"""Tests for tag-based order filtering.

Tests cover:
- Truth table from the plan (blacklist/whitelist combinations)
- All match modes: exact, contains, regex
- Case insensitivity
- Edge cases
"""

import pytest

from src.config import TagMatchMode
from src.filters.tags import TagFilter


class TestTagFilterTruthTable:
    """Tests verifying the truth table from the plan.

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
    """

    def test_empty_whitelist_empty_blacklist_includes_all(self):
        """No filters configured - include everything."""
        tag_filter = TagFilter(whitelist=[], blacklist=[])
        
        included, reason = tag_filter.should_include(["any", "tag"])
        assert included is True
        assert "included by default" in reason.lower()

    def test_empty_whitelist_empty_blacklist_includes_empty_tags(self):
        """No filters configured - include orders with no tags."""
        tag_filter = TagFilter(whitelist=[], blacklist=[])
        
        included, reason = tag_filter.should_include([])
        assert included is True

    def test_empty_whitelist_blacklist_set_no_match_includes(self):
        """Blacklist set, order has no blacklisted tags - include."""
        tag_filter = TagFilter(whitelist=[], blacklist=["hold", "test"])
        
        included, reason = tag_filter.should_include(["vip", "regular"])
        assert included is True

    def test_empty_whitelist_blacklist_set_match_excludes(self):
        """Blacklist set, order has blacklisted tag - exclude."""
        tag_filter = TagFilter(whitelist=[], blacklist=["hold", "test"])
        
        included, reason = tag_filter.should_include(["vip", "hold"])
        assert included is False
        assert "blacklist" in reason.lower()
        assert "hold" in reason.lower()

    def test_whitelist_set_empty_blacklist_match_includes(self):
        """Whitelist set, order has whitelisted tag - include."""
        tag_filter = TagFilter(whitelist=["vip", "express"], blacklist=[])
        
        included, reason = tag_filter.should_include(["vip", "regular"])
        assert included is True
        assert "whitelist" in reason.lower()
        assert "vip" in reason.lower()

    def test_whitelist_set_empty_blacklist_no_match_excludes(self):
        """Whitelist set, order has no whitelisted tags - exclude."""
        tag_filter = TagFilter(whitelist=["vip", "express"], blacklist=[])
        
        included, reason = tag_filter.should_include(["regular", "standard"])
        assert included is False
        assert "no whitelist tag matched" in reason.lower()

    def test_both_set_whitelist_match_no_blacklist_match_includes(self):
        """Both configured, order matches whitelist but not blacklist - include."""
        tag_filter = TagFilter(
            whitelist=["vip", "express"],
            blacklist=["hold", "test"],
        )
        
        included, reason = tag_filter.should_include(["vip", "regular"])
        assert included is True
        assert "whitelist" in reason.lower()

    def test_both_set_whitelist_match_blacklist_match_excludes(self):
        """Both configured, order matches both - exclude (blacklist wins)."""
        tag_filter = TagFilter(
            whitelist=["vip", "express"],
            blacklist=["hold", "test"],
        )
        
        included, reason = tag_filter.should_include(["vip", "hold"])
        assert included is False
        assert "blacklist" in reason.lower()

    def test_both_set_no_whitelist_match_no_blacklist_match_excludes(self):
        """Both configured, order matches neither - exclude (no whitelist match)."""
        tag_filter = TagFilter(
            whitelist=["vip", "express"],
            blacklist=["hold", "test"],
        )
        
        included, reason = tag_filter.should_include(["regular", "standard"])
        assert included is False
        assert "no whitelist tag matched" in reason.lower()


