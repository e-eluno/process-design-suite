"""HTML design report (self-contained; prints cleanly to PDF from any browser)."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from jinja2 import Environment, BaseLoader

from .. import APP_NAME, __version__
from .criteria import default_library

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ project.name }} - Design Report</title>
<style>
:root{--ink:#1d2329;--mute:#5d6873;--line:#d9dee3;--bg:#fff;--soft:#f4f6f8;--accent:#1f5f8b;
--pass:#2e7d4f;--warn:#a86b00;--fail:#b3261e;--info:#5d6873}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 "Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:32px 24px 64px}
header{border-bottom:3px solid var(--accent);padding-bottom:14px;margin-bottom:22px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 10px;color:var(--accent)}
h3{font-size:15px;margin:22px 0 8px;display:flex;gap:10px;align-items:center}
.meta{color:var(--mute);font-size:13px}.meta span{margin-right:18px}
table{border-collapse:collapse;width:100%;margin:6px 0 10px;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff;letter-spacing:.03em}
.PASS{background:var(--pass)}.WARN{background:var(--warn)}.FAIL{background:var(--fail)}.INFO{background:var(--info)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
.kpi{background:var(--soft);border-radius:6px;padding:10px 12px}.kpi b{display:block;font-size:20px}
.kpi small{color:var(--mute)}
.note{color:var(--mute);font-size:12.5px;margin:2px 0}.unv{color:var(--warn);font-size:11px}
.disclaimer{margin-top:40px;padding:12px 14px;border:1px solid var(--line);border-radius:6px;font-size:12px;color:var(--mute)}
.unit{break-inside:avoid-page}
@media (max-width:700px){.cols{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}}
@media print{.wrap{max-width:none;padding:0}h2{break-after:avoid}.unit{break-inside:avoid}}
</style></head><body><div class="wrap">
<header>
<h1>{{ project.name }}</h1>
<div class="meta">
{% if project.client %}<span>Client: {{ project.client }}</span>{% endif %}
{% if project.location %}<span>Location: {{ project.location }}</span>{% endif %}
{% if project.engineer %}<span>Prepared by: {{ project.engineer }}</span>{% endif %}
<span>{{ date }}</span><span>{{ app }} v{{ version }}</span></div>
</header>

<h2>Design summary</h2>
<div class="kpis">
<div class="kpi"><small>Design average flow</small><b>{{ "%.2f"|format(infl.Q_avg) }} MGD</b><small>peak hour {{ "%.2f"|format(infl.Q_peak) }} MGD</small></div>
<div class="kpi"><small>Overall status</small><b><span class="badge {{ status }}">{{ status }}</span></b><small>{{ counts.PASS }} pass · {{ counts.WARN }} warn · {{ counts.FAIL }} fail</small></div>
<div class="kpi"><small>Process</small><b style="font-size:15px">{{ process }}</b><small>{{ "%.1f"|format(srt) }} d aerobic SRT</small></div>
<div class="kpi"><small>Recycle balance</small><b style="font-size:15px">{{ "converged" if converged else "NOT converged" }}</b><small>{{ iterations }} iterations</small></div>
</div>
{% for w in warnings %}<p class="note">&#9888; {{ w }}</p>{% endfor %}

<h3>Effluent compliance</h3>
<table><tr><th>Parameter</th><th class="n">Predicted (mg/L)</th><th class="n">Permit limit (mg/L)</th><th>Status</th><th>Note</th></tr>
{% for c in compliance %}<tr><td>{{ c.param }}</td><td class="n">{{ "%.2f"|format(c.predicted) }}</td>
<td class="n">{{ "%.1f"|format(c.limit) if c.limit else "-" }}</td><td><span class="badge {{ c.status }}">{{ c.status }}</span></td><td>{{ c.note }}</td></tr>{% endfor %}
</table>

<h3>Liquid-stream mass balance (average conditions)</h3>
<table><tr><th>Stream</th><th class="n">Q (MGD)</th><th class="n">BOD5</th><th class="n">TSS</th><th class="n">TKN</th><th class="n">NH3-N</th><th class="n">NO3-N</th><th class="n">TP</th></tr>
{% for s in streams %}<tr><td>{{ s.name }}</td><td class="n">{{ "%.3f"|format(s.Q) }}</td>
{% for k in ["BOD","TSS","TKN","NH3N","NO3N","TP"] %}<td class="n">{{ "%.1f"|format(s[k]) if s[k] is not none else "-" }}</td>{% endfor %}</tr>{% endfor %}
</table><p class="note">Concentrations in mg/L.</p>

<h3>Solids mass balance</h3>
<table><tr><th>Stream</th><th class="n">Dry solids (lb/d)</th><th class="n">Volatile (lb/d)</th><th class="n">Solids (%)</th><th class="n">Volume (gpd)</th></tr>
{% for s in sludge %}<tr><td>{{ s.name }}</td><td class="n">{{ "{:,.0f}".format(s.TS) }}</td><td class="n">{{ "{:,.0f}".format(s.VS) }}</td>
<td class="n">{{ "%.2f"|format(s.pct) }}</td><td class="n">{{ "{:,.0f}".format(s.gpd) }}</td></tr>{% endfor %}
</table>

{% if figures %}<h2>Figures</h2>
{% for title, uri in figures %}<figure style="margin:14px 0;break-inside:avoid">
<img src="{{ uri }}" alt="{{ title }}" style="max-width:100%;height:auto;border:1px solid var(--line);border-radius:6px">
<figcaption class="note">Figure {{ loop.index }}. {{ title }}</figcaption></figure>{% endfor %}{% endif %}

{% if costs %}<h3>Cost summary (planning level - placeholder unit prices)</h3>
<table><tr><th>Item</th><th class="n">Amount</th></tr>
<tr><td>Total capital cost</td><td class="n">${{ "{:,.0f}".format(costs.capital) }}</td></tr>
<tr><td>Annual O&amp;M</td><td class="n">${{ "{:,.0f}".format(costs.om) }} /yr</td></tr>
<tr><td>Present worth</td><td class="n">${{ "{:,.0f}".format(costs.npv) }}</td></tr></table>{% endif %}

<h2>Unit process design</h2>
{% for u in units %}<div class="unit">
<h3>{{ u.name }} <span class="badge {{ u.status }}">{{ u.status }}</span></h3>
<div class="cols"><div>
<table><tr><th colspan="3">Design basis</th></tr>
{% for p in u.inputs %}<tr><td>{{ p.label }}</td><td class="n">{{ p.value }}</td><td>{{ p.unit }}</td></tr>{% endfor %}</table>
</div><div>
<table><tr><th colspan="3">Results</th></tr>
{% for p in u.outputs %}<tr><td>{{ p.label }}</td><td class="n">{{ p.value }}</td><td>{{ p.unit }}</td></tr>{% endfor %}</table>
</div></div>
{% if u.checks %}<table><tr><th>Criterion</th><th class="n">Value</th><th>Required / typical</th><th>Status</th><th>Basis</th></tr>
{% for c in u.checks %}<tr><td>{{ c.label }}{% if c.message %}<br><span class="note">{{ c.message }}</span>{% endif %}</td>
<td class="n">{{ fmt(c.value) }} {{ c.unit }}</td><td>{{ c.range }}</td><td><span class="badge {{ c.status }}">{{ c.status }}</span></td>
<td>{{ c.source }}{% if not c.verified %} <span class="unv">(unverified)</span>{% endif %}</td></tr>{% endfor %}</table>{% endif %}
{% for n in u.notes %}<p class="note">&bull; {{ n }}</p>{% endfor %}
</div>{% endfor %}

<h2>References for design criteria</h2>
<table><tr><th>Key</th><th>Reference</th></tr>
{% for k, v in sources.items() %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}</table>
<p class="note">Criteria marked <span class="unv">(unverified)</span> are textbook or standard values carried in the default library
that have not yet been confirmed against the cited document. Confirm them, or load a firm/state criteria file, before issuing a design.</p>

<div class="disclaimer">This report is a preliminary process design produced by software. Results depend on the input
assumptions and default coefficients listed. Final design, hydraulic profile, equipment selection and regulatory submittals
(e.g. SC R.61-67 engineering report and construction permit) must be prepared and sealed by a licensed Professional Engineer. Cost figures use placeholder unit prices and are
planning-level only. The dynamic simulation uses uncalibrated literature ASM1 parameters.</div>
</div></body></html>"""


