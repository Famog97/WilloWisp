"""
M3.4 payoff guard: the run engine (core/services/engine.py) must be importable
headlessly — importing it pulls NO GUI toolkit. This is what lets a CLI / server
(M4) drive the full author->run->report cycle through the facade without a screen.

Runs in a clean subprocess so a GUI toolkit imported by an earlier test in this
process can't mask a regression.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_engine_module_imports_without_tkinter():
    code = (
        "import sys\n"
        "import core.services.engine as e\n"
        "assert e.ProcedureRunner is not None\n"
        "assert e.register_legacy_capabilities is not None\n"
        "cov, missing = e.registry_step_coverage()\n"
        "assert missing == [], missing\n"
        "leaked = [m for m in sys.modules if m == 'tkinter' or m.startswith('tkinter.')]\n"
        "assert not leaked, leaked\n"
        "print('HEADLESS_OK')\n"
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert "HEADLESS_OK" in out.stdout, f"stdout={out.stdout!r}\nstderr={out.stderr!r}"
