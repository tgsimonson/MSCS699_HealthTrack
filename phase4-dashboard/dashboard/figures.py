"""plotly figure builders and reading classification (pure functions, unit tested)

a reading's color comes from the same effective thresholds the alert engine applies to that patient
(GET /patients/{id}/alert-thresholds), so the chart and the alert list always agree. abnormal points also get a
different marker shape and a text label in the hover, so the meaning never depends on color alone.
"""
from __future__ import annotations

import operator
from datetime import datetime, timezone
from typing import Any

import plotly.graph_objects as go

from dashboard.theme import INK_LIGHT, INK_MID, LINE, NAVY, PAPER_DEEP, PLOT_LAYOUT, SEVERITY, TEAL, ZONE

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
RANK = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
SYMBOL = {"critical": "triangle-up", "high": "diamond", "moderate": "square", "low": "circle-open",
          None: "circle", "suspect": "x-thin-open"}
MAX_POINTS = 600


# ---------------------------------------------------------------- limits and classification
def build_limits(thresholds: list[dict], rx: dict | None) -> dict[str, Any]:
    """the threshold rules that apply to single readings, plus the lines and bands the charts draw"""
    rules = [{"code": t["rule_code"], "metric": t["metric"], "comparator": t["comparator"],
              "threshold": t["threshold"], "severity": t["severity"], "contexts": t["applies_to_context"],
              "source": t["source"]} for t in thresholds if t["rule_type"] == "threshold"]
    by = {r["code"]: r["threshold"] for r in rules}
    return {
        "rules": rules,
        "zone": [rx["target_hr_min"], rx["target_hr_max"]] if rx else None,
        "hr_ceiling": by.get("HR_ABOVE_CEILING"),
        "rest_hr_high": by.get("RESTING_HR_HIGH"), "rest_hr_low": by.get("RESTING_HR_LOW"),
        "spo2_floor": by.get("SPO2_LOW"),
        "exercise_sbp_max": by.get("EXERCISE_SBP_HIGH"),
        "rest_sbp_high": by.get("RESTING_SBP_HIGH"), "rest_sbp_low": by.get("RESTING_SBP_LOW"),
    }


def classify(reading: dict, limits: dict, metric: str | None = None) -> str | None:
    """the most severe single-reading rule this reading breaches (consecutive-reading confirmation is the
    engine's job; the chart shows every out-of-range point)"""
    if reading.get("quality") not in (None, "valid"):
        return "suspect"
    worst = None
    for r in limits.get("rules", []):
        if metric and r["metric"] != metric:
            continue
        value = reading.get(r["metric"])
        if value is None or (r["contexts"] and reading.get("context") not in r["contexts"]):
            continue
        if OPS[r["comparator"]](value, r["threshold"]) and RANK[r["severity"]] > RANK.get(worst, 0):
            worst = r["severity"]
    return worst


def point_color(sev: str | None) -> str:
    if sev == "suspect":
        return INK_MID              # gray but still 6.5:1 on white, above the 3:1 needed for a chart symbol
    return SEVERITY[sev][0] if sev in SEVERITY else TEAL