def _fmt(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    ax = abs(x)
    if ax >= 1000:
        return f"{x:,.0f}"
    if ax >= 10:
        return f"{x:,.1f}"
    return f"{x:.3g}"


def render_wwtp_report(result, lib=None) -> str:
    lib = lib or default_library()
    env = Environment(loader=BaseLoader(), autoescape=True)
    tpl = env.from_string(TEMPLATE)
    as_unit = next((u for u in result.units if u.name.startswith("Activated Sludge")), None)
    from .charts import plant_charts, data_uri
    try:
        figures = [(k, data_uri(v)) for k, v in plant_charts(result).items()]
    except Exception:  # noqa: BLE001 - charts are optional
        figures = []
    cost_u = next((u for u in result.units if u.name.startswith("Cost Estimate")), None)
    return tpl.render(figures=figures, costs=cost_u.data if cost_u else None,
        project=result.inputs.project, infl=result.inputs.influent,
        date=_dt.date.today().strftime("%B %d, %Y"), app=APP_NAME, version=__version__,
        status=result.status, counts=result.counts(), iterations=result.iterations,
        converged=result.converged, warnings=result.warnings,
        process=as_unit.data.get("process", "") if as_unit else "",
        srt=as_unit.data.get("srt", 0) if as_unit else 0,
        compliance=result.compliance, streams=result.streams, sludge=result.sludge,
        units=[u.to_dict() for u in result.units], sources=lib.sources, fmt=_fmt,
    )


def write_wwtp_report(result, path: str | Path, lib=None) -> Path:
    path = Path(path)
    path.write_text(render_wwtp_report(result, lib), encoding="utf-8")
    return path
