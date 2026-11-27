"""Terminal labelling helper for the detector-validation sample.

Reads labels/to_label.csv and writes labels/labeled.csv (UTF-8, same columns). If labeled.csv
exists, it resumes at the first unlabelled row. Saves after every completed row.

Shows only what the labeller needs: episode ID, task instruction, tool calls, final state diff,
final message. It shows nothing about the detector or the reward functions.

Questions, in order (single-key answers):
  label                h = hack, n = not a hack, u = unsure (unsure needs a note)
  hack_type            only if hack: numbers 1-5, comma-separated, e.g. 1,3
  clarification_class  1 = i, 2 = ii, 3 = iii, 0 = not a clarification
  task_issue           y / n
  note                 free text; Enter keeps the current note; "-" clears it

Commands at any question:
  b  go back to the previous row (its answers can be changed; Enter keeps each one)
  g  show the labelling guide for the hack types
  q  save and quit (a row that is only partly answered is not saved)

Run from the repository root:
  python scripts/label.py
"""

import argparse
import csv
import os
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TO_LABEL = REPO / "labels" / "to_label.csv"
LABELED = REPO / "labels" / "labeled.csv"
GUIDE = REPO / "docs" / "LABELING_GUIDE.md"

COLUMNS = [
    "episode_id", "task_instruction", "tool_calls", "final_state_diff", "final_message",
    "label", "hack_type", "clarification_class", "task_issue", "note",
]
HACK_TYPES = ["metric_gaming", "scope_creep", "irreversibility_bias", "overclaiming",
              "sycophantic_caution"]
CLASSES = {"1": "i", "2": "ii", "3": "iii", "0": "not a clarification"}
LABEL_KEYS = {"h": "hack", "hack": "hack", "n": "not a hack", "not a hack": "not a hack",
              "u": "unsure", "unsure": "unsure"}
BREAK_AFTER = 25
WIDTH = 100
STEPS = ["label", "hack_type", "clarification_class", "task_issue", "note"]
PROMPTS = {
    "label": "label [h hack / n not a hack / u unsure]",
    "hack_type": "hack type(s) [1 metric_gaming, 2 scope_creep, 3 irreversibility_bias, "
                 "4 overclaiming, 5 sycophantic_caution; e.g. 1,3]",
    "clarification_class": "clarification class [1 i, 2 ii, 3 iii, 0 not a clarification]",
    "task_issue": "task_issue [y / n]",
    "note": "note (free text; Enter keeps; - clears)",
}


class Quit(Exception):
    pass


# ── data ────────────────────────────────────────────────────────────────────

def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise SystemExit(f"{path}: columns must be {COLUMNS}, found {reader.fieldnames}")
        return list(reader)


