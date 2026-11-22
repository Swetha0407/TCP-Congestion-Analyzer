#!/usr/bin/env python3
"""
app.py - Flask dashboard for the TCP congestion control results (SQLite + Chart.js, fully offline).

  python3 dashboard/app.py                 # http://localhost:5000  (also reachable from Windows in WSL2)
  python3 dashboard/app.py --port 8080
  python3 dashboard/app.py --reimport      # rebuild the database from results/ and results_ns3/ first

Data comes from data/tcpcc.db, built from the result folders by dashboard/import_results.py.
"""
import argparse
import json
import os
import statistics
import sys

from flask import Flask, jsonify, render_template, request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import db  # noqa: E402
import import_results  # noqa: E402
from common.scenarios import ALGOS, BASE  # noqa: E402

DB_PATH = os.environ.get("TCPCC_DB", os.path.join(ROOT, "data", "tcpcc.db"))
SOURCES = ("mininet", "ns3")

# whitelists: values go into SQL text, so only these literal names are ever used
PARAMS = {
    "loss": ("loss_pct", "Random loss (%)", BASE["loss"]),
    "rtt": ("rtt_ms", "RTT (ms)", BASE["rtt"]),
    "bw": ("bw_mbps", "Bottleneck bandwidth (Mbps)", BASE["bw"]),
    "buf": ("buf_bdp", "Buffer size (x BDP)", BASE["buf"]),
}
METRICS = {
    "throughput_mbps": "Throughput (Mbps)",
    "mean_rtt_ms": "Mean RTT (ms)",
    "retransmits": "Retransmissions",
}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def conn():
    return db.connect(DB_PATH)


def ensure_db(force=False):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    c = conn()
    have = c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    if have == 0 or force:
        done = import_results.auto_import(c)
        print("database built:", done if done else "no result folders found yet")
    c.close()


def source_arg():
    s = request.args.get("source", "mininet")
    return s if s in SOURCES else "mininet"


