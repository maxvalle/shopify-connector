"""Tag-based order filtering with whitelist/blacklist support.

Implements the filtering logic for orders based on their tags,
supporting:
- Whitelist: Only include orders with specified tags
- Blacklist: Exclude orders with specified tags (takes precedence)
- Multiple matching modes: exact, contains, regex
"""

import re
from typing import List, Tuple

from src.config import TagMatchMode
from src.logging_config import get_logger

logger = get_logger(__name__)


class TagFilter:
    """Filters orders based on whitelist and blacklist tags.

    The filter implements the following precedence rules:
    1. Blacklist takes precedence (deny-first model)
    2. If whitelist is configured, order must have at least one whitelist tag
    3. If no whitelist configured, order is included by default

    Truth table:
    | Whitelist | Blacklist | Has WL Tag | Has BL Tag | Result  |
    |-----------|-----------|------------|------------|---------|
    | Empty     | Empty     | -          | -          | INCLUDE |
    | Empty     | Set       | -          | No         | INCLUDE |
    | Empty     | Set       | -          | Yes        | EXCLUDE |
    | Set       | Empty     | Yes        | -          | INCLUDE |
    | Set       | Empty     | No         | -          | EXCLUDE |
    | Set       | Set       | Yes        | No         | INCLUDE |
    | Set       | Set       | Yes        | Yes        | EXCLUDE |
    | Set       | Set       | No         | No         | EXCLUDE |

    Example:
        >>> filter = TagFilter(
        ...     whitelist=["vip", "express"],
        ...     blacklist=["hold", "test"],
        ...     match_mode=TagMatchMode.EXACT,
        ... )
        >>> filter.should_include(["vip", "regular"])
        (True, "Matched whitelist tag: vip")
        >>> filter.should_include(["vip", "hold"])
        (False, "Matched blacklist tag: hold")
    """

    def __init__(
        self,
        whitelist: List[str] | None = None,
        blacklist: List[str] | None = None,
        match_mode: TagMatchMode = TagMatchMode.EXACT,
    ):
        """Initialize the tag filter.

        Args:
            whitelist: List of tags that allow inclusion. Empty means no whitelist.
            blacklist: List of tags that force exclusion.
            match_mode: How to match tags (exact, contains, regex).
        """
        self.whitelist = [tag.lower() for tag in (whitelist or [])]
        self.blacklist = [tag.lower() for tag in (blacklist or [])]
        self.match_mode = match_mode

        # Pre-compile regex patterns if using regex mode
        self._whitelist_patterns: list[re.Pattern] = []
        self._blacklist_patterns: list[re.Pattern] = []

        if match_mode == TagMatchMode.REGEX:
            self._whitelist_patterns = [
                re.compile(pattern, re.IGNORECASE) for pattern in self.whitelist
            ]
            self._blacklist_patterns = [
                re.compile(pattern, re.IGNORECASE) for pattern in self.blacklist
            ]

        logger.debug(
            "Tag filter initialized",
            extra={
                "whitelist": self.whitelist,
                "blacklist": self.blacklist,
                "match_mode": match_mode.value,
            },
        )

    def should_include(self, tags: List[str]) -> Tuple[bool, str]:
        """Determine if an order with given tags should be included.

        Args:
            tags: List of tags from the order.

        Returns:
            Tuple of (should_include, reason) where reason explains the decision.
        """
        normalized_tags = [tag.lower() for tag in tags]

        # Check blacklist first (deny-first model)
        if self.blacklist:
            matched_bl_tag = self._find_matching_tag(normalized_tags, is_blacklist=True)
            if matched_bl_tag:
                reason = f"Matched blacklist tag: {matched_bl_tag}"
                logger.debug(reason, extra={"tags": tags})
                return False, reason

        # Check whitelist (if configured)
        if self.whitelist:
            matched_wl_tag = self._find_matching_tag(
                normalized_tags, is_blacklist=False
            )
            if matched_wl_tag:
                reason = f"Matched whitelist tag: {matched_wl_tag}"
                logger.debug(reason, extra={"tags": tags})
                return True, reason
            else:
                reason = "No whitelist tag matched"
                logger.debug(reason, extra={"tags": tags})
                return False, reason

        # No whitelist configured, include by default
        return True, "No whitelist configured, included by default"

    def _find_matching_tag(
        self, tags: List[str], is_blacklist: bool
    ) -> str | None:
        """Find a matching tag in the filter list.

        Args:
            tags: Normalized (lowercase) tags to check.
            is_blacklist: Whether to check against blacklist or whitelist.

        Returns:
            The first matching tag, or None if no match found.
        """
        filter_list = self.blacklist if is_blacklist else self.whitelist
        patterns = (
            self._blacklist_patterns if is_blacklist else self._whitelist_patterns
        )

        for tag in tags:
            if self.match_mode == TagMatchMode.EXACT:
                if tag in filter_list:
                    return tag

            elif self.match_mode == TagMatchMode.CONTAINS:
                for filter_tag in filter_list:
                    if filter_tag in tag or tag in filter_tag:
                        return tag

            elif self.match_mode == TagMatchMode.REGEX:
                for pattern in patterns:
                    if pattern.search(tag):
                        return tag

        return None

    def __repr__(self) -> str:
        """Return string representation of the filter."""
        return (
            f"TagFilter(whitelist={self.whitelist}, "
            f"blacklist={self.blacklist}, "
            f"match_mode={self.match_mode.value})"
        )