def downsample(points: list[dict], key: str, max_points: int = MAX_POINTS,
               keep: Any = None) -> list[dict]:
    """bucketed min/max downsampling: keeps each bucket's highest and lowest value (so spikes survive) and every
    point for which keep(point) is true (abnormal readings are never dropped)"""
    pts = [p for p in points if p.get(key) is not None]
    if len(pts) <= max_points:
        return pts
    bucket = max(1, len(pts) * 2 // max_points)
    out: dict[int, dict] = {}
    for i in range(0, len(pts), bucket):
        chunk = pts[i:i + bucket]
        lo, hi = min(chunk, key=lambda p: p[key]), max(chunk, key=lambda p: p[key])
        for p in (lo, hi, *(c for c in chunk if keep and keep(c))):
            out[id(p)] = p
    return sorted(out.values(), key=lambda p: p["recorded_at"])


# ---------------------------------------------------------------- trend charts
def _hline(y: float | None, color: str, dash: str, label: str) -> tuple[list, list]:
    if y is None:
        return [], []
    return ([dict(type="line", xref="paper", x0=0, x1=1, y0=y, y1=y, line=dict(color=color, width=1.5, dash=dash))],
            # labels sit at the left edge: the newest readings arrive on the right and must never be covered
            [dict(xref="paper", x=0.005, y=y, text=label, showarrow=False, xanchor="left", yanchor="bottom",
                  font=dict(size=11, color=color), bgcolor="rgba(255,255,255,0.7)", borderpad=1)])


def _base(title: str, uirev: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**PLOT_LAYOUT, title=dict(text=title, x=0, font=dict(size=13, color=NAVY)), uirevision=uirev,
                      height=230)
    return fig


GAP_SECONDS = 600     # readings farther apart than this are separate sessions: the line breaks between them


def _markers(points: list[dict], key: str, limits: dict) -> dict[str, list]:
    out: dict[str, list] = {k: [] for k in ("x", "y", "color", "symbol", "size", "text")}
    prev = None
    for p in points:
        t = parse_time(p["recorded_at"])
        if prev is not None and (t - prev).total_seconds() > GAP_SECONDS:
            for k, blank in (("x", p["recorded_at"]), ("y", None), ("color", TEAL), ("symbol", "circle"),
                             ("size", 0), ("text", "")):
                out[k].append(blank)                  # a None value breaks the line without a visible point
        prev = t
        s = classify(p, limits, key)
        out["x"].append(p["recorded_at"])
        out["y"].append(p[key])
        out["color"].append(point_color(s))
        out["symbol"].append(SYMBOL.get(s, "circle"))
        out["size"].append(10 if s in RANK else 6)
        out["text"].append(f"{SEVERITY[s][3]} reading, {p['context']}" if s in RANK else
                           ("Suspect value (not alerted)" if s == "suspect" else p["context"]))
    return out


def _values(m: dict[str, list]) -> list[float]:
    return [v for v in m["y"] if v is not None]


def _no_data(fig: go.Figure, m: dict[str, list]) -> None:
    if not _values(m):
        fig.add_annotation(xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                           text="No readings in this time range", font=dict(size=13, color=INK_MID))
        fig.update_xaxes(showticklabels=False)


def hr_figure(readings: list[dict], limits: dict, uirev: str = "hr") -> go.Figure:
    pts = downsample(readings, "heart_rate", keep=lambda p: classify(p, limits, "heart_rate") in RANK)
    m = _markers(pts, "heart_rate", limits)
    fig = _base("Heart rate (bpm)", uirev)
    fig.add_trace(go.Scatter(x=m["x"], y=m["y"], mode="lines+markers", name="Heart rate", text=m["text"],
                             line=dict(color=INK_LIGHT, width=1),
                             marker=dict(color=m["color"], symbol=m["symbol"], size=m["size"]),
                             hovertemplate="%{y} bpm<br>%{text}<br>%{x|%b %d %H:%M:%S}<extra></extra>"))
    shapes, notes = [], []
    if limits.get("zone"):
        lo, hi = limits["zone"]
        shapes.append(dict(type="rect", xref="paper", x0=0, x1=1, y0=lo, y1=hi, fillcolor=ZONE, line=dict(width=0),
                           layer="below"))
        notes.append(dict(xref="paper", x=0.005, y=hi, text=f"Target zone {lo}-{hi}", showarrow=False,
                          xanchor="left", yanchor="bottom", font=dict(size=11, color=TEAL),
                          bgcolor="rgba(255,255,255,0.85)", borderpad=1))
    for y, color, dash, label in ((limits.get("hr_ceiling"), SEVERITY["critical"][0], "dash", "Exercise ceiling"),
                                  (limits.get("rest_hr_high"), SEVERITY["moderate"][0], "dot", "Resting limit")):
        s, a = _hline(y, color, dash, f"{label} {y:g}" if y else "")
        shapes += s
        notes += a
    ys = _values(m) or [70]
    top = max([*ys, (limits.get("hr_ceiling") or 150) + 12])
    fig.update_layout(shapes=shapes, annotations=notes, yaxis=dict(**PLOT_LAYOUT["yaxis"], range=[min(40, min(ys) - 5),
                                                                                                  top + 5]))
    _no_data(fig, m)
    return fig


def bp_figure(readings: list[dict], limits: dict, uirev: str = "bp") -> go.Figure:
    pts = [p for p in readings if p.get("systolic_bp") is not None]
    m = _markers(pts, "systolic_bp", limits)
    fig = _base("Blood pressure (mmHg)", uirev)
    fig.add_trace(go.Scatter(x=m["x"], y=m["y"], mode="lines+markers", name="Systolic", text=m["text"],
                             line=dict(color=INK_LIGHT, width=1),
                             marker=dict(color=m["color"], symbol=m["symbol"], size=m["size"]),
                             hovertemplate="Systolic %{y}<br>%{text}<br>%{x|%b %d %H:%M}<extra></extra>"))
    dia = {p["recorded_at"]: p["diastolic_bp"] for p in pts}
    fig.add_trace(go.Scatter(x=m["x"], y=[dia.get(x) if y is not None else None for x, y in zip(m["x"], m["y"])],
                             mode="lines+markers", name="Diastolic",
                             line=dict(color=LINE, width=1), marker=dict(color=INK_MID, size=5),
                             hovertemplate="Diastolic %{y}<extra></extra>"))
    shapes, notes = [], []
    for y, color, dash, label in ((limits.get("exercise_sbp_max"), SEVERITY["high"][0], "dash", "Exercise max"),
                                  (limits.get("rest_sbp_high"), SEVERITY["moderate"][0], "dot", "Resting high"),
                                  (limits.get("rest_sbp_low"), SEVERITY["high"][0], "dot", "Resting low")):
        s, a = _hline(y, color, dash, f"{label} {y:g}" if y else "")
        shapes += s
        notes += a
    fig.update_layout(shapes=shapes, annotations=notes,
                      yaxis=dict(**PLOT_LAYOUT["yaxis"], range=[50, max([*_values(m), 210]) + 10]))
    _no_data(fig, m)
    return fig


def spo2_figure(readings: list[dict], limits: dict, uirev: str = "spo2") -> go.Figure:
    pts = [p for p in readings if p.get("spo2") is not None]
    m = _markers(pts, "spo2", limits)
    fig = _base("Oxygen saturation (%)", uirev)
    fig.add_trace(go.Scatter(x=m["x"], y=m["y"], mode="lines+markers", name="SpO2", text=m["text"],
                             line=dict(color=INK_LIGHT, width=1),
                             marker=dict(color=m["color"], symbol=m["symbol"], size=m["size"]),
                             hovertemplate="%{y}%<br>%{text}<br>%{x|%b %d %H:%M}<extra></extra>"))
    floor = limits.get("spo2_floor")
    s, a = _hline(floor, SEVERITY["critical"][0], "dash", f"Floor {floor:g}" if floor else "")
    fig.update_layout(shapes=s, annotations=a, yaxis=dict(**PLOT_LAYOUT["yaxis"],
                                                          range=[min([*_values(m), 84]) - 2, 101]))
    _no_data(fig, m)
    return fig


# ---------------------------------------------------------------- gauges
def gauge(kind: str, reading: dict | None, limits: dict) -> go.Figure:
    """a gauge whose colored bands are this patient's limits; the number is colored and labeled by severity"""
    key = {"hr": "heart_rate", "spo2": "spo2", "bp": "systolic_bp"}[kind]
    value = reading.get(key) if reading else None
    sev = classify(reading, limits, key) if reading else None
    tint = {k: v[1] for k, v in SEVERITY.items()}
    if kind == "hr":
        lo, hi = limits.get("zone") or (60, 100)
        ceil = limits.get("hr_ceiling") or 150
        rng, steps, mark, title = [40, 200], [([40, lo], PAPER_DEEP), ([lo, hi], ZONE), ([hi, ceil], tint["moderate"]),
                                              ([ceil, 200], tint["critical"])], ceil, "Heart rate"
    elif kind == "spo2":
        floor = limits.get("spo2_floor") or 90
        rng, steps, mark, title = [80, 100], [([80, floor], tint["critical"]), ([floor, 94], tint["moderate"]),
                                              ([94, 100], tint["stable"])], floor, "SpO2"
    else:
        low, high = limits.get("rest_sbp_low") or 90, limits.get("rest_sbp_high") or 160
        rng, steps, mark, title = [60, 220], [([60, low], tint["high"]), ([low, 140], tint["stable"]),
                                              ([140, high], tint["moderate"]), ([high, 220], tint["critical"])], high, \
            "Systolic BP"
    status = "No data" if value is None else (SEVERITY[sev][3] if sev in RANK else
                                              "Suspect" if sev == "suspect" else "In range")
    if value is not None and reading.get("recorded_at"):
        status += f", {_age(reading['recorded_at'])}"
    suffix = {"hr": " bpm", "spo2": "%", "bp": ""}[kind]
    label = f"{reading['diastolic_bp']}" if kind == "bp" and reading and reading.get("diastolic_bp") else None
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value, number=dict(suffix=suffix if kind != "bp" else f"/{label}" if label else "",
                                                       font=dict(size=26, color=point_color(sev) if sev else NAVY)),
        title=dict(text=f"{title}<br><span style='font-size:12px;color:{point_color(sev) if sev else INK_MID}'>"
                        f"{SEVERITY[sev][2] + ' ' if sev in RANK else ''}{status}</span>", font=dict(size=13, color=NAVY)),
        gauge=dict(axis=dict(range=rng, tickcolor=LINE, tickfont=dict(size=10)), bar=dict(color=NAVY, thickness=0.25),
                   bgcolor="white", borderwidth=0, steps=[dict(range=r, color=c) for r, c in steps],
                   threshold=dict(line=dict(color=SEVERITY["critical"][0], width=3), thickness=0.8, value=mark))))
    fig.update_layout(margin=dict(l=24, r=24, t=58, b=8), height=170, paper_bgcolor="white",
                      font=dict(family=PLOT_LAYOUT["font"]["family"], color=INK_MID))
    return fig


