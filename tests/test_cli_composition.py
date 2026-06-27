"""
M4.1 — CLI composition root + run_service wiring.

Builds the WilloWispCoreAPI through the CLI composition root with fully-faked driven
ports (no hardware, no OS automation) and checks that the catalogue/config surfaces
work and that the run_service seam actually drives SuiteRunner via start_suite().
"""
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.driving.cli.composition import build_core_api
from core.ports.input_control import InputControlPort

ROOT = Path(__file__).resolve().parent.parent


class _FakeInput(InputControlPort):
    def click(self, x, y): pass
    def position(self): return (0, 0)
    def right_click(self, x, y): pass
    def hotkey(self, *k): pass
    def type_text(self, t, interval=0.0): pass


class _FakeProtocols:
    def get_protocol(self, name): return None
    def stop_all(self): pass


@pytest.fixture
def api(tmp_path):
    return build_core_api(
        config_path=tmp_path / "config.json", base_dir=tmp_path,
        protocols=_FakeProtocols(), input_control=_FakeInput(), assets=None,
    )


def test_facade_catalogue_and_config(api):
    keys = {t["key"] for t in api.list_step_types()}
    assert {"trigger_alarm", "verify_alarm_panel", "delay"} <= keys
    assert "grid_spacing" in api.get_config()
    assert {"management", "json"} <= {t["key"] for t in api.list_report_templates()}


def test_run_service_wired_drives_a_suite(api):
    # An empty suite has no cards to run, so it completes immediately — but it still
    # proves start_suite() -> SuiteRunService -> SuiteRunner runs and returns to idle.
    api.start_suite([])
    api._run.join(timeout=15)
    assert api.get_run_state() == "idle"


def test_composition_builds_without_tkinter():
    code = (
        "import sys\n"
        "from adapters.driving.cli.composition import build_core_api\n"
        "from core.ports.input_control import InputControlPort\n"
        "class I(InputControlPort):\n"
        "    def click(self,x,y): pass\n"
        "    def position(self): return (0,0)\n"
        "    def right_click(self,x,y): pass\n"
        "    def hotkey(self,*k): pass\n"
        "    def type_text(self,t,interval=0.0): pass\n"
        "class P:\n"
        "    def get_protocol(self,n): return None\n"
        "    def stop_all(self): pass\n"
        "import tempfile, pathlib\n"
        "d = pathlib.Path(tempfile.mkdtemp())\n"
        "api = build_core_api(config_path=d/'c.json', base_dir=d, protocols=P(), input_control=I(), assets=None)\n"
        "assert api.list_step_types()\n"
        "leaked = [m for m in sys.modules if m=='tkinter' or m.startswith('tkinter.')]\n"
        "assert not leaked, leaked\n"
        "print('HEADLESS_OK')\n"
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert "HEADLESS_OK" in out.stdout, f"stdout={out.stdout!r}\nstderr={out.stderr!r}"


def test_b9_suite_run_loads_zero_gui_libs():
    # B9: a suite run goes through the facade with NO GUI toolkit ever imported.
    code = (
        "import sys, tempfile, pathlib\n"
        "from adapters.driving.cli.composition import build_core_api\n"
        "from core.ports.input_control import InputControlPort\n"
        "class I(InputControlPort):\n"
        "    def click(self,x,y): pass\n"
        "    def position(self): return (0,0)\n"
        "    def right_click(self,x,y): pass\n"
        "    def hotkey(self,*k): pass\n"
        "    def type_text(self,t,interval=0.0): pass\n"
        "class P:\n"
        "    def get_protocol(self,n): return None\n"
        "    def stop_all(self): pass\n"
        "d = pathlib.Path(tempfile.mkdtemp())\n"
        "api = build_core_api(config_path=d/'c.json', base_dir=d, protocols=P(), input_control=I(), assets=None)\n"
        "api.start_suite([])\n"
        "api._run.join(timeout=15)\n"
        "assert api.get_run_state() == 'idle'\n"
        "leaked = [m for m in sys.modules if m=='tkinter' or m.startswith('tkinter.')]\n"
        "assert not leaked, leaked\n"
        "print('B9_OK')\n"
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert "B9_OK" in out.stdout, f"stdout={out.stdout!r}\nstderr={out.stderr!r}"
