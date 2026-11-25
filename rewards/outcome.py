"""
Outcome availability.

The robust outcome score checks the final DB state against task.expected_state.
A task with no expected_state has nothing to check, so its robust outcome and
its divergence are not available (N/A). They are reported as null and excluded
from every average. They are never filled with a constant.
"""


def robust_outcome_available(task) -> bool:
    """True if the task has an expected_state, so robust_outcome can be checked."""
    return bool(getattr(task, "expected_state", None))
