"""Test file to reproduce Ruff formatting issue that caused CI failures."""


def test_inbox_filtering():
    """Test that would have passed locally with 0.14.4 but failed in CI with 0.14.1."""
    inbox_items = [1, 2, 3, 4, 5]
    inbox_limit = 10

    # This formatting was the issue - 0.14.4 formatted it multi-line,
    # but 0.14.1 wanted it single-line
    assert len(inbox_items) <= inbox_limit, "inbox_limit should cap the number of returned messages"

    # Another example
    assert all(isinstance(item, int) for item in inbox_items), "all items should be integers"

    # This should also trigger formatting differences
    result = "This is a long string that might be formatted differently between Ruff versions"
    assert result is not None


def test_another_formatting_case():
    """Additional formatting edge case."""
    data = {"key": "value"}

    assert all(k in data for k in ["key"]), "required keys should be present"
