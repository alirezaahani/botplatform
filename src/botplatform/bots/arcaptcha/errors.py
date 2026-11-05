"""Short descriptions of exceptions for events."""


def describe(error: Exception, limit: int = 200) -> str:
    """`<TypeName>: <first line of the message, cut to limit>`; just the type name if no message."""
    lines = str(error).splitlines()
    first = lines[0][:limit] if lines else ""
    name = type(error).__name__
    return f"{name}: {first}" if first else name
