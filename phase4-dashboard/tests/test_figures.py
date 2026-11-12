"""figure builders and reading classification"""
from __future__ import annotations

import pytest

from dashboard import figures as fx
from dashboard.theme import SEVERITY, TEAL
from tests.conftest import reading


class TestClassification:
    @pytest.mark.parametrize("r,metric,expected", [
        (dict(heart_rate=136), "heart_rate", "critical"),                              # above 128 ceiling
        (dict(heart_rate=128), "heart_rate", None),                                    # at the limit is fine
        (dict(heart_rate=136, ctx="rest"), "heart_rate", "moderate"),                  # resting override 90
        (dict(heart_rate=88, ctx="rest"), "heart_rate", None),
        (dict(heart_rate=38, ctx="rest"), "heart_rate", "high"),
        (dict(spo2=88, ctx="rest"), "spo2", "critical"),
        (dict(systolic_bp=185, diastolic_bp=80, ctx="recovery"), "systolic_bp", "high"),
        (dict(systolic_bp=185, diastolic_bp=80, ctx="rest"), "systolic_bp", "moderate"),   # resting rule instead
        (dict(systolic_bp=160, diastolic_bp=80, ctx="rest"), "systolic_bp", "moderate"),   # >= is inclusive
        (dict(heart_rate=240, quality="suspect"), "heart_rate", "suspect"),
    ])
    def test_matches_engine_rules(self, limits, r, metric, expected):
        ctx = r.pop("ctx", "exercise")
        quality = r.pop("quality", "valid")
        assert fx.classify(reading(1, ctx=ctx, quality=quality, **r), limits, metric) == expected

    def test_limits_keep_only_single_reading_rules(self, limits):
        assert {r["code"] for r in limits["rules"]} == {"HR_ABOVE_CEILING", "SPO2_LOW", "EXERCISE_SBP_HIGH",
                                                        "RESTING_SBP_LOW", "RESTING_HR_LOW", "RESTING_SBP_HIGH",
                                                        "RESTING_HR_HIGH"}
        assert (limits["zone"], limits["hr_ceiling"], limits["rest_hr_high"]) == ([95, 115], 128, 90)

    def test_no_prescription_has_no_zone(self, thresholds):
        assert fx.build_limits(thresholds, None)["zone"] is None


class TestDownsample:
    def test_small_series_untouched(self):
        pts = [reading(i, heart_rate=100) for i in range(50)]
        assert fx.downsample(pts, "heart_rate", 600) == pts

    def test_keeps_spikes_and_abnormal_points(self, limits):
        pts = [reading(3000 - i, heart_rate=100 + i % 3) for i in range(3000)]
        pts[1234]["heart_rate"] = 160                                  # one spike in a long flat series
        pts[2001]["heart_rate"] = 131
        out = fx.downsample(pts, "heart_rate", 300, keep=lambda p: fx.classify(p, limits, "heart_rate") is not None)
        assert len(out) <= 320 and {160, 131} <= {p["heart_rate"] for p in out}
        assert [p["recorded_at"] for p in out] == sorted(p["recorded_at"] for p in out)


class TestCharts:
    def test_hr_chart_bands_lines_and_colors(self, limits):
        pts = [reading(5, heart_rate=110), reading(4, heart_rate=133), reading(3, heart_rate=138)]
        fig = fx.hr_figure(pts, limits, "hr-x")
        trace = fig.data[0]
        assert list(trace.y) == [110, 133, 138]
        assert list(trace.marker.color) == [TEAL, SEVERITY["critical"][0], SEVERITY["critical"][0]]
        assert list(trace.marker.symbol) == ["circle", "triangle-up", "triangle-up"]      # shape, not only color
        assert "Critical reading" in trace.text[1]
        kinds = {(s.type, s.y0, s.y1) for s in fig.layout.shapes}
        assert ("rect", 95, 115) in kinds and ("line", 128, 128) in kinds and ("line", 90, 90) in kinds
        assert fig.layout.uirevision == "hr-x"

    def test_line_breaks_between_sessions(self, limits):
        pts = [reading(120, heart_rate=105), reading(119, heart_rate=106), reading(2, heart_rate=108)]
        y = list(fx.hr_figure(pts, limits).data[0].y)
        assert y == [105, 106, None, 108]

    def test_empty_ranges_say_so(self, limits):
        for fig in (fx.hr_figure([], limits), fx.bp_figure([], limits), fx.spo2_figure([], limits)):
            assert any("No readings" in a.text for a in fig.layout.annotations)

    def test_bp_chart_pairs_systolic_and_diastolic(self, limits):
        pts = [reading(10, ctx="rest", systolic_bp=150, diastolic_bp=85),
               reading(5, ctx="recovery", systolic_bp=186, diastolic_bp=88)]
        fig = fx.bp_figure(pts, limits)
        assert list(fig.data[0].y) == [150, 186] and list(fig.data[1].y) == [85, 88]
        assert fig.data[0].marker.color[1] == SEVERITY["high"][0]

    def test_spo2_floor(self, limits):
        fig = fx.spo2_figure([reading(2, ctx="rest", spo2=97), reading(1, ctx="rest", spo2=88)], limits)
        assert fig.layout.shapes[0].y0 == 90 and fig.data[0].marker.color[1] == SEVERITY["critical"][0]

    def test_activity_baseline(self, rx):
        days = [{"activity_date": f"2026-11-{d:02d}", "steps": 5000 + d, "resting_hr": 66} for d in range(1, 8)]
        fig = fx.activity_figure(days, rx)
        assert fig.data[0].type == "bar" and fig.layout.shapes[0].y0 == 66
        assert any("No activity" in a.text for a in fx.activity_figure([], None).layout.annotations)


class TestGauges:
    def test_hr_gauge_uses_patient_limits(self, limits):
        g = fx.gauge("hr", reading(0.5, heart_rate=136), limits)
        ind = g.data[0]
        assert ind.value == 136 and ind.gauge.threshold.value == 128
        assert [tuple(s.range) for s in ind.gauge.steps] == [(40, 95), (95, 115), (115, 128), (128, 200)]
        assert ind.number.font.color == SEVERITY["critical"][0] and "Critical" in ind.title.text

    def test_in_range_and_no_data(self, limits):
        assert "In range" in fx.gauge("spo2", reading(1, ctx="rest", spo2=97), limits).data[0].title.text
        assert "No data" in fx.gauge("bp", None, limits).data[0].title.text

    def test_bp_gauge_shows_both_numbers(self, limits):
        g = fx.gauge("bp", reading(1, ctx="rest", systolic_bp=121, diastolic_bp=73), limits)
        assert g.data[0].value == 121 and g.data[0].number.suffix == "/73"
