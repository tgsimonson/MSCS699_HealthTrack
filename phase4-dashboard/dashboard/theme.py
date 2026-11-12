"""colors, severity styling, and plot defaults (the clinical slate palette used across the healthtrack documents)

every severity has a text label and a glyph as well as a color, so meaning never depends on color alone
(requirement NFR-14). text colors meet wcag 2.1 aa contrast (4.5:1) on white and on their tint.
"""
from __future__ import annotations

TEAL = "#2B7A8C"
NAVY = "#1E3A5F"
INK = "#1F2933"
INK_MID = "#52606D"
INK_LIGHT = "#9AA5B1"
PAPER = "#FFFFFF"
PAPER_DEEP = "#EEF2F6"
LINE = "#D9E2EC"
ZONE = "rgba(43, 122, 140, 0.12)"          # target heart rate zone band

# severity: (text color, tint, glyph, label)
SEVERITY = {
    "critical": ("#B42318", "#FEE4E2", "▲", "Critical"),
    "high": ("#B54708", "#FDEAD7", "◆", "High"),
    "moderate": ("#8A6100", "#FEF7C3", "●", "Moderate"),
    "low": ("#475467", "#EAECF0", "○", "Low"),
    "stable": ("#1B6E4B", "#DCFAE6", "✓", "Stable"),
}
PRIORITY_NAME = {4: "critical", 3: "high", 2: "moderate", 1: "low", 0: "stable"}

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

PLOT_LAYOUT = dict(
    font=dict(family=FONT, size=12, color=INK_MID),
    paper_bgcolor=PAPER, plot_bgcolor=PAPER,
    margin=dict(l=48, r=16, t=36, b=32),
    xaxis=dict(showgrid=False, linecolor=LINE, tickcolor=LINE, ticks="outside"),
    yaxis=dict(gridcolor=PAPER_DEEP, zeroline=False, linecolor=LINE),
    hoverlabel=dict(bgcolor=PAPER, bordercolor=LINE, font=dict(family=FONT, color=INK)),
    showlegend=False,
)


def severity_color(sev: str | None) -> str:
    return SEVERITY.get(sev or "stable", SEVERITY["stable"])[0]
