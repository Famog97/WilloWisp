"""
Pluggable report templates (FR-30) — render audience-specific reports from the
SAME normalized execution results that drive the legacy Suite_Report.html.

Design (FR-30e three layers):
  - data        : ReportManager.normalize_results(raw)  — the stable contract
  - templates   : audience-specific renderers registered in TEMPLATES
  - (renderers) : currently HTML; PDF/JSON can be added the same way

This module is standalone (no Tkinter) and additive: it does NOT change the
existing report. It renders from a results list, so any saved run can be
re-rendered under any template offline, no re-execution (FR-30).

CLI:
    python iscs_report_templates.py <suite_results.json> --template management
"""
from __future__ import annotations

import datetime
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List

# ── data layer ────────────────────────────────────────────────────────────────

def _normalize(raw_results: List[dict]) -> List[dict]:
    """Build the normalized view via the existing, golden-tested normalizer."""
    from iscs_reports import ReportManager      # lazy import avoids any import cycle
    return ReportManager.normalize_results(raw_results)


def _summary(records: List[dict]) -> Dict[str, Any]:
    total  = len(records)
    passed = sum(1 for r in records if r.get("overall") == "PASS")
    failed = total - passed
    rate   = (passed / total * 100.0) if total else 0.0
    categories = Counter(r.get("failure_category", "Other")
                         for r in records if r.get("overall") == "FAIL")
    return {"total": total, "passed": passed, "failed": failed,
            "pass_rate": rate, "categories": categories}


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_e(title)}</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#8a8f98;font-size:12px;margin-bottom:18px}}
 .kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
 .kpi{{background:#181b22;border:1px solid #262b34;border-radius:10px;padding:14px 18px;min-width:120px}}
 .kpi .v{{font-size:26px;font-weight:700}} .kpi .l{{color:#8a8f98;font-size:11px;text-transform:uppercase}}
 .pass{{color:#3ad29f}} .fail{{color:#ff6b6b}}
 table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #20242c}}
 th{{color:#8a8f98;font-weight:600;text-transform:uppercase;font-size:11px}}
 tr:hover td{{background:#15181e}} .tag{{padding:2px 8px;border-radius:6px;font-size:11px}}
 .tag.pass{{background:#10271f;color:#3ad29f}} .tag.fail{{background:#2a1414;color:#ff6b6b}}
</style></head><body>{body}</body></html>"""


# ── templates ─────────────────────────────────────────────────────────────────

def render_management(records: List[dict], meta: Dict[str, Any]) -> str:
    """Management summary: KPIs + failures-by-category + top failures. No step detail."""
    s = _summary(records)
    rate_cls = "pass" if s["pass_rate"] >= 100 else ("fail" if s["failed"] else "pass")
    kpis = f"""
     <div class="kpis">
       <div class="kpi"><div class="v">{s['total']}</div><div class="l">Points</div></div>
       <div class="kpi"><div class="v pass">{s['passed']}</div><div class="l">Passed</div></div>
       <div class="kpi"><div class="v fail">{s['failed']}</div><div class="l">Failed</div></div>
       <div class="kpi"><div class="v {rate_cls}">{s['pass_rate']:.1f}%</div><div class="l">Pass rate</div></div>
     </div>"""

    cats = "".join(f"<tr><td>{_e(c)}</td><td>{n}</td></tr>"
                   for c, n in s["categories"].most_common()) or \
        "<tr><td colspan='2'>No failures 🎉</td></tr>"

    fails = [r for r in records if r.get("overall") == "FAIL"]
    rows = "".join(
        f"<tr><td>{_e(r.get('id'))}</td><td>{_e(r.get('scenario_name'))}</td>"
        f"<td>{_e(r.get('failure_category'))}</td><td>{_e(r.get('failure_reason'))}</td></tr>"
        for r in fails) or "<tr><td colspan='4'>None</td></tr>"

    body = f"""
     <h1>{_e(meta.get('title','Test Run'))} — Management Summary</h1>
     <div class="sub">Generated {_e(meta.get('generated'))} · {_e(meta.get('range',''))}</div>
     {kpis}
     <h3>Failures by category</h3>
     <table><tr><th>Category</th><th>Count</th></tr>{cats}</table>
     <h3>Failed points</h3>
     <table><tr><th>Point</th><th>Scenario</th><th>Category</th><th>Reason</th></tr>{rows}</table>"""
    return _page(f"{meta.get('title','Test Run')} — Management Summary", body)


def render_audit(records: List[dict], meta: Dict[str, Any]) -> str:
    """Audit: immutable, full per-attempt record with timestamps for traceability."""
    s = _summary(records)
    rows = []
    for r in records:
        for a in (r.get("attempts") or [{"attempt": 0, "overall": r.get("overall"),
                                          "failure_reason": r.get("failure_reason")}]):
            st = a.get("overall", "")
            cls = "pass" if st == "PASS" else "fail"
            rows.append(
                f"<tr><td>{_e(r.get('id'))}</td><td>{_e(r.get('scenario_name'))}</td>"
                f"<td>{_e(r.get('loop_num'))}</td><td>{a.get('attempt')}</td>"
                f"<td><span class='tag {cls}'>{_e(st)}</span></td>"
                f"<td>{_e(a.get('failure_reason'))}</td></tr>")
    body = f"""
     <h1>{_e(meta.get('title','Test Run'))} — Audit Record</h1>
     <div class="sub">Generated {_e(meta.get('generated'))} · {_e(meta.get('range',''))} ·
       {s['total']} points · {s['passed']} passed / {s['failed']} failed ·
       {len(rows)} recorded attempts</div>
     <table><tr><th>Point</th><th>Scenario</th><th>Loop</th><th>Attempt</th>
       <th>Status</th><th>Reason</th></tr>{''.join(rows)}</table>"""
    return _page(f"{meta.get('title','Test Run')} — Audit Record", body)


def render_engineering(records: List[dict], meta: Dict[str, Any]) -> str:
    """Engineering view: every point with its full step-by-step trace + reason."""
    s = _summary(records)
    blocks = []
    for r in records:
        oc = r.get("overall", "")
        cls = "pass" if oc == "PASS" else "fail"
        step_rows = "".join(
            f"<tr><td>{_e(st.get('name'))}</td>"
            f"<td><span class='tag {'pass' if st.get('status')=='PASS' else 'fail'}'>"
            f"{_e(st.get('status'))}</span></td>"
            f"<td>{_e(st.get('message'))}</td></tr>"
            for st in (r.get("steps") or [])) or "<tr><td colspan='3'>No steps</td></tr>"
        reason = ""
        if oc == "FAIL":
            reason = (f"<div class='sub'>↳ {_e(r.get('failure_category'))}: "
                      f"{_e(r.get('failure_reason'))}</div>")
        blocks.append(f"""
         <h3><span class="tag {cls}">{_e(oc)}</span> {_e(r.get('id'))}
             <span class="sub">— {_e(r.get('scenario_name'))} · loop {_e(r.get('loop_num'))}</span></h3>
         {reason}
         <table><tr><th>Step</th><th>Status</th><th>Detail</th></tr>{step_rows}</table>""")
    body = f"""
     <h1>{_e(meta.get('title','Test Run'))} — Engineering Report</h1>
     <div class="sub">Generated {_e(meta.get('generated'))} · {_e(meta.get('range',''))} ·
       {s['total']} points · {s['passed']} passed / {s['failed']} failed
       ({s['pass_rate']:.1f}%)</div>
     {''.join(blocks)}"""
    return _page(f"{meta.get('title','Test Run')} — Engineering Report", body)


def render_json(records: List[dict], meta: Dict[str, Any]) -> str:
    """Data export (FR-30f): the normalized results + summary as JSON. Different
    format, same underlying data — for CI, dashboards, or other tooling."""
    s = _summary(records)
    payload = {
        "title": meta.get("title", "Test Run"),
        "generated": meta.get("generated"),
        "summary": {"total": s["total"], "passed": s["passed"], "failed": s["failed"],
                    "pass_rate": round(s["pass_rate"], 2),
                    "failures_by_category": dict(s["categories"])},
        "points": records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


# ── registry (FR-30, FR-30b) ──────────────────────────────────────────────────

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "management":  {"name": "Management Summary", "audience": "management",
                    "filename": "Management_Summary.html", "render": render_management},
    "engineering": {"name": "Engineering Report", "audience": "engineering",
                    "filename": "Engineering_Report.html", "render": render_engineering},
    "audit":       {"name": "Audit Record", "audience": "audit",
                    "filename": "Audit_Report.html", "render": render_audit},
    "json":        {"name": "Results JSON", "audience": "data",
                    "filename": "Results.json", "render": render_json},
}


def list_templates() -> List[Dict[str, str]]:
    return [{"key": k, "name": v["name"], "audience": v["audience"]}
            for k, v in sorted(TEMPLATES.items())]


def render_html(template_key: str, raw_results: List[dict],
                title: str = "Test Run", start=None, end=None) -> str:
    """Render the chosen template to an HTML string (no file written)."""
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown report template {template_key!r}. "
                       f"Available: {sorted(TEMPLATES)}")
    records = _normalize(raw_results)
    meta = {
        "title": title,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "range": f"{start} → {end}" if (start or end) else "",
    }
    return TEMPLATES[template_key]["render"](records, meta)


def generate_template_report(template_key: str, raw_results: List[dict], output_dir,
                             title: str = "Test Run", start=None, end=None) -> Path:
    """Render and write the chosen template into output_dir. Returns the path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / TEMPLATES[template_key]["filename"]
    path.write_text(render_html(template_key, raw_results, title, start, end), encoding="utf-8")
    return path


# ── CLI — render any saved results JSON under any template, offline ───────────

def _main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Render a WilloWisp report template from saved results.")
    p.add_argument("results_json", help="Path to a saved suite_results.json")
    p.add_argument("--template", default="management", choices=sorted(TEMPLATES))
    p.add_argument("--title", default="Test Run")
    p.add_argument("--out", default=None, help="Output dir (default: alongside the JSON)")
    args = p.parse_args(argv)

    raw = json.loads(Path(args.results_json).read_text(encoding="utf-8"))
    out_dir = args.out or Path(args.results_json).parent
    path = generate_template_report(args.template, raw, out_dir, title=args.title)
    print(f"Wrote {path}")


if __name__ == "__main__":
    _main()
