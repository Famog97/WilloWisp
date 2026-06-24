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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

# ── data layer ────────────────────────────────────────────────────────────────

def _normalize(raw_results: List[dict]) -> List[dict]:
    """Build the normalized view via the existing, golden-tested normalizer.

    Validates the input shape first: a suite's raw results are a *list* of record
    dicts. A common mistake is feeding a dict — e.g. picking a generated
    ``Results.json`` (``{"title","summary","points"}``) instead of the run's
    ``suite_results.json`` — which otherwise fails deep inside the normalizer with
    a cryptic ``'str' object has no attribute 'get'``. Fail early with guidance."""
    if isinstance(raw_results, dict):
        hint = (" This looks like a generated report's Results.json - pick the "
                "run's suite_results.json instead.") if "points" in raw_results else ""
        raise ValueError(
            "Report input must be a list of raw result records (a suite_results.json), "
            f"but got a JSON object (dict).{hint}")
    if not isinstance(raw_results, list):
        raise ValueError(
            "Report input must be a list of raw result records (a suite_results.json), "
            f"but got {type(raw_results).__name__}.")
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


# ── data view (FR-30e) ──────────────────────────────────────────────────────────

@dataclass
class ResultView:
    """The immutable execution-data layer widgets bind to (FR-30e). Built once
    per render from the normalized results; each widget reads only what it
    declares in ``consumes``."""
    records: List[dict]
    summary: Dict[str, Any]
    meta: Dict[str, Any]


# ── composable, self-describing widgets (FR-30c / FR-30d) ────────────────────────
#
# Each widget declares the data it consumes and renders its own HTML fragment.
# A template (see TEMPLATES) is just an ordered list of widget keys — enable /
# disable / reorder is pure config, no engine change. A new widget = register it
# and reference its key from a template; existing templates + engine untouched.

class ReportWidget:
    """Base for a self-rendering report section.

    Subclasses set ``key`` and ``consumes`` (which ``ResultView`` fields it
    reads) and implement ``render(view) -> html fragment``.
    """
    key: str = ""
    consumes: tuple = ()

    def render(self, view: "ResultView") -> str:
        raise NotImplementedError


_WIDGETS: Dict[str, ReportWidget] = {}


def register_widget(widget: ReportWidget, *, override: bool = False) -> None:
    """Register a report widget by its ``key`` (FR-7 duplicate check)."""
    key = getattr(widget, "key", "")
    if not key:
        raise ValueError("ReportWidget.key must be a non-empty string")
    if key in _WIDGETS and not override:
        raise ValueError(f"Report widget already registered for key {key!r} "
                         f"(pass override=True to replace)")
    _WIDGETS[key] = widget


def get_widget(key: str) -> ReportWidget:
    """Look up a widget by key; raises ``LookupError`` with a clear message."""
    try:
        return _WIDGETS[key]
    except KeyError:
        known = ", ".join(sorted(_WIDGETS)) or "(none)"
        raise LookupError(f"No report widget registered for {key!r}. Known: {known}")


def list_widgets() -> List[Dict[str, Any]]:
    """All registered widgets + the data each declares it consumes."""
    return [{"key": _WIDGETS[k].key, "consumes": list(_WIDGETS[k].consumes)}
            for k in sorted(_WIDGETS)]


class HeaderWidget(ReportWidget):
    key = "header"
    consumes = ("meta",)

    def render(self, view: "ResultView") -> str:
        m = view.meta
        return (f'<h1>{_e(m.get("title", "Test Run"))} — '
                f'{_e(m.get("report_name", ""))}</h1>\n'
                f'<div class="sub">Generated {_e(m.get("generated"))} · '
                f'{_e(m.get("range", ""))}</div>')


class SummaryLineWidget(ReportWidget):
    key = "summary_line"
    consumes = ("summary",)

    def render(self, view: "ResultView") -> str:
        s = view.summary
        return (f'<div class="sub">{s["total"]} points · {s["passed"]} passed / '
                f'{s["failed"]} failed ({s["pass_rate"]:.1f}%)</div>')


class KpisWidget(ReportWidget):
    key = "kpis"
    consumes = ("summary",)

    def render(self, view: "ResultView") -> str:
        s = view.summary
        rate_cls = "pass" if s["pass_rate"] >= 100 else ("fail" if s["failed"] else "pass")
        return f"""
     <div class="kpis">
       <div class="kpi"><div class="v">{s['total']}</div><div class="l">Points</div></div>
       <div class="kpi"><div class="v pass">{s['passed']}</div><div class="l">Passed</div></div>
       <div class="kpi"><div class="v fail">{s['failed']}</div><div class="l">Failed</div></div>
       <div class="kpi"><div class="v {rate_cls}">{s['pass_rate']:.1f}%</div><div class="l">Pass rate</div></div>
     </div>"""


