"""Test file to verify pre-commit hooks work."""


def poorly_formatted(x, y, z):  # Bad formatting - should be fixed by ruff format
    """Function with poor formatting."""
    return x + y + z  # Missing spaces


if __name__ == "__main__":  # Missing spaces - should be fixed by ruff format
    result = poorly_formatted(1, 2, 3)  # Missing spaces
    print(result)