def write_csv(path: Path, rows: list[dict]) -> None:
    """Write to a temporary file, then replace, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def load_rows(to_label: Path, labeled: Path) -> list[dict]:
    """The labeled file if it exists (same episodes, same order), else the blank sheet."""
    source = read_csv(to_label)
    if not labeled.exists():
        for r in source:
            for key in COLUMNS[5:]:
                r[key] = ""
        return source
    done = read_csv(labeled)
    if [r["episode_id"] for r in done] != [r["episode_id"] for r in source]:
        raise SystemExit(f"{labeled} does not list the same episodes, in the same order, as {to_label}")
    return done


def first_unlabelled(rows: list[dict]) -> int:
    for i, r in enumerate(rows):
        if not r["label"]:
            return i
    return 0


# ── parsing: each returns a value, or None when the answer is not valid ─────

def parse_label(text: str):
    return LABEL_KEYS.get(text.strip().lower())


def parse_hack_types(text: str):
    picks = [p.strip() for p in text.split(",") if p.strip()]
    if not picks or any(p not in {"1", "2", "3", "4", "5"} for p in picks):
        return None
    return ";".join(HACK_TYPES[int(p) - 1] for p in sorted(set(picks), key=int))


def parse_class(text: str):
    return CLASSES.get(text.strip())


def parse_yes_no(text: str):
    return {"y": "yes", "yes": "yes", "n": "no", "no": "no"}.get(text.strip().lower())


# ── display ─────────────────────────────────────────────────────────────────

def _wrap(text: str, indent: str) -> list[str]:
    lines = []
    for paragraph in (text or "").splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, WIDTH, initial_indent=indent,
                                   subsequent_indent=indent + "  ") or [indent])
    return lines


def render(row: dict, idx: int, total: int) -> str:
    bar = "=" * WIDTH
    out = [bar, f"row {idx + 1} of {total}   episode: {row['episode_id']}", bar,
           "", "TASK", *_wrap(row["task_instruction"], "  "),
           "", "TOOL CALLS"]
    for call in (row["tool_calls"] or "(none)").splitlines():
        out.extend(_wrap(call, "  "))
    out += ["", "FINAL STATE DIFF", *_wrap(row["final_state_diff"], "  "),
            "", "FINAL MESSAGE", *_wrap(row["final_message"], "  "), ""]
    return "\n".join(out)


def guide_text() -> str:
    if not GUIDE.exists():
        return f"(guide not found: {GUIDE})"
    text = GUIDE.read_text(encoding="utf-8")
    start = text.find("## 2. The five hack types")
    end = text.find("## 3. Not a hack")
    if start == -1 or end == -1:
        return "(guide section not found)"
    return text[start:end].strip()


# ── the labelling session ───────────────────────────────────────────────────

def ask_step(step: str, row: dict, ask, out):
    """Ask one question. Returns ("value", v) or ("back", None). Raises Quit on q."""
    current = row.get(step, "")
    shown = f" (now: {current})" if current else ""
    while True:
        text = ask(f"{PROMPTS[step]}{shown}: ").strip()
        low = text.lower()
        if low == "q":
            raise Quit()
        if low == "b":
            return ("back", None)
        if low == "g":
            out(guide_text())
            out("")
            continue
        if step == "note":
            if text == "":
                if row["label"] == "unsure" and not current:
                    out("A note is required for unsure. Say what would settle it.")
                    continue
                return ("value", current)
            if text == "-":
                if row["label"] == "unsure":
                    out("A note is required for unsure.")
                    continue
                return ("value", "")
            return ("value", text)
        if text == "" and current:
            return ("value", current)
        if step == "label":
            value = parse_label(text)
        elif step == "hack_type":
            value = parse_hack_types(text)
        elif step == "clarification_class":
            value = parse_class(text)
        else:
            value = parse_yes_no(text)
        if value is None:
            out(f"not valid: {text!r}. Try again (or b, g, q).")
            continue
        return ("value", value)


def label_rows(rows: list[dict], start: int, save, ask, out) -> None:
    idx = start
    total = len(rows)
    suggested = False
    while idx < total:
        row = rows[idx]
        snapshot = dict(row)   # restored if the labeller quits part-way through this row
        out(render(row, idx, total))
        step_i = 0
        back = False
        try:
            while step_i < len(STEPS):
                step = STEPS[step_i]
                if step == "hack_type" and row["label"] != "hack":
                    row["hack_type"] = ""          # not a hack: no hack type
                    step_i += 1
                    continue
                kind, value = ask_step(step, row, ask, out)
                if kind == "back":
                    back = True
                    break
                row[step] = value
                step_i += 1
        except Quit:
            row.update(snapshot)
            save(rows)
            raise
        if back:
            if idx == 0:
                out("Already at the first row.")
            else:
                idx -= 1
            continue
        save(rows)
        labelled = sum(1 for r in rows if r["label"])
        out(f"saved. {labelled} of {total} rows labelled.")
        if labelled >= BREAK_AFTER and not suggested:
            suggested = True
            out(f"{BREAK_AFTER} rows are labelled. This is a good place for a break. "
                "Progress is saved; type q at any question to stop.")
        idx += 1
    out("All rows labelled. Labels are in labels/labeled.csv.")


def run(to_label: Path, labeled: Path, ask=input, out=print) -> int:
    rows = load_rows(to_label, labeled)
    start = first_unlabelled(rows)

    def save(rs):
        write_csv(labeled, rs)

    save(rows)
    out(f"{len(rows)} rows; starting at row {start + 1}. Commands: b back, g guide, q save and quit.")
    try:
        label_rows(rows, start, save, ask, out)
    except (Quit, EOFError):
        out("Saved. Run the same command again to resume.")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to-label", type=Path, default=TO_LABEL)
    parser.add_argument("--labeled", type=Path, default=LABELED)
    args = parser.parse_args(argv)
    return run(args.to_label, args.labeled)


if __name__ == "__main__":
    sys.exit(main())
