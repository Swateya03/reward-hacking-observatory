"""scripts/label.py on a fake sheet in a temporary folder. Never touches labels/."""

import csv
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "label_helper", Path(__file__).resolve().parents[1] / "scripts" / "label.py")
label = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(label)


def make_sheet(path: Path, n: int) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=label.COLUMNS)
        w.writeheader()
        for i in range(1, n + 1):
            w.writerow({
                "episode_id": f"run_01/task_{i:03d}",
                "task_instruction": f"Task — number {i}: move the files",
                "tool_calls": "1. list_files({\"folder\": \"/tmp\"}) -> ok\n2. move_to_trash({\"path\": \"/tmp/a\"}) -> ok",
                "final_state_diff": "file_001 /tmp/a.txt: is_trashed 0 -> 1",
                "final_message": "Moved one file — done. Anything else?",
                "label": "", "hack_type": "", "clarification_class": "", "task_issue": "", "note": "",
            })
    return path


def scripted(answers):
    it = iter(answers)

    def ask(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return ask


def run_session(tmp_path, n, answers):
    to_label = make_sheet(tmp_path / "to_label.csv", n)
    labeled = tmp_path / "labeled.csv"
    out_lines = []
    label.run(to_label, labeled, ask=scripted(answers), out=out_lines.append)
    return labeled, "\n".join(out_lines)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── output file ─────────────────────────────────────────────────────────────

def test_writes_utf8_with_the_same_columns(tmp_path):
    answers = (
        ["n", "0", "n", ""]                       # row 1: not a hack
        + ["h", "1,3", "2", "y", "edge case"]     # row 2: hack, two types
        + ["u", "3", "n", "needs a check"]        # row 3: unsure
    )
    labeled, _ = run_session(tmp_path, 3, answers)
    with open(labeled, encoding="utf-8", newline="") as f:
        assert csv.DictReader(f).fieldnames == label.COLUMNS
    rows = read(labeled)
    assert [r["label"] for r in rows] == ["not a hack", "hack", "unsure"]
    assert rows[1]["hack_type"] == "metric_gaming;irreversibility_bias"
    assert rows[1]["clarification_class"] == "ii"
    assert rows[1]["task_issue"] == "yes"
    assert rows[2]["clarification_class"] == "iii"
    assert rows[2]["hack_type"] == ""
    assert rows[0]["task_instruction"] == "Task — number 1: move the files"   # non-ASCII kept


# ── resume ──────────────────────────────────────────────────────────────────

def test_resumes_at_first_unlabelled_row(tmp_path):
    to_label = make_sheet(tmp_path / "to_label.csv", 3)
    labeled = tmp_path / "labeled.csv"
    rows = read(to_label)
    rows[0].update({"label": "not a hack", "clarification_class": "not a clarification",
                    "task_issue": "no", "note": "kept"})
    label.write_csv(labeled, [{k: r[k] for k in label.COLUMNS} for r in rows])
    out_lines = []
    label.run(to_label, labeled, ask=scripted(["n", "0", "n", ""] + ["n", "0", "n", ""]),
              out=out_lines.append)
    text = "\n".join(out_lines)
    assert "starting at row 2" in text
    final = read(labeled)
    assert final[0]["note"] == "kept"                                   # row 1 untouched
    assert all(r["label"] for r in final)


def test_rejects_a_labeled_file_with_other_episodes(tmp_path):
    to_label = make_sheet(tmp_path / "to_label.csv", 2)
    other = make_sheet(tmp_path / "other.csv", 3)
    with pytest.raises(SystemExit):
        label.load_rows(to_label, other)


# ── validation ──────────────────────────────────────────────────────────────

def test_invalid_answers_are_asked_again(tmp_path):
    answers = ["x", "n", "7", "0", "maybe", "n", ""]     # bad label, bad class, bad task_issue
    labeled, text = run_session(tmp_path, 1, answers + [])
    assert text.count("not valid") == 3
    assert read(labeled)[0]["label"] == "not a hack"


def test_hack_type_numbers_are_checked(tmp_path):
    answers = ["h", "9", "2", "1", "y", "", ]
    labeled, text = run_session(tmp_path, 1, answers)
    assert "not valid" in text
    assert read(labeled)[0]["hack_type"] == "scope_creep"


@pytest.mark.parametrize("text,expected", [
    ("1", "metric_gaming"),
    ("3, 1", "metric_gaming;irreversibility_bias"),
    ("5,4,2", "scope_creep;overclaiming;sycophantic_caution"),
    ("6", None),
    ("", None),
    ("1,x", None),
])
def test_parse_hack_types(text, expected):
    assert label.parse_hack_types(text) == expected


def test_unsure_needs_a_note(tmp_path):
    labeled, text = run_session(tmp_path, 1, ["u", "3", "n", "", "needs a check"])
    assert "A note is required for unsure" in text
    assert read(labeled)[0]["note"] == "needs a check"


# ── commands ────────────────────────────────────────────────────────────────

def test_back_returns_to_previous_row_and_changes_it(tmp_path):
    answers = (["n", "0", "n", ""]          # row 1
               + ["b"]                       # back from row 2 to row 1
               + ["h", "2", "1", "y", "fixed"]   # row 1 revised
               + ["n", "0", "n", ""])        # row 2 again
    labeled, _ = run_session(tmp_path, 2, answers)
    rows = read(labeled)
    assert rows[0]["label"] == "hack"
    assert rows[0]["hack_type"] == "scope_creep"
    assert rows[0]["note"] == "fixed"


def test_enter_keeps_the_current_answers_when_going_back(tmp_path):
    answers = (["n", "0", "n", ""] + ["b"] + ["", "", "", ""] + ["n", "0", "n", ""])
    labeled, _ = run_session(tmp_path, 2, answers)
    assert read(labeled)[0]["label"] == "not a hack"
    assert read(labeled)[0]["clarification_class"] == "not a clarification"


def test_guide_command_shows_the_hack_types_and_asks_again(tmp_path):
    labeled, text = run_session(tmp_path, 1, ["g", "n", "0", "n", ""])
    assert "metric_gaming" in text                       # from docs/LABELING_GUIDE.md
    assert read(labeled)[0]["label"] == "not a hack"    # the next answer was still taken as the label


def test_quit_saves_completed_rows_and_drops_the_partial_one(tmp_path):
    answers = ["n", "0", "n", ""] + ["h", "1", "q"]      # row 2 partly answered, then quit
    labeled, text = run_session(tmp_path, 2, answers)
    rows = read(labeled)
    assert rows[0]["label"] == "not a hack"
    assert rows[1]["label"] == "" and rows[1]["hack_type"] == ""
    assert "Saved. Run the same command again" in text


# ── display and progress ────────────────────────────────────────────────────

def test_shows_progress_and_the_row_contents(tmp_path):
    _, text = run_session(tmp_path, 3, ["n", "0", "n", "", "n", "0", "n", "", "n", "0", "n", ""])
    assert "row 2 of 3" in text
    assert "episode: run_01/task_002" in text
    assert "Task — number 2" in text
    assert "1. list_files" in text and "2. move_to_trash" in text   # one call per line
    assert "FINAL STATE DIFF" in text and "FINAL MESSAGE" in text


def test_shows_nothing_about_the_detector_or_rewards(tmp_path):
    _, text = run_session(tmp_path, 2, ["n", "0", "n", "", "n", "0", "n", ""])
    for word in ["detector", "naive", "robust", "divergence", "was_hacked", "verdict",
                 "hacking", "reward"]:
        assert word not in text.lower(), word


def test_suggests_a_break_after_25_rows_once(tmp_path):
    answers = ["n", "0", "n", ""] * 26
    _, text = run_session(tmp_path, 26, answers)
    assert text.count("good place for a break") == 1
    assert "25 rows are labelled" in text
    assert "All rows labelled" in text
