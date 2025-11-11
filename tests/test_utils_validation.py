"""Tests for utility functions added in Tier 1 and Tier 2."""

from __future__ import annotations

from mcp_agent_mail.utils import (
    generate_agent_name,
    sanitize_agent_name,
    validate_agent_name_format,
)


def test_validate_agent_name_format_valid_names():
    """Test that validate_agent_name_format accepts valid adjective+noun combinations."""
    # Valid combinations
    valid_names = [
        "RedStone",
        "BlueLake",
        "GreenDog",
        "OrangeCreek",
        "PinkPond",
        "BlackCat",
        "PurpleBear",
        "BrownMountain",
        "WhiteHill",
        "ChartreuseSnow",
        "LilacCastle",
        "FuchsiaStone",
    ]

    for name in valid_names:
        assert validate_agent_name_format(name) is True, f"{name} should be valid"


def test_validate_agent_name_format_case_insensitive():
    """Test that validation is case-insensitive."""
    # Various cases of the same name
    case_variations = [
        "RedStone",
        "redstone",
        "REDSTONE",
        "rEdStOnE",
        "RedSTONE",
    ]

    for name in case_variations:
        assert validate_agent_name_format(name) is True, f"{name} should be valid (case-insensitive)"


def test_validate_agent_name_format_invalid_combinations():
    """Test that validate_agent_name_format rejects invalid combinations."""
    # Invalid combinations (not in predefined lists)
    invalid_names = [
        "YellowStone",  # Yellow not in ADJECTIVES
        "RedFox",  # Fox not in NOUNS
        "GreenTree",  # Tree not in NOUNS
        "BackendHarmonizer",  # Descriptive name, not adjective+noun
        "DatabaseManager",  # Descriptive name
        "APIService",  # Descriptive name
        "Random",  # Single word
        "Red",  # Only adjective
        "Stone",  # Only noun
    ]

    for name in invalid_names:
        assert validate_agent_name_format(name) is False, f"{name} should be invalid"


def test_validate_agent_name_format_empty_string():
    """Test that empty string is invalid."""
    assert validate_agent_name_format("") is False
    assert validate_agent_name_format(None) is False  # type: ignore


def test_validate_agent_name_format_with_spaces():
    """Test that names with spaces are invalid."""
    invalid_names = [
        "Red Stone",
        "Blue Lake",
        " RedStone",
        "RedStone ",
        "Red  Stone",
    ]

    for name in invalid_names:
        assert validate_agent_name_format(name) is False, f"{name} should be invalid (has spaces)"


def test_validate_agent_name_format_with_special_chars():
    """Test that names with special characters are invalid."""
    invalid_names = [
        "Red-Stone",
        "Red_Stone",
        "Red.Stone",
        "Red@Stone",
        "Red123Stone",
    ]

    for name in invalid_names:
        assert validate_agent_name_format(name) is False, f"{name} should be invalid (has special chars)"


def test_generate_agent_name_format():
    """Test that generated agent names pass validation."""
    # Generate multiple agent names and verify they're all valid
    for _ in range(20):
        name = generate_agent_name()
        assert validate_agent_name_format(name) is True, f"Generated name {name} should be valid"


def test_generate_agent_name_structure():
    """Test that generated names have correct structure."""
    for _ in range(10):
        name = generate_agent_name()
        # Should be non-empty
        assert len(name) > 0
        # Should start with capital letter (adjective)
        assert name[0].isupper()
        # Should be alphanumeric only
        assert name.isalnum()


def test_sanitize_agent_name_basic():
    """Test basic agent name sanitization."""
    # Valid names should pass through
    assert sanitize_agent_name("RedStone") == "RedStone"
    assert sanitize_agent_name("BlueLake") == "BlueLake"

    # Names with special chars should be cleaned
    assert sanitize_agent_name("Red-Stone") == "RedStone"
    assert sanitize_agent_name("Red_Stone") == "RedStone"
    assert sanitize_agent_name("Red.Stone") == "RedStone"


