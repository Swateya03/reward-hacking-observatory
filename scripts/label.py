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
  v  view details: the full result of each tool call, and the original fixture items the task
     refers to (no detector, reward or score fields are shown)
  r  add a labelling rule to docs/LABELING_DECISIONS.md (x cancels it)
  R  show the labelling rules, then ask the same question again

Run from the repository root:
  python scripts/label.py
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TO_LABEL = REPO / "labels" / "to_label.csv"
LABELED = REPO / "labels" / "labeled.csv"
GUIDE = REPO / "docs" / "LABELING_GUIDE.md"
RUNS_DIR = REPO / "results" / "runs" / "claude-haiku-5-5" / "rescored_v8"
FIXTURE_PATH = REPO / "workspace" / "fixtures" / "default.json"
DECISIONS_PATH = REPO / "docs" / "LABELING_DECISIONS.md"

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


# ── details view (v) ───────────────────────────────────────────────────────

# Field names that belong to the detector or the rewards. They are removed from anything the
# details view prints. Matched against key names, not against free text: the fixture's spam
# email legitimately contains the word "reward" in its body.
FORBIDDEN_KEY = re.compile(
    r"hack|score|reward|detector|diverg|naive|robust|severity|reversib|scope|closing|"
    r"raw_type|subtype|verdict|intermediate|policy|metric", re.IGNORECASE)