class FailuresByCategoryWidget(ReportWidget):
    key = "failures_by_category"
    consumes = ("summary",)

    def render(self, view: "ResultView") -> str:
        cats = "".join(f"<tr><td>{_e(c)}</td><td>{n}</td></tr>"
                       for c, n in view.summary["categories"].most_common()) or \
            "<tr><td colspan='2'>No failures 🎉</td></tr>"
        return ("<h3>Failures by category</h3>"
                f"<table><tr><th>Category</th><th>Count</th></tr>{cats}</table>")


class FailedPointsWidget(ReportWidget):
    key = "failed_points"
    consumes = ("records",)

    def render(self, view: "ResultView") -> str:
        fails = [r for r in view.records if r.get("overall") == "FAIL"]
        rows = "".join(
            f"<tr><td>{_e(r.get('id'))}</td><td>{_e(r.get('scenario_name'))}</td>"
            f"<td>{_e(r.get('failure_category'))}</td><td>{_e(r.get('failure_reason'))}</td></tr>"
            for r in fails) or "<tr><td colspan='4'>None</td></tr>"
        return ("<h3>Failed points</h3>"
                "<table><tr><th>Point</th><th>Scenario</th><th>Category</th>"
                f"<th>Reason</th></tr>{rows}</table>")


class AuditAttemptsWidget(ReportWidget):
    key = "audit_attempts"
    consumes = ("records", "summary")

    def render(self, view: "ResultView") -> str:
        s = view.summary
        rows = []
        for r in view.records:
            for a in (r.get("attempts") or [{"attempt": 0, "overall": r.get("overall"),
                                             "failure_reason": r.get("failure_reason")}]):
                st = a.get("overall", "")
                cls = "pass" if st == "PASS" else "fail"
                rows.append(
                    f"<tr><td>{_e(r.get('id'))}</td><td>{_e(r.get('scenario_name'))}</td>"
                    f"<td>{_e(r.get('loop_num'))}</td><td>{a.get('attempt')}</td>"
                    f"<td><span class='tag {cls}'>{_e(st)}</span></td>"
                    f"<td>{_e(a.get('failure_reason'))}</td></tr>")
        return (f'<div class="sub">{s["total"]} points · {s["passed"]} passed / '
                f'{s["failed"]} failed · {len(rows)} recorded attempts</div>'
                "<table><tr><th>Point</th><th>Scenario</th><th>Loop</th><th>Attempt</th>"
                f"<th>Status</th><th>Reason</th></tr>{''.join(rows)}</table>")


class StepTracesWidget(ReportWidget):
    key = "step_traces"
    consumes = ("records",)

    def render(self, view: "ResultView") -> str:
        blocks = []
        for r in view.records:
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
        return "".join(blocks)


# Register the built-in widgets. New widgets register the same way (FR-30d).
for _w in (HeaderWidget(), SummaryLineWidget(), KpisWidget(),
           FailuresByCategoryWidget(), FailedPointsWidget(),
           AuditAttemptsWidget(), StepTracesWidget()):
    register_widget(_w)


# ── template composition (FR-30c) ────────────────────────────────────────────────

def render_widgets(widget_keys: List[str], records: List[dict],
                   meta: Dict[str, Any]) -> str:
    """Compose an ordered list of widget keys into a full HTML page. A template
    is defined purely by its widget list (``TEMPLATES[...]['widgets']``), so
    enabling / disabling / reordering sections needs no engine change."""
    view = ResultView(records, _summary(records), meta)
    body = "\n".join(get_widget(k).render(view) for k in widget_keys)
    name = meta.get("report_name", "")
    title = f"{meta.get('title', 'Test Run')} — {name}" if name else meta.get("title", "Test Run")
    return _page(title, body)


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


def _pdf_text(s: Any) -> str:
    """fpdf2's core fonts are latin-1 only — make any text safe (drop emoji/unicode)."""
    return str(s if s is not None else "").encode("latin-1", "replace").decode("latin-1")


