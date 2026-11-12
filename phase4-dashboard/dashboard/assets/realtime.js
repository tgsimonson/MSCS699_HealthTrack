// websocket client for the healthtrack live stream
// - gets a one-time ticket from the dashboard server (/rt/ticket; the access token never reaches the browser)
// - reconnects with exponential backoff (1 s, 2 s, 4 s ... capped at 30 s)
// - batches events and hands them to the page every 250 ms through the rt-events store, so a burst of readings
//   costs one update instead of one per reading
// - keeps a small timing log in window.__htRT that the automated latency tests read
(function () {
  "use strict";
  var state = { ws: null, attempts: 0, buffer: [], seq: 0 };
  window.__htRT = [];

  function setProps(id, props) {
    if (window.dash_clientside && window.dash_clientside.set_props) {
      window.dash_clientside.set_props(id, props);
    }
  }

  function setStatus(s) {
    setProps("conn-status", { data: { state: s, at: Date.now() } });
  }

  function log(entry) {
    window.__htRT.push(entry);
    if (window.__htRT.length > 2000) window.__htRT.splice(0, 1000);
  }

  function retry() {
    var delay = Math.min(30000, 1000 * Math.pow(2, state.attempts++));
    setStatus("reconnecting");
    setTimeout(connect, delay);
  }

  function connect() {
    if (!document.getElementById("worklist")) {   // sign-in page: nothing to stream yet
      setTimeout(connect, 500);
      return;
    }
    fetch("/rt/ticket", { credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401) { setStatus("signed-out"); throw new Error("signed out"); }
        if (!r.ok) throw new Error("ticket " + r.status);
        return r.json();
      })
      .then(function (t) {
        var ws = new WebSocket(t.url);
        state.ws = ws;
        window.__htWS = ws;                       // exposed for the reconnect test
        ws.onopen = function () { ws.send(JSON.stringify({ type: "auth", ticket: t.ticket })); };
        ws.onmessage = function (ev) {
          var m = JSON.parse(ev.data);
          var now = Date.now();
          if (m.type === "ready") { state.attempts = 0; setStatus("live"); return; }
          if (m.type === "ping") { ws.send('{"type":"pong"}'); return; }
          if (m.type === "error") return;
          m.received_at = now;
          state.buffer.push(m);
          log({ type: m.type, action: m.action || null, patient_id: m.patient_id || null,
                id: m.data && (m.data.vital_id || m.data.alert_id) || null, received_at: now });
        };
        ws.onclose = function (ev) {
          state.ws = null;
          if (ev.code === 4401) { setStatus("reconnecting"); }
          retry();
        };
      })
      .catch(function (e) { if (String(e).indexOf("signed out") < 0) retry(); });
  }

  setInterval(function () {
    if (!state.buffer.length) return;
    var events = state.buffer.splice(0);
    state.seq += 1;
    setProps("rt-events", { data: { seq: state.seq, events: events, flushed_at: Date.now() } });
  }, 250);

  window.addEventListener("load", function () { setTimeout(connect, 200); });
})();
