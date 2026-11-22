/* app.js - TCP Congestion Control Lab dashboard (vanilla JS + Chart.js, offline). */
(function () {
  "use strict";

  const ALGOS = ["reno", "cubic", "bbr"];
  const NAMES = { reno: "Reno", cubic: "CUBIC", bbr: "BBR" };
  const COLORS = { reno: "#d95f02", cubic: "#1b9e77", bbr: "#7570b3" };
  const SRC_LABEL = { mininet: "Linux kernel (Mininet)", ns3: "NS-3 simulation" };

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const state = { meta: null, source: "mininet", tab: "overview", charts: {}, replay: null, whatifTimer: null };

  // ------------------------------------------------------------------ helpers
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function fmt(n, d) {
    if (n === null || n === undefined || Number.isNaN(n)) return "–";
    d = d === undefined ? 1 : d;
    return Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  async function api(path, params, opts) {
    const q = new URLSearchParams(params || {});
    const r = await fetch("/api/" + path + (q.toString() ? "?" + q : ""), opts || {});
    if (!r.ok) throw new Error("API " + path + " failed: " + r.status);
    return r.json();
  }
  function dot(algo) { return '<span class="dot" style="background:' + COLORS[algo] + '"></span>'; }
  function sourceInfo(s) { return state.meta.sources[s || state.source]; }
  function present(s) { return state.meta && state.meta.sources[s] && state.meta.sources[s].present; }

  function chartDefaults() {
    Chart.defaults.color = cssVar("--muted");
    Chart.defaults.borderColor = cssVar("--line");
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
  }
  function mk(id, cfg) {
    if (state.charts[id]) state.charts[id].destroy();
    const el = document.getElementById(id);
    if (!el) return null;
    cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 250 } }, cfg.options || {});
    state.charts[id] = new Chart(el.getContext("2d"), cfg);
    return state.charts[id];
  }
  function killCharts(ids) {
    ids.forEach(id => { if (state.charts[id]) { state.charts[id].destroy(); delete state.charts[id]; } });
  }
  function empty(el, title, html) {
    el.innerHTML = '<div class="empty"><h3>' + esc(title) + "</h3>" + (html || "") + "</div>";
  }
  const legendNoHidden = { labels: { usePointStyle: true, boxWidth: 9, boxHeight: 7, filter: it => !it.text.startsWith("_") } };
  const tooltipNoHidden = { filter: it => !it.dataset.label.startsWith("_") };

  // ------------------------------------------------------------------ theme
  function applyTheme(t) {
    if (t) document.documentElement.setAttribute("data-theme", t);
    chartDefaults();
  }
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("tcpcc-theme"); } catch (e) { /* storage may be blocked */ }
    applyTheme(saved);
    $("#theme-btn").addEventListener("click", () => {
      const cur = document.documentElement.getAttribute("data-theme") ||
        (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      const next = cur === "dark" ? "light" : "dark";
      try { localStorage.setItem("tcpcc-theme", next); } catch (e) { /* ignore */ }
      applyTheme(next);
      renderTab(state.tab);
    });
  }

  // ------------------------------------------------------------------ banner + source switch
  function renderBanner() {
    const b = $("#banner");
    const msgs = [];
    let warn = false;
    SRC_ORDER.forEach(s => {
      const i = sourceInfo(s);
      if (i.present && i.sample) {
        warn = true;
        msgs.push("<p><strong>" + esc(SRC_LABEL[s]) + ": sample data.</strong> " + esc((i.env && i.env.note) || "This is a shipped sample.") +
          " After running your own experiments, click <em>Reload data</em> to replace it.</p>");
      }
    });
    if (!present("mininet")) {
      msgs.push("<p><strong>No Linux-kernel (Mininet) results yet.</strong> Run <code>sudo python3 mininet/run_experiments.py</code>, then click <em>Reload data</em>. Steps are in README.md.</p>");
    }
    if (!present("mininet") && !present("ns3")) { warn = true; msgs.unshift("<p><strong>No data imported at all.</strong></p>"); }
    b.className = "banner" + (warn ? "" : " info");
    b.hidden = msgs.length === 0;
    b.innerHTML = msgs.join("");
  }
  const SRC_ORDER = ["mininet", "ns3"];
  function renderSourceSwitch() {
    $$("#source-switch button").forEach(btn => {
      const s = btn.dataset.src;
      btn.disabled = !present(s);
      btn.classList.toggle("active", s === state.source);
      btn.title = present(s) ? btn.title : "No data imported for this source yet";
    });
  }

  // ------------------------------------------------------------------ tabs
  function showTab(name) {
    state.tab = name;
    $$(".tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    $$(".tab").forEach(s => s.classList.toggle("active", s.id === "tab-" + name));
    if (name !== "replay") stopReplay();
    renderTab(name);
  }
  function renderTab(name) {
    const fn = { overview: loadOverview, sweeps: loadSweeps, replay: loadReplay, fairness: loadFairness,
      compare: loadCompare, packets: loadPackets, whatif: loadWhatIf, about: loadAbout }[name];
    if (fn) fn().catch(err => { console.error(err); });
  }

  // ------------------------------------------------------------------ overview
  async function loadOverview() {
    const info = sourceInfo();
    const kp = $("#kpis"), wt = $("#winner-table"), fd = $("#findings");
    if (!info.present) {
      kp.innerHTML = ""; fd.innerHTML = "";
      empty(wt, "No data for " + SRC_LABEL[state.source], "<p>Run the experiments, then click <em>Reload data</em>.</p>");
      return;
    }
    const env = info.env || {};
    const ver = state.source === "ns3" ? "NS-3 " + (env.ns3_version || "?") : "Kernel " + (env.kernel || "?");
    kp.innerHTML =
      kpi(info.scenarios, "scenarios") + kpi(info.runs, "runs (scenario × repetition)") +
      kpi(info.algos.map(a => NAMES[a] || a).join(" · "), "algorithms", true) +
      kpi(ver, "implementation under test", true) +
      kpi(env.duration_s ? env.duration_s + " s × " + (env.runs || "?") : "–", "run length × repetitions", true);

    const params = ["loss", "rtt", "bw", "buf"].filter(p => state.meta.params[p]);
    const sweeps = {};
    await Promise.all(params.map(async p => { sweeps[p] = await api("sweep", { source: state.source, param: p, metric: "throughput_mbps" }); }));
    const bufRtt = await api("sweep", { source: state.source, param: "buf", metric: "mean_rtt_ms" });

    // winner board
    let html = '<table class="tbl"><thead><tr><th>Condition</th>' + info.algos.map(a => "<th>" + dot(a) + NAMES[a] + "</th>").join("") + "<th>Highest</th></tr></thead><tbody>";
    params.forEach(p => {
      const sw = sweeps[p];
      const xs = new Set();
      Object.values(sw.series).forEach(arr => arr.forEach(pt => xs.add(pt.x)));
      if (!xs.size) return;
      html += '<tr class="group"><td colspan="' + (info.algos.length + 2) + '">' + esc(sw.x_label) + "</td></tr>";
      Array.from(xs).sort((a, b) => a - b).forEach(x => {
        let best = null, bv = -1;
        const cells = info.algos.map(a => {
          const pt = (sw.series[a] || []).find(q => q.x === x);
          if (pt && pt.mean > bv) { bv = pt.mean; best = a; }
          return pt ? pt.mean : null;
        });
        html += "<tr><td>" + fmt(x, x % 1 ? 2 : 0) + "</td>" + cells.map((v, i) =>
          '<td class="' + (info.algos[i] === best ? "best" : "") + '">' + (v === null ? "–" : fmt(v) + " Mbps") + "</td>").join("") +
          "<td>" + (best ? dot(best) + NAMES[best] : "–") + "</td></tr>";
      });
    });
    wt.innerHTML = html + "</tbody></table>";

    // findings (every sentence is built from the numbers above)
    const out = [];
    const loss = sweeps.loss;
    if (loss) {
      const xs = new Set(); Object.values(loss.series).forEach(arr => arr.forEach(pt => xs.add(pt.x)));
      const pick = Array.from(xs).filter(x => x > 0).sort((a, b) => a - b);
      const x = pick.includes(1) ? 1 : pick[pick.length - 1];
      if (x !== undefined) {
        const vals = info.algos.map(a => ({ a, v: ((loss.series[a] || []).find(q => q.x === x) || {}).mean })).filter(o => o.v !== undefined);
        if (vals.length > 1) {
          vals.sort((p, q) => q.v - p.v);
          const hi = vals[0], lo = vals[vals.length - 1];
          out.push("At <strong>" + x + "% random loss</strong>, " + NAMES[hi.a] + " reached <strong>" + fmt(hi.v) + " Mbps</strong>, " +
            (lo.v > 0 ? fmt(hi.v / lo.v) + "× the " : "versus ") + fmt(lo.v) + " Mbps of " + NAMES[lo.a] + ".");
        }
      }
    }
    const rtt = sweeps.rtt;
    if (rtt) {
      const xs = new Set(); Object.values(rtt.series).forEach(arr => arr.forEach(pt => xs.add(pt.x)));
      const x = Math.max.apply(null, Array.from(xs));
      const vals = info.algos.map(a => ({ a, v: ((rtt.series[a] || []).find(q => q.x === x) || {}).mean })).filter(o => o.v !== undefined).sort((p, q) => q.v - p.v);
      if (vals.length > 1) out.push("On the longest path (<strong>" + x + " ms RTT</strong>) the order is " + vals.map(o => NAMES[o.a] + " " + fmt(o.v) + " Mbps").join(" > ") + ".");
    }
    if (bufRtt && Object.keys(bufRtt.series).length) {
      const xs = new Set(); Object.values(bufRtt.series).forEach(arr => arr.forEach(pt => xs.add(pt.x)));
      const x = Math.max.apply(null, Array.from(xs));
      const vals = info.algos.map(a => ({ a, v: ((bufRtt.series[a] || []).find(q => q.x === x) || {}).mean })).filter(o => o.v !== undefined);
      if (vals.length) out.push("With a deep buffer (<strong>" + x + "× BDP</strong>) the mean RTT was " + vals.map(o => NAMES[o.a] + " " + fmt(o.v, 0) + " ms").join(", ") + " (propagation RTT " + state.meta.base.rtt + " ms).");
    }
    fd.innerHTML = out.length ? out.map(s => "<li>" + s + "</li>").join("") : "<li>Not enough sweep data yet.</li>";
    if (info.sample) fd.innerHTML += "<li><em>These figures come from sample data (see the banner), not from your own runs.</em></li>";
  }
  function kpi(v, l, small) {
    return '<div class="kpi"><div class="v' + (small ? " small" : "") + '">' + esc(v) + '</div><div class="l">' + esc(l) + "</div></div>";
  }

  // ------------------------------------------------------------------ sweeps
  function sweepDatasets(series, algos, dashed, labelSuffix, withBands) {
    const ds = [];
    algos.forEach(a => {
      const pts = series[a] || [];
      if (!pts.length) return;
      if (withBands && pts.some(p => p.std)) {
        ds.push({ label: "_lo" + a + labelSuffix, data: pts.map(p => [p.x, p.mean - (p.std || 0)]), parsing: false, borderWidth: 0, pointRadius: 0, fill: false, _x: true });
        ds.push({ label: "_hi" + a + labelSuffix, data: pts.map(p => [p.x, p.mean + (p.std || 0)]), parsing: false, borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: hexA(COLORS[a], 0.14), _x: true });
      }
      ds.push({ label: NAMES[a] + labelSuffix, _algo: a, data: pts.map(p => p.mean), borderColor: COLORS[a], backgroundColor: COLORS[a],
        borderDash: dashed ? [7, 5] : [], pointStyle: dashed ? "rect" : "circle", pointRadius: 4, borderWidth: 2.2, tension: 0.15, _pts: pts });
    });
    return ds;
  }
  function categoryChart(id, seriesMap, algos, xLabel, yLabel, bands) {
    // seriesMap: [{series, dashed, suffix}] ; x categories are the union of all x values
    const xs = new Set();
    seriesMap.forEach(s => Object.values(s.series).forEach(arr => arr.forEach(p => xs.add(p.x))));
    const cats = Array.from(xs).sort((a, b) => a - b);
    const datasets = [];
    seriesMap.forEach(s => {
      algos.forEach(a => {
        const pts = s.series[a] || [];
        if (!pts.length) return;
        const byX = new Map(pts.map(p => [p.x, p]));
        const std = cats.map(x => byX.has(x) ? (byX.get(x).std || 0) : null);
        const mean = cats.map(x => byX.has(x) ? byX.get(x).mean : null);
        if (bands && std.some(v => v)) {
          datasets.push({ label: "_lo" + a + s.suffix, data: mean.map((m, i) => m === null ? null : m - std[i]), borderWidth: 0, pointRadius: 0, fill: false });
          datasets.push({ label: "_hi" + a + s.suffix, data: mean.map((m, i) => m === null ? null : m + std[i]), borderWidth: 0, pointRadius: 0, fill: "-1", backgroundColor: hexA(COLORS[a], 0.13) });
        }
        datasets.push({ label: NAMES[a] + s.suffix, data: mean, borderColor: COLORS[a], backgroundColor: COLORS[a], borderDash: s.dashed ? [7, 5] : [],
          pointStyle: s.dashed ? "rect" : "circle", pointRadius: 4, pointHoverRadius: 6, borderWidth: 2.2, tension: 0.15, spanGaps: true });
      });
    });
    return mk(id, {
      type: "line",
      data: { labels: cats.map(x => (x % 1 ? String(x) : String(x))), datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: { legend: legendNoHidden, tooltip: Object.assign({ callbacks: { label: c => c.dataset.label + ": " + fmt(c.parsed.y, 2) } }, tooltipNoHidden) },
        scales: { x: { title: { display: true, text: xLabel } }, y: { title: { display: true, text: yLabel }, beginAtZero: true } },
      },
    });
  }
  async function loadSweeps() {
    const box = $("#sw-table");
    if (!sourceInfo().present) { killCharts(["sw-chart"]); empty(box, "No data for " + SRC_LABEL[state.source]); return; }
    const param = $("#sw-param").value, metric = $("#sw-metric").value;
    const d = await api("sweep", { source: state.source, param, metric });
    const algos = sourceInfo().algos;
    categoryChart("sw-chart", [{ series: d.series, dashed: false, suffix: "" }], algos, d.x_label, d.y_label, true);
    const xs = new Set(); Object.values(d.series).forEach(a => a.forEach(p => xs.add(p.x)));
    const cats = Array.from(xs).sort((a, b) => a - b);
    let h = '<table class="tbl"><thead><tr><th>' + esc(d.x_label) + "</th>" + algos.map(a => "<th>" + dot(a) + NAMES[a] + "</th>").join("") + "</tr></thead><tbody>";
    cats.forEach(x => {
      h += "<tr><td>" + x + "</td>" + algos.map(a => {
        const p = (d.series[a] || []).find(q => q.x === x);
        return "<td>" + (p ? fmt(p.mean, 2) + ' <span class="sub">± ' + fmt(p.std, 2) + " (n=" + p.n + ")</span>" : "–") + "</td>";
      }).join("") + "</tr>";
    });
    box.innerHTML = h + "</tbody></table>";
  }

  // ------------------------------------------------------------------ replay
  function scenarioLabel(s) {
    // the scenario id starts with the algorithms of every flow, e.g. "cubic-bbr_bw50_..."
    const al = s.scenario.split("_")[0].split("-").map(a => NAMES[a] || a);
    if (s.n_flows > 1) return al.join(" vs ") + " · buffer " + s.buf_bdp + "× BDP";
    return al[0] + " · " + s.bw_mbps + " Mbps · " + s.rtt_ms + " ms · loss " + s.loss_pct + "% · buffer " + s.buf_bdp + "×";
  }
  async function loadReplay() {
    const sel = $("#rp-scenario");
    if (!sourceInfo().present) { stopReplay(); empty($("#rp-readout"), "No data for " + SRC_LABEL[state.source]); return; }
    const list = (await api("scenarios", { source: state.source })).filter(s => s.has_timeseries);
    if (!list.length) { stopReplay(); empty($("#rp-readout"), "No time-series recorded", "<p>The time-series files are written by the experiment runners.</p>"); return; }
    const prev = sel.value;
    const groups = {};
    list.forEach(s => { (groups[s.grp] = groups[s.grp] || []).push(s); });
    sel.innerHTML = Object.keys(groups).map(g => '<optgroup label="' + esc(g.replace("sweep_", "sweep: ").replace("fairness", "fairness (2 flows)")) + '">' +
      groups[g].map(s => '<option value="' + esc(s.scenario) + '">' + esc(scenarioLabel(s)) + "</option>").join("") + "</optgroup>").join("");
    const want = list.find(s => s.scenario === prev) || list.find(s => s.scenario === "bbr_bw50_rtt50_loss1_buf1") || list[0];
    sel.value = want.scenario;
    await loadReplayData();
  }
  function percentile(arr, p) {
    const a = arr.filter(v => v !== null && !Number.isNaN(v)).sort((x, y) => x - y);
    if (!a.length) return 0;
    return a[Math.min(a.length - 1, Math.floor(p * (a.length - 1)))];
  }
  async function loadReplayData() {
    stopReplay();
    const scenario = $("#rp-scenario").value;
    const runSel = $("#rp-run");
    const d = await api("timeseries", { source: state.source, scenario, run: runSel.value || "" });
    if (!d.runs.length) return;
    runSel.innerHTML = d.runs.map(r => '<option value="' + r + '">' + r + "</option>").join("");
    runSel.value = d.run;
    const flows = Object.keys(d.flows).sort();
    let dur = 0;
    flows.forEach(f => { const t = d.flows[f].t; if (t.length) dur = Math.max(dur, t[t.length - 1]); });
    const r = { data: d, flows, dur: dur || 1, t: 0, playing: false, last: 0, particles: {}, link: d.link || {} };
    state.replay = r;

    const mkSeries = (field) => flows.map(f => ({
      label: NAMES[d.flows[f].algo] + (flows.length > 1 ? " (flow " + f + ")" : ""),
      _pts: d.flows[f].t.map((t, i) => ({ x: t, y: d.flows[f][field][i] })),
      data: [], parsing: false, borderColor: COLORS[d.flows[f].algo], backgroundColor: COLORS[d.flows[f].algo],
      borderDash: f === "2" ? [6, 4] : [], borderWidth: 2, pointRadius: 0, tension: 0.1,
    }));
    const mkRp = (id, field, yTitle, clip) => {
      const ds = mkSeries(field);
      const all = [].concat.apply([], ds.map(s => s._pts.map(p => p.y)));
      const opts = { x: { type: "linear", min: 0, max: Math.ceil(r.dur), title: { display: true, text: "Time (s)" } }, y: { beginAtZero: true, title: { display: false } } };
      let clipped = false;
      if (clip) {
        const top = percentile(all, 0.98) * 1.3;
        if (Math.max.apply(null, all.filter(v => v !== null)) > top && top > 0) { opts.y.max = Math.ceil(top / 50) * 50; clipped = true; }
      }
      mk(id, { type: "line", data: { datasets: ds }, options: { animation: false, interaction: { mode: "nearest", intersect: false },
        plugins: { legend: { labels: { usePointStyle: true, boxWidth: 9, boxHeight: 7 } } }, scales: opts } });
      return clipped;
    };
    const clipped = mkRp("rp-cwnd", "cwnd", "segments", true);
    mkRp("rp-rtt", "rtt_ms", "ms", false);
    mkRp("rp-rate", "delivery_mbps", "Mbps", false);
    $("#rp-note").textContent = clipped
      ? "The cwnd axis is clipped at 1.3× its 98th percentile: some implementations report an extreme transient value right after the start (NS-3's BBR does). The data itself is not modified."
      : (state.source === "mininet" ? "Sampled from the kernel with `ss -ti` about every 0.2 s while iPerf3 ran." : "Sampled every 0.1 s from NS-3 trace sources.");
    $("#rp-scrub").value = 0;
    setReplayTime(0);
    drawPipe(0);
  }
  function setReplayTime(t) {
    const r = state.replay; if (!r) return;
    r.t = Math.max(0, Math.min(r.dur, t));
    $("#rp-time").textContent = fmt(r.t, 1) + " / " + fmt(r.dur, 0) + " s";
    $("#rp-scrub").value = Math.round(r.t / r.dur * 1000);
    const readout = [];
    r.flows.forEach((f, fi) => {
      const fl = r.data.flows[f];
      let lo = 0, hi = fl.t.length - 1, idx = -1;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (fl.t[mid] <= r.t) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
      ["rp-cwnd", "rp-rtt", "rp-rate"].forEach(id => {
        const ch = state.charts[id];
        if (ch && ch.data.datasets[fi]) ch.data.datasets[fi].data = ch.data.datasets[fi]._pts.slice(0, idx + 1);
      });
      if (idx >= 0) {
        r.cur = r.cur || {};
        r.cur[f] = { rate: fl.delivery_mbps[idx] || 0 };
        readout.push('<span>' + dot(fl.algo) + "<strong>" + NAMES[fl.algo] + (r.flows.length > 1 ? " #" + f : "") + "</strong> cwnd " + fmt(fl.cwnd[idx], 0) +
          " · RTT " + fmt(fl.rtt_ms[idx], 1) + " ms · " + fmt(fl.delivery_mbps[idx], 1) + " Mbps</span>");
      }
    });
    ["rp-cwnd", "rp-rtt", "rp-rate"].forEach(id => { if (state.charts[id]) state.charts[id].update("none"); });
    $("#rp-readout").innerHTML = readout.join("");
  }
  function stopReplay() {
    if (state.replay) state.replay.playing = false;
    const b = $("#rp-play"); if (b) b.textContent = "▶ Play";
  }
  function toggleReplay() {
    const r = state.replay; if (!r) return;
    if (r.playing) { stopReplay(); return; }
    if (r.t >= r.dur - 0.05) setReplayTime(0);
    r.playing = true; r.last = performance.now();
    $("#rp-play").textContent = "❚❚ Pause";
    requestAnimationFrame(tick);
  }
  function tick(now) {
    const r = state.replay;
    if (!r || !r.playing || state.tab !== "replay") { stopReplay(); return; }
    const dt = Math.min(0.1, (now - r.last) / 1000);
    r.last = now;
    const speed = parseFloat($("#rp-speed").value) || 1;
    setReplayTime(r.t + dt * speed);
    drawPipe(dt * speed);
    if (r.t >= r.dur - 1e-6) { stopReplay(); return; }
    requestAnimationFrame(tick);
  }
  function drawPipe(dt) {
    const r = state.replay, cv = $("#rp-pipe");
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = 150;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const muted = cssVar("--muted"), line = cssVar("--line"), surf = cssVar("--surface"), text = cssVar("--text");
    const n = r ? r.flows.length : 1;
    const pipeL = 110, pipeR = w - 110, pipeY = 40, pipeH = 70;
    g.fillStyle = surf; g.strokeStyle = line; g.lineWidth = 1.5;
    g.beginPath(); g.roundRect ? g.roundRect(pipeL, pipeY, pipeR - pipeL, pipeH, 12) : g.rect(pipeL, pipeY, pipeR - pipeL, pipeH); g.fill(); g.stroke();
    // endpoints
    const nodes = r ? r.flows.map(f => r.data.flows[f].algo) : ["cubic"];
    nodes.forEach((a, i) => {
      const y = pipeY + pipeH * (i + 1) / (n + 1);
      g.fillStyle = COLORS[a]; g.beginPath(); g.arc(46, y, 13, 0, 7); g.fill();
      g.strokeStyle = COLORS[a]; g.globalAlpha = 0.35; g.beginPath(); g.moveTo(59, y); g.lineTo(pipeL, y); g.stroke(); g.globalAlpha = 1;
    });
    g.fillStyle = muted; g.beginPath(); g.arc(w - 46, pipeY + pipeH / 2, 13, 0, 7); g.fill();
    g.fillStyle = muted; g.font = "11.5px system-ui, sans-serif"; g.textAlign = "center";
    g.fillText("senders", 46, 140); g.fillText("receiver", w - 46, 140);
    if (!r) return;
    const bw = r.link.bw_mbps || 50;
    let total = 0;
    r.flows.forEach((f, i) => {
      const rate = (r.cur && r.cur[f] ? r.cur[f].rate : 0);
      total += rate;
      const y = pipeY + pipeH * (i + 1) / (n + 1);
      const list = (r.particles[f] = r.particles[f] || []);
      const speed = 170;                                  // px per second of replay time
      const spawn = (rate / bw) * 26 * dt;                // particles per frame ~ delivery rate
      r._acc = r._acc || {}; r._acc[f] = (r._acc[f] || 0) + spawn;
      while (r._acc[f] >= 1) { list.push(pipeL + 4); r._acc[f] -= 1; }
      for (let k = list.length - 1; k >= 0; k--) { list[k] += speed * dt; if (list[k] > pipeR - 4) list.splice(k, 1); }
      g.fillStyle = COLORS[r.data.flows[f].algo];
      list.forEach(x => { g.beginPath(); g.arc(x, y, 3.4, 0, 7); g.fill(); });
    });
    g.fillStyle = text; g.font = "600 12.5px system-ui, sans-serif"; g.textAlign = "center";
    g.fillText("bottleneck " + bw + " Mbps · using " + fmt(total, 1) + " Mbps (" + fmt(total / bw * 100, 0) + "%)", (pipeL + pipeR) / 2, 30);
    g.fillStyle = muted; g.font = "11.5px system-ui, sans-serif";
    g.fillText("RTT " + (r.link.rtt_ms || "?") + " ms · loss " + (r.link.loss_pct || 0) + "% · buffer " + (r.link.buf_bdp || "?") + "× BDP", (pipeL + pipeR) / 2, 134);
  }

  // ------------------------------------------------------------------ fairness
  async function loadFairness() {
    const rows = await api("fairness", { source: state.source });
    const tbl = $("#fr-table");
    if (!rows.length) {
      killCharts(["fr-share", "fr-jain"]);
      empty(tbl, "No two-flow scenarios in " + SRC_LABEL[state.source]);
      return;
    }
    const bufs = Array.from(new Set(rows.map(r => r.buf))).sort((a, b) => a - b);
    const sel = $("#fr-buf");
    if (!sel.options.length || sel.dataset.src !== state.source) {
      sel.innerHTML = bufs.map(b => '<option value="' + b + '">' + b + "× BDP</option>").join("");
      sel.value = bufs.includes(1) ? 1 : bufs[0];
      sel.dataset.src = state.source;
    }
    const b = parseFloat(sel.value);
    const cur = rows.filter(r => r.buf === b);
    const lab = r => NAMES[r.a1] + " vs " + NAMES[r.a2];
    mk("fr-share", {
      type: "bar",
      data: { labels: cur.map(lab), datasets: [
        { label: "Flow 1", data: cur.map(r => r.t1), backgroundColor: cur.map(r => COLORS[r.a1]) },
        { label: "Flow 2", data: cur.map(r => r.t2), backgroundColor: cur.map(r => hexA(COLORS[r.a2], 0.55)), borderColor: cur.map(r => COLORS[r.a2]), borderWidth: 1.5 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => { const r = cur[c.dataIndex]; return (c.datasetIndex ? NAMES[r.a2] : NAMES[r.a1]) + " (flow " + (c.datasetIndex + 1) + "): " + fmt(c.parsed.y) + " Mbps"; } } } },
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, title: { display: true, text: "Throughput (Mbps)" } } } },
    });
    const pairs = Array.from(new Set(rows.map(r => lab(r))));
    const shades = ["#9ecae1", "#4a90d9", "#1b3f8f"];
    mk("fr-jain", {
      type: "bar",
      data: { labels: pairs, datasets: bufs.map((bb, i) => ({ label: bb + "× BDP", backgroundColor: shades[i % shades.length],
        data: pairs.map(p => { const r = rows.find(q => q.buf === bb && lab(q) === p); return r ? r.jain : null; }) })) },
      options: { plugins: { legend: { labels: { usePointStyle: true, boxWidth: 9, boxHeight: 7 } } }, scales: { y: { min: 0.5, max: 1.02, title: { display: true, text: "Jain index" } }, x: { ticks: { maxRotation: 40 } } } },
    });
    let h = '<table class="tbl"><thead><tr><th>Pair</th><th>Buffer</th><th>Flow 1</th><th>Flow 2</th><th>Jain</th></tr></thead><tbody>';
    rows.forEach(r => { h += "<tr><td>" + dot(r.a1) + dot(r.a2) + lab(r) + "</td><td>" + r.buf + "×</td><td>" + fmt(r.t1) + "</td><td>" + fmt(r.t2) + "</td><td>" + fmt(r.jain, 3) + "</td></tr>"; });
    tbl.innerHTML = h + "</tbody></table>";
  }

  // ------------------------------------------------------------------ NS-3 vs Linux
  async function loadCompare() {
    const notes = $("#cp-notes"), tb = $("#cp-table");
    const mn = present("mininet"), ns = present("ns3");
    notes.innerHTML = "<p><strong>How to read this tab.</strong> The <em>Linux kernel</em> lines come from the real TCP implementations in the kernel under test (Reno, CUBIC, BBR v1), " +
      "driven through Mininet + iPerf3. The <em>NS-3</em> lines come from NS-3's own models (<code>TcpNewReno</code>, <code>TcpCubic</code>, <code>TcpBbr</code>), which are re-implementations. " +
      "Differences between them are expected and are part of the analysis.</p>";
    if (!mn || !ns) {
      killCharts(["cp-chart"]);
      empty(tb, "Both sources are needed for this comparison", "<p>" + (mn ? "" : "No Mininet results are imported yet. ") + (ns ? "" : "No NS-3 results are imported yet. ") + "Run both experiment sets (README.md), then click <em>Reload data</em>.</p>");
      return;
    }
    const d = await api("compare", { param: $("#cp-param").value, metric: $("#cp-metric").value });
    if (d.info.ns3.sample) notes.innerHTML += "<p><strong>The NS-3 side is sample data</strong> (see the banner), so this comparison is only an illustration.</p>";
    if (d.info.mininet.sample) notes.innerHTML += "<p><strong>The Mininet side is sample data.</strong></p>";
    const algos = ALGOS;
    categoryChart("cp-chart", [{ series: d.sources.mininet, dashed: false, suffix: " · Linux" }, { series: d.sources.ns3, dashed: true, suffix: " · NS-3" }], algos, d.x_label, d.y_label, false);
    const xs = new Set(); [d.sources.mininet, d.sources.ns3].forEach(s => Object.values(s).forEach(a => a.forEach(p => xs.add(p.x))));
    const cats = Array.from(xs).sort((a, b) => a - b);
    let h = '<table class="tbl left2"><thead><tr><th>' + esc(d.x_label) + "</th><th>Algorithm</th><th>Linux kernel</th><th>NS-3</th><th>NS-3 vs Linux</th></tr></thead><tbody>";
    cats.forEach(x => algos.forEach(a => {
      const m = (d.sources.mininet[a] || []).find(p => p.x === x), n = (d.sources.ns3[a] || []).find(p => p.x === x);
      if (!m && !n) return;
      const diff = m && n && m.mean ? (n.mean - m.mean) / m.mean * 100 : null;
      h += "<tr><td>" + x + "</td><td>" + dot(a) + NAMES[a] + "</td><td>" + (m ? fmt(m.mean, 2) : "–") + "</td><td>" + (n ? fmt(n.mean, 2) : "–") + "</td><td>" + (diff === null ? "–" : (diff > 0 ? "+" : "") + fmt(diff, 0) + "%") + "</td></tr>";
    }));
    tb.innerHTML = h + "</tbody></table>";
  }

  // ------------------------------------------------------------------ packets
  async function loadPackets() {
    const box = $("#pk-content");
    const d = await api("pcap");
    const rows = d.rows.filter(r => r.source === "mininet");
    const howto = '<div class="card"><h3>Open the captures in Wireshark</h3><p class="note">Captures are taken on the sender\'s interface inside Mininet (96-byte snaplen, headers only).</p>' +
      '<ul class="findings"><li>Windows Wireshark can open them from <code>\\\\wsl.localhost\\&lt;your distro&gt;\\…\\results\\pcap\\</code> (this machine: <code>' + esc(d.pcap_dir) + "</code>).</li>" +
      "<li>Useful display filters: <code>tcp.analysis.retransmission</code>, <code>tcp.analysis.fast_retransmission</code>, <code>tcp.analysis.duplicate_ack</code>, <code>tcp.analysis.ack_rtt</code>.</li>" +
      "<li>Graphs: <em>Statistics → TCP Stream Graphs → Time Sequence (tcptrace)</em>, <em>Throughput</em>, <em>Round Trip Time</em>.</li></ul></div>";
    if (!rows.length) {
      killCharts(["pk-chart"]);
      box.innerHTML = '<div class="card"><div class="empty"><h3>No packet statistics imported yet</h3><p>Capture while running the Linux-kernel experiments, compute the statistics, then reload:</p>' +
        '<pre>sudo python3 mininet/run_experiments.py --pcap\npython3 analysis/analyze_results.py --pcap-stats\n(click “Reload data”)</pre></div></div>' + howto;
      return;
    }
    box.innerHTML = '<div class="card"><h3>Retransmissions and duplicate ACKs per capture <span class="sub">tshark, sender-side capture</span></h3><div class="chart-box"><canvas id="pk-chart"></canvas></div></div>' +
      '<div class="card"><div class="table-wrap"><table class="tbl"><thead><tr><th>Capture</th><th>Packets</th><th>Retrans.</th><th>Fast retrans.</th><th>Dup ACKs</th><th>RTT mean (ms)</th><th>RTT p95 (ms)</th></tr></thead><tbody>' +
      rows.map(r => "<tr><td>" + esc(r.pcap) + "</td><td>" + r.packets + "</td><td>" + r.retransmissions + "</td><td>" + r.fast_retransmissions + "</td><td>" + r.dup_acks + "</td><td>" + fmt(r.rtt_mean_ms, 1) + "</td><td>" + fmt(r.rtt_p95_ms, 1) + "</td></tr>").join("") +
      "</tbody></table></div></div>" + howto;
    const col = r => { const a = (r.scenario || "").split("_")[0].split("-")[0]; return COLORS[a] || "#888"; };
    mk("pk-chart", { type: "bar", data: { labels: rows.map(r => r.scenario.replace(/_buf.*$/, "")),
      datasets: [{ label: "Retransmissions", data: rows.map(r => r.retransmissions), backgroundColor: rows.map(col) },
        { label: "Duplicate ACKs", data: rows.map(r => r.dup_acks), backgroundColor: rows.map(r => hexA(col(r).length === 7 ? col(r) : "#888888", 0.4)) }] },
      options: { plugins: { legend: { labels: { usePointStyle: true, boxWidth: 9, boxHeight: 7 } } }, scales: { x: { ticks: { maxRotation: 70, autoSkip: true } }, y: { beginAtZero: true } } } });
  }

  // ------------------------------------------------------------------ what-if
  function readWhatIf() {
    const g = id => parseFloat($("#" + id).value);
    const p = { bw: g("wi-bw"), rtt: g("wi-rtt"), loss: g("wi-loss"), buf: g("wi-buf"), dur: g("wi-dur") };
    $("#wi-bw-o").textContent = p.bw + " Mbps";
    $("#wi-rtt-o").textContent = p.rtt + " ms";
    $("#wi-loss-o").textContent = p.loss + " %";
    $("#wi-buf-o").textContent = p.buf + "× BDP";
    $("#wi-dur-o").textContent = p.dur + " s";
    return p;
  }
  async function loadWhatIf() {
    const p = readWhatIf();
    const res = {};
    ALGOS.forEach(a => { res[a] = WhatIf.simulate(a, p); });
    const ds = key => ALGOS.map(a => ({ label: NAMES[a], data: res[a].t.map((t, i) => ({ x: t, y: res[a][key][i] })), parsing: false,
      borderColor: COLORS[a], backgroundColor: COLORS[a], borderWidth: 2, pointRadius: 0, tension: 0.1 }));
    const scales = (yMax) => ({ x: { type: "linear", min: 0, max: p.dur, title: { display: true, text: "Time (s)" } }, y: { beginAtZero: true, max: yMax } });
    const common = { animation: false, interaction: { mode: "nearest", intersect: false }, plugins: { legend: { labels: { usePointStyle: true, boxWidth: 9, boxHeight: 7 } } } };
    mk("wi-thr", { type: "line", data: { datasets: ds("thr") }, options: Object.assign({ scales: scales(Math.ceil(p.bw * 1.1 / 5) * 5) }, common) });
    const cwAll = [].concat.apply([], ALGOS.map(a => res[a].cwnd));
    mk("wi-cwnd", { type: "line", data: { datasets: ds("cwnd") }, options: Object.assign({ scales: scales(Math.max(10, Math.ceil(percentile(cwAll, 0.98) * 1.25 / 10) * 10)) }, common) });
    mk("wi-q", { type: "line", data: { datasets: ds("qdelay") }, options: Object.assign({ scales: scales(undefined) }, common) });
    $("#wi-tiles").innerHTML = ALGOS.map(a => '<div class="tile"><div class="n">' + dot(a) + NAMES[a] + '</div><div class="m">avg goodput <strong>' + fmt(res[a].avgThr) + " Mbps</strong> (" + fmt(res[a].util * 100, 0) +
      "% of link) · avg queueing delay " + fmt(res[a].avgQdelay, 0) + " ms</div></div>").join("");
  }

  // ------------------------------------------------------------------ about
  async function loadAbout() {
    const box = $("#about-content");
    const kv = o => "<dl class=\"kv\">" + Object.keys(o).map(k => o[k] === null || o[k] === undefined || o[k] === "" ? "" : "<dt>" + esc(k) + "</dt><dd>" + esc(o[k]) + "</dd>").join("") + "</dl>";
    let h = "";
    SRC_ORDER.forEach(s => {
      const i = sourceInfo(s);
      h += '<div class="card"><h2>' + esc(SRC_LABEL[s]) + (i.present ? (i.sample ? '<span class="badge">sample data</span>' : '<span class="badge ok">your data</span>') : '<span class="badge">not imported</span>') + "</h2>";
      if (!i.present) { h += "<p class=\"note\">No results imported for this source yet.</p></div>"; return; }
      const e = i.env || {};
      h += kv({ "TCP implementations": e.tcp_models, "NS-3 version": e.ns3_version, "Run length (s)": e.duration_s, "Repetitions": e.runs, "OS": e.os, "Kernel": e.kernel,
        "Python": e.python, "Generated": e.generated, "Note": e.note, "Rows / scenarios": i.rows + " / " + i.scenarios });
      if (e.tools) h += "<h3 style=\"margin-top:14px\">Tool versions</h3>" + kv(e.tools);
      h += "</div>";
    });
    h += '<div class="card"><h2>Method in short</h2><ul class="findings">' +
      "<li><strong>Topology:</strong> senders → router → bottleneck → receiver (dumbbell). RTT is set on the access links, bandwidth, random loss and buffer on the bottleneck.</li>" +
      "<li><strong>Scenarios:</strong> one factor at a time around 50 Mbps / 50 ms / 0 % loss / 1× BDP buffer, plus two competing flows at three buffer sizes.</li>" +
      "<li><strong>Linux kernel:</strong> Mininet + iPerf3 (<code>-C reno|cubic|bbr</code>), cwnd and RTT sampled with <code>ss -ti</code>, optional tcpdump captures analysed with tshark.</li>" +
      "<li><strong>NS-3:</strong> same topology and scenarios; NS-3's own TCP models; cwnd and RTT from trace sources.</li>" +
      "<li><strong>Fairness:</strong> Jain's index (Σx)² / (n·Σx²) over the two flows' throughput.</li></ul></div>";
    box.innerHTML = h;
  }

  // ------------------------------------------------------------------ boot
  async function refreshMeta() {
    state.meta = await api("meta");
    if (!present(state.source)) state.source = present("mininet") ? "mininet" : (present("ns3") ? "ns3" : "mininet");
    renderSourceSwitch();
    renderBanner();
  }
  async function init() {
    initTheme();
    $$(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));
    $$("#source-switch button").forEach(b => b.addEventListener("click", () => {
      if (b.disabled) return;
      state.source = b.dataset.src; renderSourceSwitch(); $("#rp-run").innerHTML = ""; renderTab(state.tab);
    }));
    $("#reload-btn").addEventListener("click", async () => {
      const btn = $("#reload-btn"); btn.disabled = true; btn.textContent = "Reloading…";
      try { await api("reload", {}, { method: "POST" }); await refreshMeta(); renderTab(state.tab); }
      finally { btn.disabled = false; btn.textContent = "Reload data"; }
    });
    ["sw-param", "sw-metric"].forEach(id => $("#" + id).addEventListener("change", loadSweeps));
    ["cp-param", "cp-metric"].forEach(id => $("#" + id).addEventListener("change", loadCompare));
    $("#fr-buf").addEventListener("change", loadFairness);
    $("#rp-scenario").addEventListener("change", () => { $("#rp-run").innerHTML = ""; loadReplayData(); });
    $("#rp-run").addEventListener("change", loadReplayData);
    $("#rp-play").addEventListener("click", toggleReplay);
    $("#rp-scrub").addEventListener("input", e => { const r = state.replay; if (!r) return; setReplayTime(parseInt(e.target.value, 10) / 1000 * r.dur); r.particles = {}; drawPipe(0); });
    ["wi-bw", "wi-rtt", "wi-loss", "wi-buf", "wi-dur"].forEach(id => $("#" + id).addEventListener("input", () => {
      readWhatIf(); clearTimeout(state.whatifTimer); state.whatifTimer = setTimeout(loadWhatIf, 60);
    }));
    window.addEventListener("resize", () => { if (state.tab === "replay") drawPipe(0); });
    try { await refreshMeta(); } catch (e) { console.error(e); $("#banner").hidden = false; $("#banner").textContent = "Could not reach the dashboard API."; return; }
    renderTab("overview");
  }
  document.addEventListener("DOMContentLoaded", init);
})();
