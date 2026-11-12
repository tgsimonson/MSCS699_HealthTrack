// clientside callbacks: append live readings to the open charts with plotly extendTraces (via dcc.Graph
// extendData), so a new reading never redraws a chart or waits on the server. classification mirrors
// dashboard/figures.py classify(): the same effective thresholds the alert engine uses for this patient.
(function () {
  "use strict";
  var RANK = { critical: 4, high: 3, moderate: 2, low: 1 };
  var COLOR = { critical: "#B42318", high: "#B54708", moderate: "#8A6100", low: "#475467" };
  var SYMBOL = { critical: "triangle-up", high: "diamond", moderate: "square", low: "circle-open" };
  var LABEL = { critical: "Critical", high: "High", moderate: "Moderate", low: "Low" };
  var OPS = {
    ">": function (a, b) { return a > b; }, ">=": function (a, b) { return a >= b; },
    "<": function (a, b) { return a < b; }, "<=": function (a, b) { return a <= b; }
  };
  var MAX_POINTS = 3000;

  function classify(r, limits, metric) {
    if (r.quality && r.quality !== "valid") return "suspect";
    var worst = null;
    (limits.rules || []).forEach(function (rule) {
      if (rule.metric !== metric) return;
      var v = r[rule.metric];
      if (v === null || v === undefined) return;
      if (rule.contexts && rule.contexts.indexOf(r.context) < 0) return;
      if (OPS[rule.comparator](v, rule.threshold) && RANK[rule.severity] > (RANK[worst] || 0)) worst = rule.severity;
    });
    return worst;
  }

  function point(r, limits, metric) {
    var s = classify(r, limits, metric);
    var abnormal = s && RANK[s];
    return {
      color: abnormal ? COLOR[s] : (s === "suspect" ? "#52606D" : "#2B7A8C"),
      symbol: abnormal ? SYMBOL[s] : (s === "suspect" ? "x-thin-open" : "circle"),
      size: abnormal ? 10 : 6,
      text: abnormal ? LABEL[s] + " reading, " + r.context : (s === "suspect" ? "Suspect value (not alerted)" : r.context)
    };
  }

  var GAP_MS = 600000;   // same rule as figures.py: readings 10+ minutes apart are separate sessions

  function lastTime(graphId, trace) {
    var g = document.getElementById(graphId);
    var plot = g && g.querySelector(".js-plotly-plot");
    var xs = plot && plot.data && plot.data[trace] ? plot.data[trace].x : null;
    if (!xs) return null;
    for (var i = xs.length - 1; i >= 0; i--) { if (xs[i]) return Date.parse(xs[i]); }
    return null;
  }

  function series(graphId, n) {
    var e = function () { var a = []; for (var i = 0; i < n; i++) a.push([]); return a; };
    var last = [];
    for (var i = 0; i < n; i++) last.push(lastTime(graphId, i));
    return { data: { x: e(), y: e(), "marker.color": e(), "marker.symbol": e(), "marker.size": e(), text: e() },
             last: last };
  }

  function add(d, i, x, y, color, symbol, size, text) {
    d.x[i].push(x); d.y[i].push(y); d["marker.color"][i].push(color);
    d["marker.symbol"][i].push(symbol); d["marker.size"][i].push(size); d.text[i].push(text);
  }

  function push(s, i, r, value, p) {
    var t = Date.parse(r.recorded_at);
    if (s.last[i] !== null && t - s.last[i] > GAP_MS) add(s.data, i, r.recorded_at, null, "#2B7A8C", "circle", 0, "");
    s.last[i] = t;
    add(s.data, i, r.recorded_at, value, p.color, p.symbol, p.size, p.text);
  }

  var EMPTY_TEXT = "No readings in this time range";

  // a chart drawn with no data carries an empty-state label and hidden time ticks; the first live reading
  // removes the label (threshold labels stay) and turns the ticks back on
  function clearEmpty(graphId) {
    var g = document.getElementById(graphId);
    var plot = g && g.querySelector(".js-plotly-plot");
    if (!plot || !plot.layout || !window.Plotly) return;
    var notes = plot.layout.annotations || [];
    var kept = notes.filter(function (a) { return a.text !== EMPTY_TEXT; });
    if (kept.length !== notes.length) window.Plotly.relayout(plot, { annotations: kept, "xaxis.showticklabels": true });
  }

  window.dash_clientside = Object.assign({}, window.dash_clientside, {
    ht: {
      extend: function (batch, selected, limits) {
        var nu = window.dash_clientside.no_update;
        if (!batch || !batch.events || !selected || !limits || limits.patient_id !== selected) return [nu, nu, nu];
        var hr = series("hr-graph", 1), bp = series("bp-graph", 2), sp = series("spo2-graph", 1);
        var counts = [0, 0, 0], applied = Date.now();
        batch.events.forEach(function (e) {
          if (e.type !== "vital" || e.patient_id !== selected) return;
          var r = e.data;
          if (r.heart_rate !== null && r.heart_rate !== undefined) {
            push(hr, 0, r, r.heart_rate, point(r, limits, "heart_rate")); counts[0]++;
          }
          if (r.systolic_bp !== null && r.systolic_bp !== undefined) {
            push(bp, 0, r, r.systolic_bp, point(r, limits, "systolic_bp"));
            push(bp, 1, r, r.diastolic_bp, { color: "#52606D", symbol: "circle", size: 5, text: "diastolic" });
            counts[1]++;
          }
          if (r.spo2 !== null && r.spo2 !== undefined) { push(sp, 0, r, r.spo2, point(r, limits, "spo2")); counts[2]++; }
          window.__htRT.push({ type: "applied", id: r.vital_id, received_at: e.received_at, applied_at: applied });
        });
        if (counts[0]) clearEmpty("hr-graph");
        if (counts[1]) clearEmpty("bp-graph");
        if (counts[2]) clearEmpty("spo2-graph");
        return [counts[0] ? [hr.data, [0], MAX_POINTS] : nu, counts[1] ? [bp.data, [0, 1], MAX_POINTS] : nu,
                counts[2] ? [sp.data, [0], MAX_POINTS] : nu];
      }
    }
  });
})();
