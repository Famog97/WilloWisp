"""
adapters/driving/cli/__main__.py  (M4.2 — WilloWisp headless CLI)

A second front-end (alongside the Tk GUI) that drives the core through the
WilloWispCoreAPI facade — no GUI toolkit involved. Proves the hexagon: the same
author/run/report surfaces, headless.

Usage:
    python -m adapters.driving.cli catalog
    python -m adapters.driving.cli report <results.json> <out_dir> [--template management] [--title T]
    python -m adapters.driving.cli run <suite.json> [--title T]

`catalog` and `report` are fully headless (no hardware). `run` executes a real suite,
so it needs the live SCADA host (screen + protocol) unless you point it at fakes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _build_api(args):
    from adapters.driving.cli.composition import build_core_api
    cfg = Path(args.config) if getattr(args, "config", None) else None
    return build_core_api(config_path=cfg)


def cmd_catalog(args) -> int:
    api = _build_api(args)
    steps = sorted(api.list_step_types(), key=lambda t: (t["category"], t["key"]))
    print(f"Step types ({len(steps)}):")
    for t in steps:
        print(f"  {t['key']:<28} {t['category']:<14} {t['name']}")
    print("\nReport templates:")
    for t in api.list_report_templates():
        print(f"  {t['key']:<14} {t.get('name', '')}")
    return 0


def cmd_report(args) -> int:
    api = _build_api(args)
    raw = json.loads(Path(args.results).read_text(encoding="utf-8"))
    out = api.generate_report(args.template, raw, Path(args.out_dir), title=args.title)
    print(f"Report written: {out}")
    return 0


def cmd_run(args) -> int:
    from core.domain.scenario import Scenario
    api = _build_api(args)
    data = json.loads(Path(args.suite).read_text(encoding="utf-8"))
    raw_scenarios = data.get("scenarios", data) if isinstance(data, dict) else data
    scenarios = [Scenario.from_dict(d) for d in raw_scenarios]
    print(f"Running {len(scenarios)} scenario(s)…")
    api.start_suite(scenarios, suite_title=args.title)
    api._run.join()
    print(f"Run complete: state={api.get_run_state()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="willowisp", description="WilloWisp headless CLI")
    p.add_argument("--config", help="path to config.json (defaults to repo config)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="list step types and report templates")
    c.set_defaults(fn=cmd_catalog)

    r = sub.add_parser("report", help="generate a report from a results JSON (offline)")
    r.add_argument("results", help="path to a results/normalized JSON")
    r.add_argument("out_dir", help="output directory for the report")
    r.add_argument("--template", default="management", help="report template key")
    r.add_argument("--title", default="WilloWisp Report")
    r.set_defaults(fn=cmd_report)

    rn = sub.add_parser("run", help="run a suite (needs a live SCADA host)")
    rn.add_argument("suite", help="path to a suite JSON (list/dict of scenario dicts)")
    rn.add_argument("--title", default="ISCS Test Suite Run")
    rn.set_defaults(fn=cmd_run)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
