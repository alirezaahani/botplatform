"""Small pure statistics helpers."""

from math import sqrt


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """The Wilson score interval for a rate (95% by default), or None if there are no trials.

    Unlike the plain normal interval it stays inside 0..1 and is not zero-width at 0/n or n/n,
    which matters because a block rate here may be 0 or 100 percent in a small batch.
    """
    if total <= 0:
        return None
    p = successes / total
    z2 = z * z
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    half = z * sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / (1 + z2 / total)
    return max(0.0, centre - half), min(1.0, centre + half)
