"""Tests for priority tag parsing.

Tests cover:
- Numeric pattern matching (priority:N, prio-N, etc.)
- Keyword-based priorities (urgent, high, normal, low)
- Value clamping for out-of-range values
- Case insensitivity
- Edge cases and fallbacks
"""

import pytest

from src.filters.priority import PriorityParser


class TestPriorityParserNumericPatterns:
    """Tests for numeric priority patterns."""

    @pytest.mark.parametrize(
        "tag,expected",
        [
            # priority:N pattern
            ("priority:1", 1),
            ("priority:50", 50),
            ("priority:99", 99),
            # priority-N pattern
            ("priority-1", 1),
            ("priority-50", 50),
            ("priority-99", 99),
            # priority_N pattern
            ("priority_1", 1),
            ("priority_50", 50),
            ("priority_99", 99),
            # prio:N pattern
            ("prio:1", 1),
            ("prio:50", 50),
            ("prio:99", 99),
            # prio-N pattern
            ("prio-1", 1),
            ("prio-50", 50),
            ("prio-99", 99),
            # prio_N pattern
            ("prio_1", 1),
            ("prio_50", 50),
            ("prio_99", 99),
        ],
    )
    def test_numeric_patterns_in_range(self, tag: str, expected: int):
        """Numeric priority patterns within valid range should parse correctly."""
        result = PriorityParser.parse([tag])
        assert result == expected

    @pytest.mark.parametrize(
        "tag",
        [
            "PRIORITY:80",
            "Priority:80",
            "PRIO:80",
            "Prio:80",
            "PrIoRiTy-80",
            "PRIO_80",
        ],
    )
    def test_numeric_patterns_case_insensitive(self, tag: str):
        """Numeric patterns should be case-insensitive."""
        result = PriorityParser.parse([tag])
        assert result == 80

    def test_priority_at_boundaries(self):
        """Priority values at exact boundaries should work."""
        assert PriorityParser.parse(["priority:1"]) == 1
        assert PriorityParser.parse(["priority:99"]) == 99

    def test_first_numeric_pattern_wins(self):
        """First matching numeric pattern should be used."""
        result = PriorityParser.parse(["priority:80", "priority:90"])
        assert result == 80


class TestPriorityParserClamping:
    """Tests for priority value clamping."""

    @pytest.mark.parametrize(
        "tag,expected",
        [
            # Values below minimum should clamp to 1
            ("priority:0", 1),
            # Values above maximum should clamp to 99
            ("priority:100", 99),
            ("priority:150", 99),
            ("priority:999", 99),
        ],
    )
    def test_out_of_range_values_clamped(self, tag: str, expected: int):
        """Out-of-range priority values should be clamped to 1-99."""
        result = PriorityParser.parse([tag])
        assert result == expected

    def test_large_values_clamped(self):
        """Very large priority values should be clamped to 99."""
        result = PriorityParser.parse(["priority:9999999"])
        assert result == 99


class TestPriorityParserKeywords:
    """Tests for keyword-based priority mapping."""

    @pytest.mark.parametrize(
        "keyword,expected",
        [
            # Highest priority (90)
            ("urgent", 90),
            ("critical", 90),
            ("asap", 90),
            # High priority (75)
            ("high", 75),
            ("important", 75),
            # Normal priority (50)
            ("normal", 50),
            ("standard", 50),
            # Low priority (25)
            ("low", 25),
        ],
    )
    def test_keyword_priorities(self, keyword: str, expected: int):
        """Keyword priorities should map correctly."""
        result = PriorityParser.parse([keyword])
        assert result == expected

    @pytest.mark.parametrize(
        "keyword",
        [
            "URGENT",
            "Urgent",
            "uRgEnT",
            "HIGH",
            "High",
            "NORMAL",
            "LOW",
        ],
    )
    def test_keyword_case_insensitive(self, keyword: str):
        """Keyword matching should be case-insensitive."""
        # Just verify it doesn't return default (50 for normal, but others differ)
        result = PriorityParser.parse([keyword])
        expected = PriorityParser.KEYWORD_PRIORITIES[keyword.lower()]
        assert result == expected

    def test_first_keyword_wins(self):
        """First matching keyword should be used."""
        result = PriorityParser.parse(["urgent", "low"])
        assert result == 90


