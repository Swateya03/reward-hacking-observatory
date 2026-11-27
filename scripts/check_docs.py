"""Check README.md against the code.

Fails (exit 1) if
  - the badge, the total in the test table, any per-file count in the test table, any "N tests" count in
    the README text, or any test count in the project tree differs from what `pytest --collect-only` collects;
  - a test file is missing from the test table or the project tree, or the test table's heading count is wrong;
  - a path in the project tree (section 07) does not exist on disk;
  - README or the architecture notes cite a source line number;
  - the Results block (between RESULTS:BEGIN and RESULTS:END) differs from scripts/results_readme.py output,
    byte for byte;
  - a number in the TL;DR does not match the result files (see scripts/results_readme.py TL_DR_PHRASES).

Server-dependent counts (the split with the server down) are not checked here: they need a full run.

Run from the repository root, before committing doc changes:
  python scripts/check_docs.py
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
sys.path.insert(0, str(REPO / "scripts"))

ARCH_HEADING = "## 🏗 07 — Architecture"
TESTING_HEADING = "## 🧪 08 — Testing"
NEXT_HEADING = "## 🔁 09"


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


def section(text: str, heading: str, next_heading: str) -> str:
    start = text.index(heading)
    end = text.index(next_heading, start)
    return text[start:end]


def details_body(text: str, summary_start: str) -> str:
    """The text inside the <details> block whose <summary> starts with summary_start."""
    s = text.index(summary_start)
    body_start = text.index("</summary>", s) + len("</summary>")
    return text[body_start:text.index("</details>", body_start)]


def tree_block(arch: str) -> list[str]:
    body = details_body(arch, "<summary><b>Full project tree</b>")
    fence = body.index("```")
    body_start = body.index("\n", fence) + 1
    body_end = body.index("```", body_start)
    return body[body_start:body_end].splitlines()


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
    import results_readme
    text = README.read_text(encoding="utf-8")
    total, per_file = collected_counts()
    problems: list[str] = []

    def expect(label: str, found, want):
        if str(found) != str(want):
            problems.append(f"{label}: README says {found}, collected {want}")

    # badge
    badge = re.search(r"Tests-(\d+)%20Passing", text)
    expect("badge", badge.group(1) if badge else "missing", total)

    # test table in section 08: heading count, total row and per-file rows
    testing = section(text, TESTING_HEADING, NEXT_HEADING)
    heading = re.search(r"<summary><b>All (\d+) test files</b></summary>", testing)
    expect("test table heading", heading.group(1) if heading else "missing", len(per_file))
    table_body = details_body(testing, "<summary><b>All ")
    total_row = re.search(r"\| \*\*Total\*\* \| \*\*(\d+)\*\* \|", table_body)
    expect("test table total", total_row.group(1) if total_row else "missing", total)
    table = dict((f, int(n)) for f, n in re.findall(r"^\| `(test_\w+\.py)` \| (\d+) \|", table_body, re.M))
    for name, n in sorted(per_file.items()):
        if name not in table:
            problems.append(f"test table: {name} has no row")
        else:
            expect(f"test table {name}", table[name], n)
    for name in table:
        if name not in per_file:
            problems.append(f"test table: {name} is not a collected test file")

    # "N tests" statements anywhere in the text
    for m in re.finditer(r"(?:suite of|\*\*)(\d+) tests", text):
        expect("README text count", m.group(1), total)

    # project tree in section 07
    arch = section(text, ARCH_HEADING, TESTING_HEADING)
    lines = tree_block(arch)
    tree_tests = dict((f, int(n)) for f, n in re.findall(r"(test_\w+\.py)\s+← (\d+) tests", "\n".join(lines)))
    for name, n in sorted(per_file.items()):
        if name not in tree_tests:
            problems.append(f"project tree: {name} has no entry")
        else:
            expect(f"project tree {name}", tree_tests[name], n)
    for path in tree_paths(lines):
        if not (REPO / path.rstrip("/")).exists():
            problems.append(f"project tree: {path} does not exist on disk")

    # source references are by function or class name, never by line number
    line_ref = re.compile(r"\.py`?:\d|lines? \d+\s*[-–]\s*\d+|\(line \d+\)")
    for doc in (README, REPO / "docs" / "ARCHITECTURE_NOTES.md"):
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if line_ref.search(line):
                problems.append(f"{doc.relative_to(REPO)}:{n}: line-number reference; name the function or class instead")

    # the Results block: byte-identical to the generator's output
    values = results_readme.values()
    generated = results_readme.block(values).strip("\n")
    if results_readme.current_between(text) != results_readme.expected_between(generated):
        problems.append("README Results block differs from scripts/results_readme.py output; "
                        "run: python scripts/results_readme.py")

    # TL;DR numbers, computed from the result files
    problems += results_readme.tldr_problems(text, values)

    if problems:
        print("README check FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"README check OK: {total} tests collected, {len(per_file)} test files, "
          f"{len(tree_paths(lines))} tree entries, all present on disk; Results block and TL;DR match the result files.")
    print("Not checked here: the server-down split; confirm it with a full run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
