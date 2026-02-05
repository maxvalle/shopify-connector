"""Priority tag parsing for order prioritization.

Extracts and normalizes priority values from order tags,
supporting:
- Numeric priority patterns (priority:N, prio-N, etc.)
- Keyword-based priorities (urgent, high, low, etc.)
- Default fallback value
"""

import re
from typing import List, Optional, Tuple

from src.logging_config import get_logger

logger = get_logger(__name__)


class PriorityParser:
    """Parses priority from order tags.

    Supports multiple priority formats:
    1. Numeric patterns: priority:N, priority-N, priority_N, prio:N, prio-N, prio_N
       where N can be any number (values are clamped to 1-99)
    2. Keyword mapping: urgent→90, high→75, normal→50, low→25
    3. Default: 50 (middle priority)

    Priority values are clamped to the 1-99 range with warnings for out-of-range values.

    Example:
        >>> PriorityParser.parse(["vip", "priority:80"])
        80
        >>> PriorityParser.parse(["urgent", "express"])
        90
        >>> PriorityParser.parse(["regular"])
        50
        >>> PriorityParser.parse(["priority:150"])  # Clamped to 99
        99
    """

    # Default priority when no tag matches
    DEFAULT_PRIORITY = 50

    # Minimum and maximum allowed priority values
    MIN_PRIORITY = 1
    MAX_PRIORITY = 99

    # Regex patterns for numeric priority extraction
    # Matches: priority:N, priority-N, priority_N, prio:N, prio-N, prio_N
    # Captures 1+ digits to allow clamping of out-of-range values
    PRIORITY_PATTERNS = [
        re.compile(r"^priority[:\-_](\d+)$", re.IGNORECASE),
        re.compile(r"^prio[:\-_](\d+)$", re.IGNORECASE),
    ]

    # Keyword to priority mappings (all lowercase for case-insensitive matching)
    KEYWORD_PRIORITIES = {
        # Highest priority (90)
        "urgent": 90,
        "critical": 90,
        "asap": 90,
        # High priority (75)
        "high": 75,
        "important": 75,
        # Normal priority (50)
        "normal": 50,
        "standard": 50,
        # Low priority (25)
        "low": 25,
    }

    @classmethod
    def parse(cls, tags: List[str]) -> int:
        """Parse priority from a list of order tags.

        Attempts to find a priority value in the following order:
        1. Numeric pattern (priority:N, prio-N, etc.) - first match wins
        2. Keyword mapping (urgent, high, normal, low) - first match wins
        3. Default value (50) if no priority tag found

        Args:
            tags: List of tags from the order.

        Returns:
            Priority value between 1-99.
        """
        if not tags:
            logger.debug(
                "No tags provided, using default priority",
                extra={"priority": cls.DEFAULT_PRIORITY},
            )
            return cls.DEFAULT_PRIORITY

        # First, try to find a numeric priority pattern
        numeric_result = cls._find_numeric_priority(tags)
        if numeric_result is not None:
            priority, source_tag = numeric_result
            clamped = cls._clamp_priority(priority, source_tag)
            logger.debug(
                "Parsed numeric priority",
                extra={"tag": source_tag, "raw_value": priority, "clamped": clamped},
            )
            return clamped

        # Second, check for keyword priorities
        keyword_result = cls._find_keyword_priority(tags)
        if keyword_result is not None:
            priority, source_tag = keyword_result
            logger.debug(
                "Parsed keyword priority",
                extra={"tag": source_tag, "priority": priority},
            )
            return priority

        # Default priority
        logger.debug(
            "No priority tag found, using default",
            extra={"tags": tags, "priority": cls.DEFAULT_PRIORITY},
        )
        return cls.DEFAULT_PRIORITY

    @classmethod
    def _find_numeric_priority(
        cls, tags: List[str]
    ) -> Optional[Tuple[int, str]]:
        """Find a numeric priority pattern in tags.

        Args:
            tags: List of tags to search.

        Returns:
            Tuple of (priority_value, source_tag) if found, None otherwise.
        """
        for tag in tags:
            tag_stripped = tag.strip()
            for pattern in cls.PRIORITY_PATTERNS:
                match = pattern.match(tag_stripped)
                if match:
                    try:
                        priority = int(match.group(1))
                        return (priority, tag_stripped)
                    except ValueError:
                        continue
        return None

    @classmethod
    def _find_keyword_priority(
        cls, tags: List[str]
    ) -> Optional[Tuple[int, str]]:
        """Find a keyword-based priority in tags.

        Args:
            tags: List of tags to search.

        Returns:
            Tuple of (priority_value, source_tag) if found, None otherwise.
        """
        for tag in tags:
            tag_lower = tag.lower().strip()
            if tag_lower in cls.KEYWORD_PRIORITIES:
                return (cls.KEYWORD_PRIORITIES[tag_lower], tag.strip())
        return None

    @classmethod
    def _clamp_priority(cls, value: int, source_tag: str) -> int:
        """Clamp priority value to valid range and log warnings.

        Args:
            value: The parsed priority value.
            source_tag: The original tag for logging purposes.

        Returns:
            Priority clamped to MIN_PRIORITY-MAX_PRIORITY range.
        """
        if value < cls.MIN_PRIORITY:
            logger.warning(
                "Priority value below minimum, clamping to %d",
                cls.MIN_PRIORITY,
                extra={
                    "tag": source_tag,
                    "original_value": value,
                    "clamped_value": cls.MIN_PRIORITY,
                },
            )
            return cls.MIN_PRIORITY

        if value > cls.MAX_PRIORITY:
            logger.warning(
                "Priority value above maximum, clamping to %d",
                cls.MAX_PRIORITY,
                extra={
                    "tag": source_tag,
                    "original_value": value,
                    "clamped_value": cls.MAX_PRIORITY,
                },
            )
            return cls.MAX_PRIORITY

        return value

    @classmethod
    def is_priority_tag(cls, tag: str) -> bool:
        """Check if a tag is a recognized priority tag.

        Args:
            tag: The tag to check.

        Returns:
            True if the tag is a numeric priority pattern or keyword.
        """
        tag_stripped = tag.strip()

        # Check numeric patterns
        for pattern in cls.PRIORITY_PATTERNS:
            if pattern.match(tag_stripped):
                return True

        # Check keywords
        if tag_stripped.lower() in cls.KEYWORD_PRIORITIES:
            return True

        return False

    @classmethod
    def get_keyword_priorities(cls) -> dict[str, int]:
        """Get the keyword to priority mapping.

        Useful for documentation or configuration display.

        Returns:
            Dictionary of keyword to priority value mappings.
        """
        return dict(cls.KEYWORD_PRIORITIES)

    @classmethod
    def get_priority_range(cls) -> Tuple[int, int]:
        """Get the valid priority range.

        Returns:
            Tuple of (min_priority, max_priority).
        """
        return (cls.MIN_PRIORITY, cls.MAX_PRIORITY)
