"""findings.py never writes results/findings.json, and never writes under results/legacy/.

The output path is a required --out argument. These tests check the guard and
the CLI. No API calls, no workspace server.
"""

import json
from unittest.mock import patch

import pytest

from analysis import findings
from analysis.findings import REPO_ROOT, FindingsExtractor, check_output_path


def test_refuses_results_findings_json_relative_and_absolute():
    with pytest.raises(ValueError, match="results/findings.json"):
        check_output_path("results/findings.json")
    with pytest.raises(ValueError, match="results/findings.json"):
        check_output_path(str(REPO_ROOT / "results" / "findings.json"))


def test_refuses_anything_under_results_legacy():
    with pytest.raises(ValueError, match="results/legacy"):
        check_output_path(str(REPO_ROOT / "results" / "legacy" / "findings_partial_run.json"))
    with pytest.raises(ValueError, match="results/legacy"):
        check_output_path(str(REPO_ROOT / "results" / "legacy" / "new" / "out.json"))
    with pytest.raises(ValueError, match="results/legacy"):
        check_output_path(str(REPO_ROOT / "results" / "legacy"))


def test_allows_other_paths(tmp_path):
    assert check_output_path(tmp_path / "out.json") == (tmp_path / "out.json").resolve()
    assert check_output_path(str(REPO_ROOT / "results" / "demo" / "x.json"))


def test_main_requires_out_argument(capsys):
    with pytest.raises(SystemExit) as exc:
        findings.main([])
    assert exc.value.code == 2
    assert "--out" in capsys.readouterr().err


def test_main_refuses_results_findings_json_without_writing(capsys):
    with patch("analysis.findings.json.dump") as dump:
        with pytest.raises(SystemExit) as exc:
            findings.main(["--out", "results/findings.json"])
    assert exc.value.code == 2
    dump.assert_not_called()
    assert "refusing" in capsys.readouterr().err


def test_main_refuses_legacy_without_writing():
    with patch("analysis.findings.json.dump") as dump:
        with pytest.raises(SystemExit):
            findings.main(["--out", "results/legacy/findings_partial_run.json"])
    dump.assert_not_called()


def test_save_findings_has_no_default_and_refuses_protected_path():
    extractor = FindingsExtractor()
    with patch("analysis.findings.json.dump") as dump:
        with pytest.raises(TypeError):
            extractor.save_findings()  # path is required
        with pytest.raises(ValueError):
            extractor.save_findings("results/findings.json")
    dump.assert_not_called()


def test_save_findings_writes_to_allowed_path(tmp_path):
    extractor = FindingsExtractor()
    extractor.results = []
    out = tmp_path / "findings.json"
    extractor.save_findings(out)
    assert json.loads(out.read_text())  # a findings dict was written