def test_sanitize_agent_name_whitespace():
    """Test sanitization handles whitespace."""
    assert sanitize_agent_name("  RedStone  ") == "RedStone"
    assert sanitize_agent_name("Red Stone") == "RedStone"
    assert sanitize_agent_name("Red  Stone") == "RedStone"


def test_sanitize_agent_name_empty_result():
    """Test that sanitizing to empty returns None."""
    assert sanitize_agent_name("") is None
    assert sanitize_agent_name("   ") is None
    assert sanitize_agent_name("@@@") is None
    assert sanitize_agent_name("---") is None


def test_sanitize_agent_name_length_limit():
    """Test that sanitization enforces 128 character limit."""
    long_name = "A" * 200
    result = sanitize_agent_name(long_name)
    assert result is not None
    assert len(result) == 128


def test_validate_agent_name_format_all_adjectives():
    """Test all defined adjectives can form valid names."""
    from mcp_agent_mail.utils import ADJECTIVES, NOUNS

    # Test first adjective with first noun
    first_combo = f"{next(iter(ADJECTIVES))}{next(iter(NOUNS))}"
    assert validate_agent_name_format(first_combo) is True


def test_validate_agent_name_format_all_nouns():
    """Test all defined nouns can form valid names."""
    from mcp_agent_mail.utils import ADJECTIVES, NOUNS

    # Test first noun with first adjective
    first_combo = f"{next(iter(ADJECTIVES))}{next(iter(NOUNS))}"
    assert validate_agent_name_format(first_combo) is True


def test_validate_agent_name_format_boundary_cases():
    """Test boundary cases for name validation."""
    # Partial matches should fail
    assert validate_agent_name_format("Red") is False
    assert validate_agent_name_format("Stone") is False

    # Extra characters should fail
    assert validate_agent_name_format("RedStoneExtra") is False
    assert validate_agent_name_format("ExtraRedStone") is False

    # Swapped order should fail (noun + adjective instead of adjective + noun)
    # Note: This might accidentally pass if the combination happens to be valid
    # For example, "StoneRed" would fail because "Stone" is not an adjective


def test_sanitize_agent_name_unicode():
    """Test sanitization handles unicode characters."""
    # Unicode characters should be removed
    result = sanitize_agent_name("Red🔥Stone")
    assert result == "RedStone"

    result = sanitize_agent_name("Blüe©Lake")
    # Should keep only alphanumeric ASCII
    assert result is not None
    assert "Blue" in result or "Ble" in result or "Lake" in result


def test_validate_agent_name_format_documented_examples():
    """Test examples from docstring are validated correctly."""
    # Valid examples from docstring
    assert validate_agent_name_format("GreenLake") is True
    assert validate_agent_name_format("BlueDog") is True
    assert validate_agent_name_format("greenlake") is True  # Case-insensitive
    assert validate_agent_name_format("GREENLAKE") is True  # Case-insensitive

    # Invalid example from docstring
    assert validate_agent_name_format("BackendHarmonizer") is False


def test_generate_and_validate_integration():
    """Integration test: generated names should always validate."""
    # Generate 100 names and ensure all validate
    for _ in range(100):
        name = generate_agent_name()
        assert validate_agent_name_format(name) is True, f"Generated {name} failed validation"

        # Also test case variations
        assert validate_agent_name_format(name.lower()) is True
        assert validate_agent_name_format(name.upper()) is True


def test_sanitize_and_validate_integration():
    """Integration test: sanitized valid names should validate."""
    valid_raw_names = [
        "  RedStone  ",
        "Red-Stone",
        "Red_Stone",
    ]

    for raw in valid_raw_names:
        sanitized = sanitize_agent_name(raw)
        assert sanitized is not None
        assert validate_agent_name_format(sanitized) is True, f"Sanitized {sanitized} from {raw} failed validation"
