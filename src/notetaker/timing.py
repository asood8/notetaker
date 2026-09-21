"""Guessing how long a run will take.

Shared by the command line and the web page, which both need to warn someone
before they commit to something that might take an afternoon.
"""

from __future__ import annotations

SECONDS_PER_SECTION = (15, 35)
"""How long one section takes, roughly, measured on a small instruct model.

Only ever used to set expectations before a long run. A bigger model, a slower
machine or a reasoning model will all leave this range behind.
"""

CHECK_OVERHEAD = 1.7
"""What checking adds. Measured: 170s against 282s over the same three sections."""


def estimate(sections: int, *, check: bool = False) -> str:
    """A range, deliberately wide. Anything narrower would be pretending."""
    overhead = CHECK_OVERHEAD if check else 1
    low, high = (round(sections * seconds * overhead) for seconds in SECONDS_PER_SECTION)
    return f"roughly {duration(low)} to {duration(high)}"


def duration(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds}s"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"{minutes} min"
    return f"{round(minutes / 60, 1)} hours"