class TestPriorityParserPrecedence:
    """Tests for priority matching precedence."""

    def test_numeric_takes_precedence_over_keyword(self):
        """Numeric pattern should take precedence over keyword."""
        # Numeric pattern first
        result = PriorityParser.parse(["priority:30", "urgent"])
        assert result == 30

        # Keyword first (but numeric should still win)
        result = PriorityParser.parse(["urgent", "priority:30"])
        assert result == 30

    def test_numeric_before_keyword_in_same_position(self):
        """Numeric priority should be checked before keywords."""
        result = PriorityParser.parse(["priority:60", "high"])
        assert result == 60


class TestPriorityParserDefaults:
    """Tests for default priority handling."""

    def test_empty_tags_returns_default(self):
        """Empty tag list should return default priority."""
        result = PriorityParser.parse([])
        assert result == PriorityParser.DEFAULT_PRIORITY
        assert result == 50

    def test_none_tags_returns_default(self):
        """None tag list should return default priority."""
        result = PriorityParser.parse(None)  # type: ignore
        assert result == 50

    def test_no_matching_tags_returns_default(self):
        """Tags without priority info should return default."""
        result = PriorityParser.parse(["vip", "express", "customer-123"])
        assert result == 50


class TestPriorityParserEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_whitespace_handling(self):
        """Tags with whitespace should be handled."""
        result = PriorityParser.parse(["  priority:80  "])
        assert result == 80

        result = PriorityParser.parse(["  urgent  "])
        assert result == 90

    def test_similar_but_invalid_patterns_ignored(self):
        """Tags similar to priority patterns but invalid should be ignored."""
        # Missing separator
        result = PriorityParser.parse(["priority80"])
        assert result == 50

        # Wrong format
        result = PriorityParser.parse(["pri:80"])
        assert result == 50

        # Extra characters
        result = PriorityParser.parse(["priority:80extra"])
        assert result == 50

        # Prefix
        result = PriorityParser.parse(["mypriority:80"])
        assert result == 50

    def test_mixed_valid_invalid_tags(self):
        """Valid priority should be found among invalid tags."""
        result = PriorityParser.parse(["vip", "invalid", "priority:75", "other"])
        assert result == 75

    def test_empty_string_tag(self):
        """Empty string in tags should be ignored."""
        result = PriorityParser.parse(["", "priority:60", ""])
        assert result == 60


class TestPriorityParserUtilities:
    """Tests for utility methods."""

    def test_is_priority_tag_numeric(self):
        """is_priority_tag should identify numeric patterns."""
        assert PriorityParser.is_priority_tag("priority:50") is True
        assert PriorityParser.is_priority_tag("prio-75") is True
        assert PriorityParser.is_priority_tag("priority_99") is True

    def test_is_priority_tag_keyword(self):
        """is_priority_tag should identify keyword priorities."""
        assert PriorityParser.is_priority_tag("urgent") is True
        assert PriorityParser.is_priority_tag("high") is True
        assert PriorityParser.is_priority_tag("low") is True

    def test_is_priority_tag_invalid(self):
        """is_priority_tag should return False for non-priority tags."""
        assert PriorityParser.is_priority_tag("vip") is False
        assert PriorityParser.is_priority_tag("express") is False
        assert PriorityParser.is_priority_tag("pri:50") is False

    def test_get_keyword_priorities(self):
        """get_keyword_priorities should return all keyword mappings."""
        keywords = PriorityParser.get_keyword_priorities()
        assert keywords["urgent"] == 90
        assert keywords["high"] == 75
        assert keywords["normal"] == 50
        assert keywords["low"] == 25

    def test_get_priority_range(self):
        """get_priority_range should return valid range."""
        min_val, max_val = PriorityParser.get_priority_range()
        assert min_val == 1
        assert max_val == 99


class TestPriorityParserDocExamples:
    """Tests verifying the docstring examples work correctly."""

    def test_docstring_example_numeric(self):
        """Example: PriorityParser.parse(["vip", "priority:80"]) -> 80"""
        result = PriorityParser.parse(["vip", "priority:80"])
        assert result == 80

    def test_docstring_example_keyword(self):
        """Example: PriorityParser.parse(["urgent", "express"]) -> 90"""
        result = PriorityParser.parse(["urgent", "express"])
        assert result == 90

    def test_docstring_example_default(self):
        """Example: PriorityParser.parse(["regular"]) -> 50"""
        result = PriorityParser.parse(["regular"])
        assert result == 50

    def test_docstring_example_clamped(self):
        """Example: PriorityParser.parse(["priority:150"]) -> 99 (clamped)"""
        result = PriorityParser.parse(["priority:150"])
        assert result == 99
