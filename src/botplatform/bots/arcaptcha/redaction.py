"""Keeping the password out of recorded text."""


def redact(text: str, password: str, keep: str) -> str:
    """Replace the password everywhere except inside `keep`, such as the site's host name.

    A short password like `demo` would otherwise turn `demo.arcaptcha.co` into nonsense.
    Anywhere else, even a match followed by a dot, is replaced: over-redacting is fine.
    """
    if not keep:
        return text.replace(password, "[password]")
    return keep.join(part.replace(password, "[password]") for part in text.split(keep))
