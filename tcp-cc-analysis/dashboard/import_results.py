#!/usr/bin/env python3
"""
import_results.py - load experiment result folders into the dashboard's SQLite database.

  python3 dashboard/import_results.py --mininet results --ns3 results_ns3
  python3 dashboard/import_results.py --ns3 data/sample_ns3          # sample data shipped with the project

Re-importing a source replaces that source's rows (idempotent). Folders are the ones written by
mininet/run_experiments.py and ns3/run_ns3_matrix.py (summary.csv, timeseries/, pcap_stats.csv,
environment.json).
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

DEFAULT_DB = os.path.join(ROOT, "data", "tcpcc.db")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def import_source(conn, source, folder):
    """Replace all rows of `source` with the contents of `folder`. Returns a small stats dict."""
    summary = os.path.join(folder, "summary.csv")
    if not os.path.exists(summary):
        raise FileNotFoundError("no summary.csv in %s" % folder)
    cur = conn.cursor()
    for table in ("meta", "runs", "timeseries", "pcap_stats"):
        cur.execute("DELETE FROM %s WHERE source = ?" % table, (source,))

    with open(summary, newline="") as f:
        rows = [(source, r["scenario"], r["group"], int(r["run"]), int(r["flow"]), r["algo"],
                 int(r["n_flows"]), _f(r["bw_mbps"]), _f(r["rtt_ms"]), _f(r["loss_pct"]), _f(r["buf_bdp"]),
                 _f(r["throughput_mbps"]), _f(r["retransmits"]), _f(r["mean_rtt_ms"]),
                 _f(r["min_rtt_ms"]), _f(r["max_rtt_ms"])) for r in csv.DictReader(f)]
    cur.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    n_ts = 0
    for path in sorted(glob.glob(os.path.join(folder, "timeseries", "*.csv"))):
        m = re.match(r"(.+)_run(\d+)\.csv$", os.path.basename(path))
        if not m:
            continue
        sid, run = m.group(1), int(m.group(2))
        with open(path, newline="") as f:
            batch = [(source, sid, run, int(r["flow"]), r["algo"], _f(r["t"]), _f(r["cwnd"]),
                      _f(r.get("rtt_ms")), _f(r.get("retrans")), _f(r.get("delivery_mbps")))
                     for r in csv.DictReader(f)]
        cur.executemany("INSERT INTO timeseries VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        n_ts += len(batch)

    n_pcap = 0
    pcap_csv = os.path.join(folder, "pcap_stats.csv")
    if os.path.exists(pcap_csv):
        with open(pcap_csv, newline="") as f:
            batch = [(source, r.get("pcap"), r.get("scenario"), int(r.get("run") or 1),
                      int(float(r.get("packets") or 0)), int(float(r.get("retransmissions") or 0)),
                      int(float(r.get("fast_retransmissions") or 0)), int(float(r.get("dup_acks") or 0)),
                      _f(r.get("rtt_mean_ms")), _f(r.get("rtt_p95_ms"))) for r in csv.DictReader(f)]
        cur.executemany("INSERT INTO pcap_stats VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
        n_pcap = len(batch)

    env = {}
    env_path = os.path.join(folder, "environment.json")
    if os.path.exists(env_path):
        with open(env_path) as f:
            env = json.load(f)
    cur.execute("INSERT INTO meta VALUES (?,?,?)", (source, "environment", json.dumps(env)))
    cur.execute("INSERT INTO meta VALUES (?,?,?)", (source, "folder", os.path.abspath(folder)))
    conn.commit()
    return dict(source=source, runs=len(rows), timeseries=n_ts, pcap=n_pcap, sample=bool(env.get("sample")))


def auto_import(conn, root=ROOT):
    """Import every result folder that exists. Real results win over the shipped sample."""
    done = []
    mn = os.path.join(root, "results")
    if os.path.exists(os.path.join(mn, "summary.csv")):
        done.append(import_source(conn, "mininet", mn))
    ns_real = os.path.join(root, "results_ns3")
    ns_sample = os.path.join(root, "data", "sample_ns3")
    if os.path.exists(os.path.join(ns_real, "summary.csv")):
        done.append(import_source(conn, "ns3", ns_real))
    elif os.path.exists(os.path.join(ns_sample, "summary.csv")):
        done.append(import_source(conn, "ns3", ns_sample))
    return done


def main():
    ap = argparse.ArgumentParser(description="Import results into the dashboard database")
    ap.add_argument("--mininet", default="", help="Mininet results folder (e.g. results)")
    ap.add_argument("--ns3", default="", help="NS-3 results folder (e.g. results_ns3)")
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    if not args.mininet and not args.ns3:
        ap.error("give --mininet and/or --ns3")
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    conn = db.connect(args.db)
    for source, folder in (("mininet", args.mininet), ("ns3", args.ns3)):
        if folder:
            try:
                print("imported:", import_source(conn, source, folder))
            except FileNotFoundError as ex:
                print("skipped %s: %s" % (source, ex))
    conn.close()
    print("database:", args.db)


if __name__ == "__main__":
    main()