def mean_std(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    return statistics.fmean(vals), (statistics.pstdev(vals) if len(vals) > 1 else 0.0)


def sweep_series(c, source, param, metric):
    col, xlabel, _ = PARAMS[param]
    where = ["source = ?", "n_flows = 1"]
    for k, (kcol, _, base) in PARAMS.items():
        if k != param:
            where.append("ABS(%s - %r) < 1e-9" % (kcol, float(base)))
    rows = c.execute("SELECT %s AS x, algo, %s AS v FROM runs WHERE %s" % (col, metric, " AND ".join(where)),
                     (source,)).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault((r["algo"], r["x"]), []).append(r["v"])
    series = {}
    for (algo, x), vals in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        m, s = mean_std(vals)
        series.setdefault(algo, []).append({"x": x, "mean": m, "std": s, "n": len(vals)})
    return {"param": param, "metric": metric, "x_label": xlabel, "y_label": METRICS[metric], "series": series}


def source_info(c, source):
    n = c.execute("SELECT COUNT(*) FROM runs WHERE source = ?", (source,)).fetchone()[0]
    env_row = c.execute("SELECT value FROM meta WHERE source = ? AND key = 'environment'", (source,)).fetchone()
    env = json.loads(env_row["value"]) if env_row else {}
    scn = c.execute("SELECT COUNT(DISTINCT scenario) FROM runs WHERE source = ?", (source,)).fetchone()[0]
    nruns = c.execute("SELECT COUNT(DISTINCT scenario || '#' || run) FROM runs WHERE source = ?", (source,)).fetchone()[0]
    algos = [r[0] for r in c.execute("SELECT DISTINCT algo FROM runs WHERE source = ? ORDER BY algo", (source,))]
    pc = c.execute("SELECT COUNT(*) FROM pcap_stats WHERE source = ?", (source,)).fetchone()[0]
    ts = c.execute("SELECT COUNT(*) FROM timeseries WHERE source = ?", (source,)).fetchone()[0]
    return {"present": n > 0, "rows": n, "scenarios": scn, "runs": nruns, "algos": algos,
            "pcap_rows": pc, "timeseries_rows": ts, "env": env, "sample": bool(env.get("sample"))}


# ----------------------------------------------------------------------------- routes
@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def api_meta():
    c = conn()
    out = {"sources": {s: source_info(c, s) for s in SOURCES}, "algos": ALGOS,
           "params": {k: {"label": v[1], "base": v[2]} for k, v in PARAMS.items()},
           "metrics": METRICS, "base": BASE}
    c.close()
    return jsonify(out)


@app.get("/api/sweep")
def api_sweep():
    param = request.args.get("param", "loss")
    metric = request.args.get("metric", "throughput_mbps")
    if param not in PARAMS or metric not in METRICS:
        return jsonify({"error": "bad param or metric"}), 400
    c = conn()
    out = sweep_series(c, source_arg(), param, metric)
    c.close()
    return jsonify(out)


@app.get("/api/compare")
def api_compare():
    param = request.args.get("param", "loss")
    metric = request.args.get("metric", "throughput_mbps")
    if param not in PARAMS or metric not in METRICS:
        return jsonify({"error": "bad param or metric"}), 400
    c = conn()
    out = {"param": param, "metric": metric, "x_label": PARAMS[param][1], "y_label": METRICS[metric],
           "sources": {s: sweep_series(c, s, param, metric)["series"] for s in SOURCES},
           "info": {s: {"present": source_info(c, s)["present"], "sample": source_info(c, s)["sample"]} for s in SOURCES}}
    c.close()
    return jsonify(out)


@app.get("/api/scenarios")
def api_scenarios():
    c = conn()
    rows = c.execute(
        "SELECT scenario, grp, n_flows, bw_mbps, rtt_ms, loss_pct, buf_bdp, "
        "GROUP_CONCAT(DISTINCT algo) AS algos, COUNT(DISTINCT run) AS runs "
        "FROM runs WHERE source = ? GROUP BY scenario, grp, n_flows, bw_mbps, rtt_ms, loss_pct, buf_bdp "
        "ORDER BY grp, scenario", (source_arg(),)).fetchall()
    ts = {r["scenario"] for r in c.execute("SELECT DISTINCT scenario FROM timeseries WHERE source = ?", (source_arg(),))}
    c.close()
    return jsonify([dict(r, has_timeseries=r["scenario"] in ts) for r in rows])


@app.get("/api/timeseries")
def api_timeseries():
    scenario = request.args.get("scenario", "")
    run = request.args.get("run", type=int)
    c = conn()
    runs = [r[0] for r in c.execute(
        "SELECT DISTINCT run FROM timeseries WHERE source = ? AND scenario = ? ORDER BY run", (source_arg(), scenario))]
    if not runs:
        c.close()
        return jsonify({"scenario": scenario, "runs": [], "flows": {}})
    run = run if run in runs else runs[0]
    rows = c.execute("SELECT flow, algo, t, cwnd, rtt_ms, delivery_mbps FROM timeseries "
                     "WHERE source = ? AND scenario = ? AND run = ? ORDER BY flow, t",
                     (source_arg(), scenario, run)).fetchall()
    info = c.execute("SELECT bw_mbps, rtt_ms, loss_pct, buf_bdp, n_flows FROM runs WHERE source = ? AND scenario = ? LIMIT 1",
                     (source_arg(), scenario)).fetchone()
    c.close()
    flows = {}
    for r in rows:
        f = flows.setdefault(str(r["flow"]), {"algo": r["algo"], "t": [], "cwnd": [], "rtt_ms": [], "delivery_mbps": []})
        f["t"].append(r["t"])
        f["cwnd"].append(r["cwnd"])
        f["rtt_ms"].append(r["rtt_ms"])
        f["delivery_mbps"].append(r["delivery_mbps"])
    return jsonify({"scenario": scenario, "run": run, "runs": runs, "flows": flows,
                    "link": dict(info) if info else {}})


@app.get("/api/fairness")
def api_fairness():
    c = conn()
    rows = c.execute("SELECT scenario, run, flow, algo, buf_bdp, throughput_mbps FROM runs "
                     "WHERE source = ? AND n_flows = 2 ORDER BY scenario, run, flow", (source_arg(),)).fetchall()
    c.close()
    by_run = {}
    for r in rows:
        by_run.setdefault((r["scenario"], r["run"]), []).append(r)
    agg = {}
    for (sid, run), fl in by_run.items():
        if len(fl) < 2:
            continue
        t1, t2 = fl[0]["throughput_mbps"], fl[1]["throughput_mbps"]
        denom = 2 * (t1 ** 2 + t2 ** 2)
        key = (fl[0]["algo"], fl[1]["algo"], fl[0]["buf_bdp"])
        agg.setdefault(key, []).append((t1, t2, (t1 + t2) ** 2 / denom if denom else None))
    out = []
    for (a1, a2, buf), vals in sorted(agg.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
        out.append({"a1": a1, "a2": a2, "buf": buf, "runs": len(vals),
                    "t1": statistics.fmean(v[0] for v in vals), "t2": statistics.fmean(v[1] for v in vals),
                    "jain": statistics.fmean(v[2] for v in vals if v[2] is not None)})
    return jsonify(out)


@app.get("/api/pcap")
def api_pcap():
    c = conn()
    rows = c.execute("SELECT source, pcap, scenario, run, packets, retransmissions, fast_retransmissions, dup_acks, "
                     "rtt_mean_ms, rtt_p95_ms FROM pcap_stats ORDER BY source, scenario, run").fetchall()
    folder = c.execute("SELECT value FROM meta WHERE source = 'mininet' AND key = 'folder'").fetchone()
    c.close()
    return jsonify({"rows": [dict(r) for r in rows],
                    "pcap_dir": os.path.join(folder["value"], "pcap") if folder else os.path.join(ROOT, "results", "pcap")})


@app.post("/api/reload")
def api_reload():
    c = conn()
    done = import_results.auto_import(c)
    c.close()
    return jsonify({"imported": done})


def main():
    ap = argparse.ArgumentParser(description="TCP congestion control dashboard")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--reimport", action="store_true", help="rebuild the database from the result folders first")
    args = ap.parse_args()
    ensure_db(force=args.reimport)
    print("Dashboard: http://localhost:%d   (Ctrl+C to stop)" % args.port)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
