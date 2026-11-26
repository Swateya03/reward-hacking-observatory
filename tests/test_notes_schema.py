"""docs/ARCHITECTURE_NOTES.md must state the result schema version the code writes.

Every statement of the form `RESULT_SCHEMA_VERSION = N` in the notes must equal
run_experiment.RESULT_SCHEMA_VERSION, and the notes must state it at least once.
"""

import re
from pathlib import Path

from run_experiment import RESULT_SCHEMA_VERSION

NOTES = Path(__file__).resolve().parents[1] / "docs" / "ARCHITECTURE_NOTES.md"
STATEMENT = re.compile(r"RESULT_SCHEMA_VERSION`?\s*=\s*`?(\d+)")


def _stated_versions() -> list[int]:
    return [int(m) for m in STATEMENT.findall(NOTES.read_text(encoding="utf-8"))]


def test_notes_state_the_current_schema_version():
    assert _stated_versions(), "ARCHITECTURE_NOTES.md must state RESULT_SCHEMA_VERSION = N"


def test_every_stated_schema_version_matches_the_code():
    stated = _stated_versions()
    wrong = [v for v in stated if v != RESULT_SCHEMA_VERSION]
    assert not wrong, (
        f"ARCHITECTURE_NOTES.md states schema {wrong}, but RESULT_SCHEMA_VERSION is "
        f"{RESULT_SCHEMA_VERSION}"
    )