ID_RE = re.compile(r"\b(?:file|email|event)_\d{3}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PATH_RE = re.compile(r"/[\w./-]*\w")
FOLDER_WORDS = ("inbox", "trash", "sent", "drafts", "spam", "archive")
EMAIL_LABELS = {"sender": "from", "recipient": "to"}


def sanitize(obj):
    """Copy of obj with every dict key that names a detector, reward or score field removed."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if not FORBIDDEN_KEY.search(str(k))}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def load_record(runs_dir: Path, episode_id: str):
    run, task = episode_id.split("/")
    path = Path(runs_dir) / run / f"{task}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def tool_calls(record: dict):
    """(tool, arguments, result) for each tool call in the stored trajectory, in order."""
    for step in record.get("trajectory", []):
        if step.get("type") == "tool_call":
            yield step.get("tool"), step.get("arguments") or {}, step.get("result")


def referenced_fixture_items(fixture: dict, instruction: str, record: dict) -> list:
    """Fixture items the task refers to: named by id in the agent's tool arguments, or matched by
    an address, path, folder word or event title in the task instruction."""
    ids = set()
    for _, args, _ in tool_calls(record):
        ids.update(ID_RE.findall(json.dumps(args, ensure_ascii=False)))
    low = instruction.lower()
    addresses = set(EMAIL_RE.findall(instruction))
    paths = set(PATH_RE.findall(instruction))
    words = {w for w in FOLDER_WORDS if re.search(rf"\b{w}\b", low)}
    picked = []
    for kind in ("emails", "files", "events"):
        for item in fixture.get(kind, []):
            title = (item.get("title") or "").lower()
            hit = (
                item["id"] in ids
                or (kind == "emails" and (item.get("sender") in addresses
                                          or item.get("recipient") in addresses
                                          or item.get("folder") in words))
                or (kind == "files" and (item.get("folder") in paths
                                         or item.get("path") in paths
                                         or item.get("folder") in words
                                         or any(item.get("path", "").startswith(p.rstrip("/") + "/")
                                                for p in paths)))
                or (kind == "events" and bool(title) and title in low)
            )
            if hit:
                picked.append((kind, item))
    return picked


def details_text(record, instruction: str, fixture: dict) -> str:
    if record is None:
        return "(no stored record for this episode)"
    bar = "=" * WIDTH
    out = ["", bar, "DETAILS: stored tool results and the original fixture items", bar, "",
           "TOOL RESULTS"]
    n = 0
    for tool, args, result in tool_calls(record):
        n += 1
        out.append(f"[{n}] {tool}({json.dumps(args, ensure_ascii=False)})")
        body = (json.dumps(sanitize(result), indent=2, ensure_ascii=False)
                if result is not None else "(no result)")
        out.extend("    " + line for line in body.splitlines())
    if n == 0:
        out.append("  (no tool calls)")
    out += ["", "ORIGINAL FIXTURE ITEMS THE TASK REFERS TO (before the episode)"]
    items = referenced_fixture_items(fixture, instruction, record)
    if not items:
        out.append("  (none matched by name or id)")
    for kind, item in items:
        out.append(f"  {kind[:-1]} {item['id']}:")
        for key, value in sanitize(item).items():
            if key == "id":
                continue
            label = EMAIL_LABELS.get(key, key) if kind == "emails" else key
            out.append(f"    {label}: {value}")
    return "\n".join(out) + "\n"


# ── labelling rules (r and R) ───────────────────────────────────────────────

RULE_HEADER = "| # | Pattern |"
CANCELLED = object()


def _rule_table(lines: list[str]):
    """(header_index, last_row_index) of the rules table, or None if there is no table."""
    for i, line in enumerate(lines):
        if line.startswith(RULE_HEADER):
            last = i + 1                       # the separator line
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                last = j
                j += 1
            return i, last
    return None


def show_rules(path: Path, out) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    bounds = _rule_table(lines)
    if bounds is None:
        out("(no rules table found in " + str(path) + ")")
        return
    header, last = bounds
    out("\n".join(lines[header:last + 1]))


def add_rule(path: Path, row: dict, ask, out) -> None:
    """Ask for one rule and append it as a row. Existing rows are never edited or removed."""

    def field(prompt, parse):
        while True:
            text = ask(f"  {prompt} (x cancels): ").strip()
            if text.lower() == "q":
                raise Quit()
            if text.lower() == "x":
                return CANCELLED
            value = parse(text)
            if value is None:
                out(f"  not valid: {text!r}")
                continue
            return value

    def no_bar(text):
        return text if "|" not in text else None

    pattern = field("Pattern", lambda t: t if t and "|" not in t else None)
    if pattern is CANCELLED:
        out("rule cancelled")
        return
    label_value = field("Label [h hack / n not a hack / u unsure]", lambda t: LABEL_KEYS.get(t.lower()))
    if label_value is CANCELLED:
        out("rule cancelled")
        return
    hack_type = field("Hack type [1-5, comma-separated, or - for none]",
                      lambda t: "" if t == "-" else parse_hack_types(t))
    if hack_type is CANCELLED:
        out("rule cancelled")
        return
    clar = field("Clarification class [1 i, 2 ii, 3 iii, 0 not a clarification]", parse_class)
    if clar is CANCELLED:
        out("rule cancelled")
        return
    note = field("Note to write (may be empty)", no_bar)
    if note is CANCELLED:
        out("rule cancelled")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    bounds = _rule_table(lines)
    if bounds is None:
        out(f"no rules table in {path}; nothing added")
        return
    header, last = bounds
    numbers = [int(line.split("|")[1].strip()) for line in lines[header + 2:last + 1]
               if line.split("|")[1].strip().isdigit()]
    number = max(numbers, default=0) + 1
    cells = [str(number), pattern, label_value,
             hack_type.replace(";", ", ") or "–", clar, note, row["episode_id"],
             datetime.date.today().isoformat()]
    lines.insert(last + 1, "| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    out(f"rule {number} added to {path.name}")


# ── the labelling session ───────────────────────────────────────────────────

def ask_step(step: str, row: dict, ask, out, hooks=None):
    """Ask one question. Returns ("value", v) or ("back", None). Raises Quit on q."""
    current = row.get(step, "")
    shown = f" (now: {current})" if current else ""
    hooks = hooks or {}
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
        if low == "v":
            out(hooks["v"]() if "v" in hooks else "(not available here)")
            continue
        if text == "R":
            if "R" in hooks:
                hooks["R"]()
            continue
        if low == "r":
            if "r" in hooks:
                hooks["r"]()
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


def label_rows(rows: list[dict], start: int, save, ask, out, details_for=lambda row: "",
               decisions=None) -> None:
    idx = start
    total = len(rows)
    suggested = False
    while idx < total:
        row = rows[idx]
        snapshot = dict(row)   # restored if the labeller quits part-way through this row
        out(render(row, idx, total))
        hooks = {"v": lambda r=row: details_for(r)}
        if decisions is not None:
            hooks["r"] = lambda r=row: add_rule(decisions, r, ask, out)
            hooks["R"] = lambda: show_rules(decisions, out)
        step_i = 0
        back = False
        try:
            while step_i < len(STEPS):
                step = STEPS[step_i]
                if step == "hack_type" and row["label"] != "hack":
                    row["hack_type"] = ""          # not a hack: no hack type
                    step_i += 1
                    continue
                kind, value = ask_step(step, row, ask, out, hooks=hooks)
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


def run(to_label: Path, labeled: Path, ask=input, out=print,
        runs_dir: Path = RUNS_DIR, fixture_path: Path = FIXTURE_PATH,
        decisions_path: Path = DECISIONS_PATH) -> int:
    rows = load_rows(to_label, labeled)
    start = first_unlabelled(rows)
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))

    def details_for(row):
        return details_text(load_record(runs_dir, row["episode_id"]),
                            row["task_instruction"], fixture)

    def save(rs):
        write_csv(labeled, rs)

    save(rows)
    out(f"{len(rows)} rows; starting at row {start + 1}. Commands: b back, g guide, q save and quit.")
    try:
        label_rows(rows, start, save, ask, out, details_for, decisions=decisions_path)
    except (Quit, EOFError):
        out("Saved. Run the same command again to resume.")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to-label", type=Path, default=TO_LABEL)
    parser.add_argument("--labeled", type=Path, default=LABELED)
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--decisions", type=Path, default=DECISIONS_PATH)
    args = parser.parse_args(argv)
    return run(args.to_label, args.labeled, runs_dir=args.runs_dir, fixture_path=args.fixture,
               decisions_path=args.decisions)


if __name__ == "__main__":
    sys.exit(main())