class TestTagFilterCaseSensitivity:
    """Tests for case-insensitive matching."""

    def test_whitelist_case_insensitive(self):
        """Whitelist matching should be case-insensitive."""
        tag_filter = TagFilter(whitelist=["VIP", "Express"], blacklist=[])
        
        # Various case combinations should match
        assert tag_filter.should_include(["vip"])[0] is True
        assert tag_filter.should_include(["VIP"])[0] is True
        assert tag_filter.should_include(["Vip"])[0] is True
        assert tag_filter.should_include(["EXPRESS"])[0] is True
        assert tag_filter.should_include(["express"])[0] is True

    def test_blacklist_case_insensitive(self):
        """Blacklist matching should be case-insensitive."""
        tag_filter = TagFilter(whitelist=[], blacklist=["HOLD", "Test"])
        
        # Various case combinations should match
        assert tag_filter.should_include(["hold"])[0] is False
        assert tag_filter.should_include(["HOLD"])[0] is False
        assert tag_filter.should_include(["Hold"])[0] is False
        assert tag_filter.should_include(["TEST"])[0] is False
        assert tag_filter.should_include(["test"])[0] is False


class TestTagFilterExactMode:
    """Tests for exact matching mode (default)."""

    def test_exact_match_required(self):
        """Exact mode requires exact string match."""
        tag_filter = TagFilter(
            whitelist=["vip"],
            blacklist=[],
            match_mode=TagMatchMode.EXACT,
        )
        
        assert tag_filter.should_include(["vip"])[0] is True
        assert tag_filter.should_include(["vip-gold"])[0] is False
        assert tag_filter.should_include(["super-vip"])[0] is False

    def test_exact_blacklist_match(self):
        """Exact blacklist requires exact string match."""
        tag_filter = TagFilter(
            whitelist=[],
            blacklist=["test"],
            match_mode=TagMatchMode.EXACT,
        )
        
        assert tag_filter.should_include(["test"])[0] is False
        assert tag_filter.should_include(["test-order"])[0] is True
        assert tag_filter.should_include(["my-test"])[0] is True


class TestTagFilterContainsMode:
    """Tests for contains matching mode."""

    def test_contains_partial_match(self):
        """Contains mode matches partial strings."""
        tag_filter = TagFilter(
            whitelist=["vip"],
            blacklist=[],
            match_mode=TagMatchMode.CONTAINS,
        )
        
        assert tag_filter.should_include(["vip"])[0] is True
        assert tag_filter.should_include(["vip-gold"])[0] is True
        assert tag_filter.should_include(["super-vip"])[0] is True
        assert tag_filter.should_include(["regular"])[0] is False

    def test_contains_blacklist_partial_match(self):
        """Contains blacklist matches partial strings."""
        tag_filter = TagFilter(
            whitelist=[],
            blacklist=["test"],
            match_mode=TagMatchMode.CONTAINS,
        )
        
        assert tag_filter.should_include(["test"])[0] is False
        assert tag_filter.should_include(["test-order"])[0] is False
        assert tag_filter.should_include(["my-test"])[0] is False
        assert tag_filter.should_include(["production"])[0] is True

    def test_contains_bidirectional(self):
        """Contains mode works bidirectionally (tag in filter OR filter in tag)."""
        tag_filter = TagFilter(
            whitelist=["priority"],
            blacklist=[],
            match_mode=TagMatchMode.CONTAINS,
        )
        
        # Filter pattern in tag
        assert tag_filter.should_include(["high-priority"])[0] is True
        # Tag in filter pattern
        assert tag_filter.should_include(["prio"])[0] is True