# ---------------------------------------------------------------- activity
def activity_figure(days: list[dict], rx: dict | None) -> go.Figure:
    fig = _base("Daily steps and resting heart rate (14 days)", "activity")
    x = [d["activity_date"] for d in days]
    fig.add_trace(go.Bar(x=x, y=[d["steps"] for d in days], name="Steps", marker_color=TEAL, opacity=0.85,
                         hovertemplate="%{y:,} steps<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=[d.get("resting_hr") for d in days], name="Resting HR", yaxis="y2",
                             mode="lines+markers", line=dict(color=NAVY, width=2), marker=dict(size=6),
                             hovertemplate="Resting %{y} bpm<extra></extra>"))
    shapes, notes = [], []
    if rx:
        b = rx["resting_hr_baseline"]
        shapes.append(dict(type="line", xref="paper", yref="y2", x0=0, x1=1, y0=b, y1=b,
                           line=dict(color=NAVY, dash="dot", width=1)))
        notes.append(dict(xref="paper", yref="y2", x=0.01, y=b, text=f"Resting baseline {b}", showarrow=False, xanchor="left",
                          yanchor="bottom", font=dict(size=11, color=NAVY)))
    fig.update_layout(shapes=shapes, annotations=notes, bargap=0.25, showlegend=True,
                      legend=dict(orientation="h", y=1.12, x=1, xanchor="right", font=dict(size=11)),
                      yaxis=dict(**PLOT_LAYOUT["yaxis"], title=None, tickformat=","),
                      yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[40, 110], dtick=10,
                                  title=dict(text="bpm", font=dict(size=11))))
    if not days:
        fig.add_annotation(xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                           text="No activity uploaded in the last 14 days", font=dict(size=13, color=INK_MID))
    return fig


def _age(ts: str) -> str:
    secs = max(0.0, (datetime.now(timezone.utc) - parse_time(ts)).total_seconds())
    return "now" if secs < 60 else f"{secs / 60:.0f} min ago" if secs < 3600 else \
        f"{secs / 3600:.0f} h ago" if secs < 86400 else f"{secs / 86400:.0f} d ago"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
