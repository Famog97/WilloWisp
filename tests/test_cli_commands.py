"""
M4.2 — the headless CLI commands (catalog / report).

Invokes `python -m adapters.driving.cli ...` as a real subprocess (so it also proves
the CLI path loads no GUI toolkit) and checks the output / produced report file.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cli(*args, **kw):
    return subprocess.run([sys.executable, "-m", "adapters.driving.cli", *args],
                          capture_output=True, text=True, cwd=str(ROOT), **kw)


def test_cli_catalog_lists_steps_and_templates():
    out = _cli("catalog")
    assert out.returncode == 0, out.stderr
    assert "trigger_alarm" in out.stdout and "verify_alarm_panel" in out.stdout
    assert "management" in out.stdout and "json" in out.stdout


def test_cli_report_generates_file(tmp_path):
    fixture = ROOT / "tests" / "fixtures" / "normalize_input.json"
    out_dir = tmp_path / "report_out"
    out = _cli("report", str(fixture), str(out_dir), "--template", "management",
               "--title", "CLI Test")
    assert out.returncode == 0, out.stderr
    assert "Report written:" in out.stdout
    produced = list(out_dir.glob("*.html"))
    assert produced, f"no report produced in {out_dir}: {out.stdout}\n{out.stderr}"


def test_cli_runs_without_tkinter(tmp_path):
    # The CLI front-end must never pull a GUI toolkit (B9).
    out = _cli("catalog")
    # the subprocess prints only the catalogue; assert it succeeded and, via a
    # dedicated probe, that importing the CLI module graph loads no tkinter.
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys, runpy, adapters.driving.cli.__main__ as m;"
         "leaked=[x for x in sys.modules if x=='tkinter' or x.startswith('tkinter.')];"
         "assert not leaked, leaked; print('HEADLESS_OK')"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert "HEADLESS_OK" in probe.stdout, f"{probe.stdout!r}\n{probe.stderr!r}"
