"""Sample entry-point helpers for ``my_project``."""


def sample_function(name: str) -> str:
    """Return a deterministic greeting used by bootstrap tests."""
    cleaned = name.strip()
    if not cleaned:
        return "Hello, world!"
    return f"Hello, {cleaned}!"