def render_pdf(records: List[dict], meta: Dict[str, Any], path) -> None:
    """Write a summary PDF (FR-30f). Requires the pure-Python 'fpdf2' package:
    `pip install fpdf2`. Unlike the HTML/JSON templates this writes the file
    directly (PDF is binary), so it's registered with a 'write' hook."""
    try:
        from fpdf import FPDF
    except Exception:
        raise RuntimeError("PDF export requires the 'fpdf2' package — install it with: "
                           "pip install fpdf2")
    s = _summary(records)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _pdf_text(f"{meta.get('title','Test Run')} - Summary"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _pdf_text(f"Generated {meta.get('generated')}   {meta.get('range','')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _pdf_text(
        f"Points: {s['total']}    Passed: {s['passed']}    Failed: {s['failed']}    "
        f"Pass rate: {s['pass_rate']:.1f}%"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Failures by category", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    if s["categories"]:
        for cat, n in s["categories"].most_common():
            pdf.cell(0, 6, _pdf_text(f"   {cat}: {n}"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "   None", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Failed points", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    fails = [r for r in records if r.get("overall") == "FAIL"]
    if fails:
        for r in fails:
            line = _pdf_text(
                f"{r.get('id')}  [{r.get('scenario_name')}]  "
                f"{r.get('failure_category')}: {r.get('failure_reason')}")
            # Reset x to the left margin first: multi_cell defaults new_x=RIGHT, so
            # without this the *next* full-width multi_cell would get ~0 width and
            # fpdf2 raises "Not enough horizontal space to render a single
            # character". new_x=LMARGIN keeps the cursor at the left edge; CHAR
            # wrap lets a long unbroken token (e.g. raw OCR text) break by char.
            pdf.set_x(pdf.l_margin)
            try:
                pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT",
                               wrapmode="CHAR")
            except Exception:
                # Never let one row kill the whole report — truncate and continue.
                pdf.set_x(pdf.l_margin)
                pdf.cell(0, 5, _pdf_text(line[:110]), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "   None", new_x="LMARGIN", new_y="NEXT")

    pdf.output(str(path))


def render_legacy(records: List[dict], meta: Dict[str, Any], path) -> None:
    """Regenerate the original full **Suite_Report.html** (the built-in "Legacy"
    view, FR-30a) from the same results, by delegating to `ReportManager` so the
    layout is identical to the run-time report. Writes into the suite folder.

    Times aren't stored in `suite_results.json`, so a re-render uses 0 (duration
    shows 0); the picker prefers an already-present Suite_Report.html over a
    re-render, so the original run's report is what you normally see."""
    from iscs_reports import ReportManager
    out_dir = Path(path).parent
    evidence = ReportManager._scan_evidence_files(out_dir)
    # _write_html_report expects datetime objects (it subtracts them and calls
    # strftime). suite_results.json doesn't store run times, so a re-render uses
    # "now" for both → duration shows 0:00:00.
    now = datetime.datetime.now()
    start = meta.get("start_ts") or now
    end = meta.get("end_ts") or now
    ReportManager._write_html_report(records, out_dir, start, end,
                                     meta.get("title", "Test Run"), evidence)


# ── registry (FR-30, FR-30b) ──────────────────────────────────────────────────

# HTML templates are pure composition config — an ordered ``widgets`` list (FR-30c).
# Adding/reordering a section, or adding a whole template, needs no engine change.
# json/pdf are format-specific renderers (FR-30f) and keep their own hooks.
# `order` controls the picker list (HTML reports first, then PDF, then JSON).
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "legacy":      {"name": "Legacy Report (Original)", "audience": "full", "order": 10,
                    "filename": "Suite_Report.html", "write": render_legacy},
    "audit":       {"name": "Audit Record", "audience": "audit", "order": 20,
                    "filename": "Audit_Report.html",
                    "widgets": ["header", "audit_attempts"]},
    "engineering": {"name": "Engineering Report", "audience": "engineering", "order": 30,
                    "filename": "Engineering_Report.html",
                    "widgets": ["header", "summary_line", "step_traces"]},
    "management":  {"name": "Management Summary", "audience": "management", "order": 40,
                    "filename": "Management_Summary.html",
                    "widgets": ["header", "kpis", "failures_by_category", "failed_points"]},
    "pdf":         {"name": "Summary PDF", "audience": "print", "order": 50,
                    "filename": "Summary_Report.pdf", "write": render_pdf},
    "json":        {"name": "Results JSON", "audience": "data", "order": 60,
                    "filename": "Results.json", "render": render_json},
}


def list_templates() -> List[Dict[str, str]]:
    """Templates in display order (HTML reports first, then PDF, then JSON)."""
    items = sorted(TEMPLATES.items(), key=lambda kv: (kv[1].get("order", 999), kv[0]))
    return [{"key": k, "name": v["name"], "audience": v["audience"]} for k, v in items]


def render_html(template_key: str, raw_results: List[dict],
                title: str = "Test Run", start=None, end=None) -> str:
    """Render the chosen template to an HTML string (no file written)."""
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown report template {template_key!r}. "
                       f"Available: {sorted(TEMPLATES)}")
    entry = TEMPLATES[template_key]
    if "widgets" not in entry and "render" not in entry:
        raise ValueError(f"Template {template_key!r} is a binary format — "
                         f"use generate_template_report() to write it.")
    records = _normalize(raw_results)
    meta = {
        "title": title,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "range": f"{start} → {end}" if (start or end) else "",
    }
    if "widgets" in entry:
        meta["report_name"] = entry["name"]
        return render_widgets(entry["widgets"], records, meta)
    return entry["render"](records, meta)


def generate_template_report(template_key: str, raw_results: List[dict], output_dir,
                             title: str = "Test Run", start=None, end=None) -> Path:
    """Render and write the chosen template into output_dir. Returns the path.
    Handles both text templates ('render' → str) and binary ones ('write' → file)."""
    if template_key not in TEMPLATES:
        raise KeyError(f"Unknown report template {template_key!r}. Available: {sorted(TEMPLATES)}")
    entry = TEMPLATES[template_key]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / entry["filename"]
    if "write" in entry:
        records = _normalize(raw_results)
        meta = {
            "title": title,
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "range": f"{start} → {end}" if (start or end) else "",
        }
        entry["write"](records, meta, path)
    else:
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
