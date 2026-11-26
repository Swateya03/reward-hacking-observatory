"""Check README.md against the code.

Fails (exit 1) if
  - the README badge, the section 09 total, any section 09 per-file count, any "N tests" count
    in the README text, or any test count in the section 08 tree differs from what
    `pytest --collect-only` collects;
  - a test file is missing from the section 09 table or the section 08 tree;
  - a path in the section 08 project tree does not exist on disk.

Server-dependent counts (the 338 / 51 / 7 split with the server down) are not checked here:
they need a full run. Run the suite to confirm them.

Run from the repository root, before committing doc changes:
  python scripts/check_docs.py
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"


def collected_counts() -> tuple[int, dict[str, int]]:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, check=False,
    ).stdout
    per_file: dict[str, int] = {}
    for line in out.splitlines():
        m = re.match(r"(tests/[\w.]+\.py)::", line)
        if m:
            per_file[Path(m.group(1)).name] = per_file.get(Path(m.group(1)).name, 0) + 1
    return sum(per_file.values()), per_file


def tree_block(text: str) -> list[str]:
    start = text.index("<summary><b>Click to expand full project tree</b></summary>")
    fence = text.index("```", start)
    body_start = text.index("\n", fence) + 1
    body_end = text.index("```", body_start)
    return text[body_start:body_end].splitlines()


TREE_ENTRY = re.compile(r"^([│ ]*)(├── |└── )(\S+)")


def tree_paths(lines: list[str]) -> list[str]:
    """Paths named in the tree, reconstructed from the indentation. Each level is 4 columns."""
    stack: dict[int, str] = {}
    paths = []
    for line in lines:
        m = TREE_ENTRY.match(line)
        if not m:
            continue
        depth = len(m.group(1)) // 4 + 1
        name = m.group(3)
        stack = {d: n for d, n in stack.items() if d < depth}
        stack[depth] = name.rstrip("/")
        paths.append("/".join(stack[d] for d in range(1, depth + 1)) + ("/" if name.endswith("/") else ""))
    return paths


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    text = README.read_text(encoding="utf-8")
    total, per_file = collected_counts()
    problems: list[str] = []

    def expect(label: str, found, want):
        if str(found) != str(want):
            problems.append(f"{label}: README says {found}, collected {want}")

    # badge
    badge = re.search(r"Tests-(\d+)%20Passing", text)
    expect("badge", badge.group(1) if badge else "missing", total)

    # section 09 total row
    total_row = re.search(r"\| \*\*Total\*\* \| \*\*(\d+)\*\* \|", text)
    expect("section 09 total", total_row.group(1) if total_row else "missing", total)

    # section 09 per-file table
    table = dict((f, int(n)) for f, n in re.findall(r"^\| `(test_\w+\.py)` \| (\d+) \|", text, re.M))
    for name, n in sorted(per_file.items()):
        if name not in table:
            problems.append(f"section 09 table: {name} has no row")
        else:
            expect(f"section 09 {name}", table[name], n)
    for name in table:
        if name not in per_file:
            problems.append(f"section 09 table: {name} is not a collected test file")

    # "N tests" statements in the text
    for m in re.finditer(r"(?:suite of|\*\*)(\d+) tests", text):
        expect("README text count", m.group(1), total)

    # section 08 tree
    lines = tree_block(text)
    tree_tests = dict((f, int(n)) for f, n in re.findall(r"(test_\w+\.py)\s+← (\d+) tests", "\n".join(lines)))
    for name, n in sorted(per_file.items()):
        if name not in tree_tests:
            problems.append(f"section 08 tree: {name} has no entry")
        else:
            expect(f"section 08 {name}", tree_tests[name], n)
    for path in tree_paths(lines):
        if not (REPO / path.rstrip("/")).exists():
            problems.append(f"section 08 tree: {path} does not exist on disk")

    # source references are by function or class name, never by line number
    line_ref = re.compile(r"\.py`?:\d|lines? \d+\s*[-–]\s*\d+|\(line \d+\)")
    for doc in (README, REPO / "docs" / "ARCHITECTURE_NOTES.md"):
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line_ref.search(line):
                problems.append(f"{doc.relative_to(REPO)}:{n}: line-number reference; name the function or class instead")

    if problems:
        print("README check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"README check OK: {total} tests collected, {len(per_file)} test files, "
          f"{len(tree_paths(lines))} tree entries, all present on disk.")
    print("Not checked here: the server-down split (338 / 51 / 7); confirm with a full run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