class TestTagFilterRegexMode:
    """Tests for regex matching mode."""

    def test_regex_pattern_match(self):
        """Regex mode supports regular expression patterns."""
        tag_filter = TagFilter(
            whitelist=[r"vip-\d+", r"express.*"],
            blacklist=[],
            match_mode=TagMatchMode.REGEX,
        )
        
        assert tag_filter.should_include(["vip-123"])[0] is True
        assert tag_filter.should_include(["vip-gold"])[0] is False
        assert tag_filter.should_include(["express"])[0] is True
        assert tag_filter.should_include(["express-shipping"])[0] is True
        assert tag_filter.should_include(["regular"])[0] is False

    def test_regex_blacklist_pattern(self):
        """Regex blacklist supports regular expression patterns."""
        tag_filter = TagFilter(
            whitelist=[],
            blacklist=[r"test.*", r"dev-\d+"],
            match_mode=TagMatchMode.REGEX,
        )
        
        assert tag_filter.should_include(["test"])[0] is False
        assert tag_filter.should_include(["test-order"])[0] is False
        assert tag_filter.should_include(["dev-123"])[0] is False
        assert tag_filter.should_include(["dev-abc"])[0] is True
        assert tag_filter.should_include(["production"])[0] is True

    def test_regex_case_insensitive(self):
        """Regex patterns should be case-insensitive."""
        tag_filter = TagFilter(
            whitelist=[r"VIP.*"],
            blacklist=[],
            match_mode=TagMatchMode.REGEX,
        )
        
        assert tag_filter.should_include(["VIP-gold"])[0] is True
        assert tag_filter.should_include(["vip-gold"])[0] is True
        assert tag_filter.should_include(["Vip-Gold"])[0] is True


class TestTagFilterEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_order_tags_with_whitelist(self):
        """Order with no tags should be excluded if whitelist is set."""
        tag_filter = TagFilter(whitelist=["vip"], blacklist=[])
        
        included, reason = tag_filter.should_include([])
        assert included is False
        assert "no whitelist tag matched" in reason.lower()

    def test_empty_order_tags_without_filters(self):
        """Order with no tags should be included if no filters set."""
        tag_filter = TagFilter(whitelist=[], blacklist=[])
        
        included, _ = tag_filter.should_include([])
        assert included is True

    def test_none_whitelist_treated_as_empty(self):
        """None whitelist should be treated as empty list."""
        tag_filter = TagFilter(whitelist=None, blacklist=None)
        
        included, _ = tag_filter.should_include(["any"])
        assert included is True

    def test_multiple_whitelist_matches(self):
        """Order matching multiple whitelist tags should be included."""
        tag_filter = TagFilter(
            whitelist=["vip", "express", "priority"],
            blacklist=[],
        )
        
        included, reason = tag_filter.should_include(["vip", "express", "priority"])
        assert included is True

    def test_multiple_blacklist_matches(self):
        """Order matching multiple blacklist tags should be excluded."""
        tag_filter = TagFilter(
            whitelist=[],
            blacklist=["hold", "test", "do-not-ship"],
        )
        
        included, reason = tag_filter.should_include(["hold", "test"])
        assert included is False

    def test_repr_string(self):
        """TagFilter should have a useful string representation."""
        tag_filter = TagFilter(
            whitelist=["vip"],
            blacklist=["test"],
            match_mode=TagMatchMode.CONTAINS,
        )
        
        repr_str = repr(tag_filter)
        assert "TagFilter" in repr_str
        assert "vip" in repr_str
        assert "test" in repr_str
        assert "contains" in repr_str

    def test_whitespace_in_tags(self):
        """Tags with whitespace should be handled correctly."""
        tag_filter = TagFilter(
            whitelist=["vip customer"],
            blacklist=[],
        )
        
        # Exact match with whitespace
        assert tag_filter.should_include(["vip customer"])[0] is True
        assert tag_filter.should_include(["vip"])[0] is False


class TestTagFilterFirstMatchReturned:
    """Tests that verify the first matching tag is returned in reason."""

    def test_first_blacklist_match_in_reason(self):
        """The first matching blacklist tag should appear in reason."""
        tag_filter = TagFilter(
            whitelist=[],
            blacklist=["hold", "test"],
        )
        
        # When order has "hold" first
        _, reason = tag_filter.should_include(["hold", "test"])
        assert "hold" in reason.lower()

    def test_first_whitelist_match_in_reason(self):
        """The first matching whitelist tag should appear in reason."""
        tag_filter = TagFilter(
            whitelist=["vip", "express"],
            blacklist=[],
        )
        
        # When order has "vip" first
        _, reason = tag_filter.should_include(["vip", "express"])
        assert "vip" in reason.lower()
