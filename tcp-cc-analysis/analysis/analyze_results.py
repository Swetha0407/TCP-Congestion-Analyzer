#!/usr/bin/env python3
"""
analyze_results.py - turn a results folder (Mininet or NS-3) into graphs, tables and a report.

Usage (Ubuntu/WSL2 terminal, no sudo needed):
  python3 analysis/analyze_results.py                                # graphs + aggregated.csv + report.md for results/
  python3 analysis/analyze_results.py --results results_ns3          # same for the NS-3 results
  python3 analysis/analyze_results.py --compare-ns3 results_ns3      # + NS-3 vs Mininet graphs and table
  python3 analysis/analyze_results.py --pcap-stats                   # + tshark statistics for results/pcap/*.pcap
  python3 analysis/analyze_results.py --export-json                  # + results/dashboard_data.json (flat export)

Outputs inside --results:
  graphs/*.png, aggregated.csv, report.md, compare_ns3_vs_mininet.csv, pcap_stats.csv
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common.scenarios import BASE as SC_BASE  # noqa: E402

BASE = dict(bw_mbps=SC_BASE["bw"], rtt_ms=SC_BASE["rtt"], loss_pct=SC_BASE["loss"], buf_bdp=SC_BASE["buf"])
PARAMS = {
    "loss": ("loss_pct", "Random loss (%)"),
    "rtt": ("rtt_ms", "RTT (ms)"),
    "bw": ("bw_mbps", "Bottleneck bandwidth (Mbps)"),
    "buf": ("buf_bdp", "Buffer size (x BDP)"),
}
METRICS = {
    "throughput_mbps": "Throughput (Mbps)",
    "mean_rtt_ms": "Mean RTT (ms)",
    "retransmits": "Retransmissions",
}
COMPARE_METRICS = {k: METRICS[k] for k in ("throughput_mbps", "mean_rtt_ms")}
COLORS = {"reno": "#d95f02", "cubic": "#1b9e77", "bbr": "#7570b3"}
plt.rcParams.update({"axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 110})


# ----------------------------------------------------------------------------- helpers
def single_flow_baseline(df, col):
    """Single-flow rows with every parameter except `col` at its baseline value."""
    d = df[df.n_flows == 1]
    for k, v in BASE.items():
        if k != col:
            d = d[np.isclose(d[k], v)]
    return d


def load_env(results):
    try:
        with open(os.path.join(results, "environment.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ----------------------------------------------------------------------------- plots
def sweep_plot(df, param, metric, path):
    col, xlabel = PARAMS[param]
    d = single_flow_baseline(df, col)
    if d.empty:
        return False
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for algo, g in d.groupby("algo"):
        agg = g.groupby(col)[metric].agg(["mean", "std"]).fillna(0).sort_index()
        ax.errorbar(agg.index, agg["mean"], yerr=agg["std"], marker="o", capsize=3,
                    label=algo.upper(), color=COLORS.get(algo))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(METRICS[metric])
    ax.set_title("%s vs %s" % (METRICS[metric], xlabel))
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


def fairness_table(df):
    """Per (pair, buffer): mean throughput of both flows and Jain's fairness index."""
    f = df[df.n_flows == 2]
    rows = []
    for (sid, run), g in f.groupby(["scenario", "run"]):
        g = g.sort_values("flow")
        if len(g) < 2:
            continue
        t = g.throughput_mbps.values.astype(float)
        denom = 2 * (t ** 2).sum()
        rows.append(dict(pair=" vs ".join(g.algo.str.upper()), buf=float(g.buf_bdp.iloc[0]),
                         a1=g.algo.iloc[0], a2=g.algo.iloc[1], t1=t[0], t2=t[1],
                         jain=(t.sum() ** 2) / denom if denom else np.nan))
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).groupby(["pair", "buf", "a1", "a2"], as_index=False).mean(numeric_only=True)


def fairness_plots(df, outdir):
    r = fairness_table(df)
    if r.empty:
        return False
    piv = r.pivot(index="pair", columns="buf", values="jain")
    fig, ax = plt.subplots(figsize=(8, 4))
    piv.plot.bar(ax=ax)
    ax.set_ylim(0.5, 1.05)
    ax.set_ylabel("Jain's fairness index")
    ax.set_xlabel("")
    ax.set_title("Fairness of two competing flows")
    ax.legend(title="Buffer (x BDP)")
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fairness_jain.png"), dpi=160)
    plt.close(fig)

    bufs = sorted(r.buf.unique())
    fig, axes = plt.subplots(1, len(bufs), figsize=(5 * len(bufs), 4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, b in zip(axes, bufs):
        d = r[r.buf == b].reset_index(drop=True)
        x = np.arange(len(d))
        ax.bar(x, d.t1, color=[COLORS[a] for a in d.a1])
        ax.bar(x, d.t2, bottom=d.t1, color=[COLORS[a] for a in d.a2], hatch="//", edgecolor="white")
        ax.set_xticks(x)
        ax.set_xticklabels(d.pair, rotation=30, ha="right")
        ax.set_title("Buffer = %g x BDP" % b)
    axes[0].set_ylabel("Throughput (Mbps)\nsolid = flow 1, hatched = flow 2")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "fairness_share.png"), dpi=160)
    plt.close(fig)
    return True


def ts_plot(ts_dir, loss, path):
    """cwnd / RTT / delivery rate of the three algorithms in the baseline scenario."""
    fields = [("cwnd", "cwnd (segments)"), ("rtt_ms", "RTT (ms)"), ("delivery_mbps", "Delivery rate (Mbps)")]
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    found, clipped = False, False
    cw_all = []
    for algo in ("reno", "cubic", "bbr"):
        p = os.path.join(ts_dir, "%s_bw50_rtt50_loss%g_buf1_run1.csv" % (algo, loss))
        if not os.path.exists(p):
            continue
        d = pd.read_csv(p)
        found = True
        cw_all.extend(d["cwnd"].tolist())
        for ax, (c, lab) in zip(axes, fields):
            ax.plot(d["t"], d[c], label=algo.upper(), color=COLORS[algo], lw=1.4)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel(lab)
    if not found:
        plt.close(fig)
        return False
    # a single start-up transient (NS-3 BBR reports an extreme initial cwnd) must not flatten the plot
    top = np.percentile(cw_all, 98) * 1.3
    if max(cw_all) > top:
        axes[0].set_ylim(0, top)
        clipped = True
    axes[0].legend()
    title = "Single flow, 50 Mbps, 50 ms RTT, %g%% loss, 1 x BDP buffer" % loss
    if clipped:
        title += "  (cwnd axis clipped at the 98th percentile x 1.3)"
    fig.suptitle(title, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return True


# ----------------------------------------------------------------------------- NS-3 vs Mininet
def compare_plots(mn, ns, outdir):
    """One figure per (parameter, metric): solid = Mininet (Linux kernel), dashed = NS-3 models."""
    made = 0
    for param, (col, xlabel) in PARAMS.items():
        dm, dn = single_flow_baseline(mn, col), single_flow_baseline(ns, col)
        if dm.empty or dn.empty:
            continue
        for metric, ylabel in COMPARE_METRICS.items():
            fig, ax = plt.subplots(figsize=(7, 4.2))
            for algo in ("reno", "cubic", "bbr"):
                for d, style, tag in ((dm, "-", "Linux kernel (Mininet)"), (dn, "--", "NS-3 model")):
                    g = d[d.algo == algo]
                    if g.empty:
                        continue
                    agg = g.groupby(col)[metric].agg(["mean", "std"]).fillna(0).sort_index()
                    ax.errorbar(agg.index, agg["mean"], yerr=agg["std"], ls=style,
                                marker="o" if style == "-" else "s", capsize=3, color=COLORS[algo],
                                alpha=0.9, label="%s (%s)" % (algo.upper(), tag))
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.set_title("NS-3 vs Mininet: %s vs %s" % (ylabel, xlabel))
            ax.legend(fontsize=7, ncol=2)
            fig.tight_layout()
            fig.savefig(os.path.join(outdir, "compare_%s_vs_%s.png" % (metric, param)), dpi=160)
            plt.close(fig)
            made += 1
    print("comparison graphs: %d saved in %s" % (made, outdir))


def compare_table(mn, ns, out_csv):
    keys = ["scenario", "algo", "bw_mbps", "rtt_ms", "loss_pct", "buf_bdp"]
    a = mn[mn.n_flows == 1].groupby(keys)[["throughput_mbps", "mean_rtt_ms"]].mean().reset_index()
    b = ns[ns.n_flows == 1].groupby(keys)[["throughput_mbps", "mean_rtt_ms"]].mean().reset_index()
    m = a.merge(b, on=keys, suffixes=("_mininet", "_ns3"))
    if m.empty:
        print("no matching scenarios between the two result sets - skipping comparison table")
        return None
    m["throughput_diff_pct"] = ((m.throughput_mbps_ns3 - m.throughput_mbps_mininet)
                                / m.throughput_mbps_mininet.replace(0, np.nan) * 100)
    m["rtt_diff_pct"] = ((m.mean_rtt_ms_ns3 - m.mean_rtt_ms_mininet)
                         / m.mean_rtt_ms_mininet.replace(0, np.nan) * 100)
    m = m.round(2).sort_values(["algo", "loss_pct", "rtt_ms", "bw_mbps", "buf_bdp"])
    m.to_csv(out_csv, index=False)
    print("wrote", out_csv, "(%d matching scenarios)" % len(m))
    print("median |throughput difference| NS-3 vs Mininet: %.1f%%" % m.throughput_diff_pct.abs().median())
    return m


# ----------------------------------------------------------------------------- tshark
def pcap_stats(pcap_dir, out_csv):
    """One tshark pass per capture: count retransmissions, fast retransmissions, dup ACKs, RTT stats."""
    rows = []
    files = sorted(glob.glob(os.path.join(pcap_dir, "*.pcap")))
    if not files:
        print("no pcap files found in", pcap_dir, "(run the Mininet runner with --pcap)")
        return None
    for p in files:
        cmd = ["tshark", "-n", "-r", p, "-T", "fields",
               "-e", "tcp.analysis.retransmission", "-e", "tcp.analysis.fast_retransmission",
               "-e", "tcp.analysis.duplicate_ack", "-e", "tcp.analysis.ack_rtt"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            sys.exit("tshark not found - install it with:  sudo apt install tshark")
        if r.returncode != 0:
            print("  tshark failed on %s: %s" % (os.path.basename(p), r.stderr.strip()[:200]))
            continue
        retr = fast = dup = pk = 0
        rtts = []
        for line in r.stdout.splitlines():
            pk += 1
            f = line.split("\t") + ["", "", "", ""]
            retr += bool(f[0])
            fast += bool(f[1])
            dup += bool(f[2])
            if f[3]:
                try:
                    rtts.append(float(f[3]) * 1000.0)
                except ValueError:
                    pass
        name = os.path.basename(p)[:-5]
        m = re.match(r"(.+)_run(\d+)$", name)
        rows.append(dict(pcap=os.path.basename(p), scenario=m.group(1) if m else name,
                         run=int(m.group(2)) if m else 1, packets=pk, retransmissions=retr,
                         fast_retransmissions=fast, dup_acks=dup,
                         rtt_mean_ms=round(float(np.mean(rtts)), 2) if rtts else None,
                         rtt_p95_ms=round(float(np.percentile(rtts, 95)), 2) if rtts else None))
        print("  tshark:", rows[-1])
    if rows:
        pd.DataFrame(rows).to_csv(out_csv, index=False)
        print("wrote", out_csv)
    return rows


# ----------------------------------------------------------------------------- report
def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def write_report(df, results, cmp_table, path):
    env = load_env(results)
    src = env.get("source", os.path.basename(os.path.abspath(results)))
    L = ["# TCP congestion control comparison - report data", "",
         "Generated %s from `%s` (source: **%s**)." % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), results, src),
         "", "> Statements under *Automatic observations* are computed from the data in this folder. "
         "Check them against the graphs before quoting them.", ""]
    if env.get("sample"):
        L += ["> **SAMPLE DATA**: %s" % env.get("note", "this result set is a sample."), ""]
    L += ["## Setup", ""]
    rows = [("Source", src), ("TCP implementations", env.get("tcp_models", "?")),
            ("Kernel", env.get("kernel", "?")), ("OS", env.get("os", "?")),
            ("NS-3", env.get("ns3_version", "-")), ("Run length (s)", env.get("duration_s", "?")),
            ("Repetitions", env.get("runs", "?"))]
    for k, v in (env.get("tools") or {}).items():
        if v:
            rows.append((k, v))
    L += [md_table(["Item", "Value"], rows), ""]
    L += ["Rows analysed: %d (%d scenarios, %d algorithms)." % (len(df), df.scenario.nunique(), df.algo.nunique()), ""]

    obs = []
    for param, (col, xlabel) in PARAMS.items():
        d = single_flow_baseline(df, col)
        if d.empty:
            continue
        L += ["## Throughput vs %s (single flow, other parameters at baseline)" % xlabel, ""]
        algos = sorted(d.algo.unique())
        agg = d.groupby([col, "algo"])["throughput_mbps"].agg(["mean", "std"]).fillna(0)
        trows = []
        for x in sorted(d[col].unique()):
            cells = []
            best, best_v = None, -1
            for a in algos:
                if (x, a) in agg.index:
                    mval, sval = float(agg.loc[(x, a), "mean"]), float(agg.loc[(x, a), "std"])
                    cells.append("%.1f +/- %.1f" % (mval, sval))
                    if mval > best_v:
                        best, best_v = a, mval
                else:
                    cells.append("-")
            trows.append(["%g" % x] + cells + [best.upper() if best else "-"])
        L += [md_table([xlabel] + [a.upper() + " (Mbps)" for a in algos] + ["Highest"], trows), ""]
        if param == "loss" and len(algos) >= 2:
            for x in sorted(d[col].unique()):
                if x <= 0:
                    continue
                vals = {a: float(agg.loc[(x, a), "mean"]) for a in algos if (x, a) in agg.index}
                if len(vals) >= 2:
                    hi, lo = max(vals, key=vals.get), min(vals, key=vals.get)
                    if vals[lo] > 0:
                        obs.append("At %g%% random loss %s reached %.1f Mbps, %.1fx the %.1f Mbps of %s."
                                   % (x, hi.upper(), vals[hi], vals[hi] / vals[lo], vals[lo], lo.upper()))
        if param == "buf":
            rt = d.groupby([col, "algo"])["mean_rtt_ms"].mean()
            big = max(d[col].unique())
            parts = ["%s %.0f ms" % (a.upper(), rt.loc[(big, a)]) for a in algos if (big, a) in rt.index]
            if parts:
                obs.append("Mean RTT with the largest buffer (%g x BDP): %s (base propagation RTT %g ms)."
                           % (big, ", ".join(parts), SC_BASE["rtt"]))
    fr = fairness_table(df)
    if not fr.empty:
        L += ["## Fairness of two competing flows (mean over runs)", ""]
        L += [md_table(["Pair", "Buffer (x BDP)", "Flow 1 (Mbps)", "Flow 2 (Mbps)", "Jain index"],
                       [[r.pair, "%g" % r.buf, "%.1f" % r.t1, "%.1f" % r.t2, "%.3f" % r.jain]
                        for r in fr.sort_values(["pair", "buf"]).itertuples()]), ""]
        worst = fr.loc[fr.jain.idxmin()]
        obs.append("Least fair pairing: %s at %g x BDP buffer (Jain index %.3f, %.1f vs %.1f Mbps)."
                   % (worst.pair, worst.buf, worst.jain, worst.t1, worst.t2))
    if cmp_table is not None and len(cmp_table):
        obs.append("Median |throughput difference| between NS-3 models and the Linux kernel over %d matching "
                   "scenarios: %.1f%%." % (len(cmp_table), cmp_table.throughput_diff_pct.abs().median()))
    L += ["## Automatic observations", ""] + (["- " + o for o in obs] or ["- (not enough data yet)"]) + [""]
    L += ["## Figures", ""] + ["- `graphs/%s`" % os.path.basename(g)
                              for g in sorted(glob.glob(os.path.join(results, "graphs", "*.png")))] + [""]
    with open(path, "w") as f:
        f.write("\n".join(L))
    print("wrote", path)


# ----------------------------------------------------------------------------- flat JSON export
def export_json(df, ts_dir, path):
    data = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "scenarios": []}
    for sid, g in df.groupby("scenario"):
        first = g.iloc[0]
        flows = []
        for (flow, algo), gg in g.groupby(["flow", "algo"]):
            flows.append(dict(
                flow=int(flow), algo=algo, runs=int(gg.run.nunique()),
                throughput_mean=round(float(gg.throughput_mbps.mean()), 3),
                throughput_std=round(float(gg.throughput_mbps.std(ddof=0)), 3),
                retransmits_mean=round(float(gg.retransmits.mean()), 1),
                mean_rtt_ms=round(float(gg.mean_rtt_ms.mean()), 3)))
        ts_path = os.path.join(ts_dir, "%s_run1.csv" % sid)
        ts = []
        if os.path.exists(ts_path):
            t = pd.read_csv(ts_path).round(3)
            ts = t.astype(object).where(t.notnull(), None).to_dict("records")
        data["scenarios"].append(dict(
            id=sid, group=str(first["group"]), bw_mbps=float(first.bw_mbps), rtt_ms=float(first.rtt_ms),
            loss_pct=float(first.loss_pct), buf_bdp=float(first.buf_bdp),
            n_flows=int(first.n_flows), flows=flows, timeseries=ts))
    with open(path, "w") as f:
        json.dump(data, f, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", path, "(%d scenarios)" % len(data["scenarios"]))


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Analyse TCP congestion control results")
    ap.add_argument("--results", default=os.path.join(ROOT, "results"))
    ap.add_argument("--pcap-stats", action="store_true")
    ap.add_argument("--export-json", action="store_true")
    ap.add_argument("--compare-ns3", metavar="NS3_RESULTS", default="",
                    help="NS-3 results folder; --results is then treated as the Mininet side")
    args = ap.parse_args()

    summary = os.path.join(args.results, "summary.csv")
    if not os.path.exists(summary):
        sys.exit("No %s yet. Run the experiments first (see README.md, step 'Run the experiments')." % summary)
    graphs = os.path.join(args.results, "graphs")
    ts_dir = os.path.join(args.results, "timeseries")
    os.makedirs(graphs, exist_ok=True)

    df = pd.read_csv(summary)
    print("loaded %d rows, %d scenarios from %s" % (len(df), df.scenario.nunique(), summary))

    agg = (df.groupby(["scenario", "flow", "algo", "n_flows", "bw_mbps", "rtt_ms", "loss_pct", "buf_bdp"])
             [["throughput_mbps", "retransmits", "mean_rtt_ms"]].agg(["mean", "std"]).round(3))
    agg.columns = ["_".join(c) for c in agg.columns]
    agg.reset_index().to_csv(os.path.join(args.results, "aggregated.csv"), index=False)

    for param in PARAMS:
        for metric in METRICS:
            sweep_plot(df, param, metric, os.path.join(graphs, "%s_vs_%s.png" % (metric, param)))
    fairness_plots(df, graphs)
    for loss in (0, 1):
        ts_plot(ts_dir, loss, os.path.join(graphs, "timeseries_loss%g.png" % loss))
    print("graphs saved in", graphs)

    base = single_flow_baseline(df, "loss_pct")
    if not base.empty:
        print("\nSingle-flow throughput (Mbps, mean) at 50 Mbps / 50 ms / 1xBDP:")
        print(base.pivot_table(index="loss_pct", columns="algo", values="throughput_mbps").round(2))

    cmp_tab = None
    if args.compare_ns3:
        ns_summary = os.path.join(args.compare_ns3, "summary.csv")
        if os.path.exists(ns_summary):
            ns = pd.read_csv(ns_summary)
            compare_plots(df, ns, graphs)
            cmp_tab = compare_table(df, ns, os.path.join(args.results, "compare_ns3_vs_mininet.csv"))
        else:
            print("NS-3 results not found:", ns_summary)

    if args.pcap_stats:
        pcap_stats(os.path.join(args.results, "pcap"), os.path.join(args.results, "pcap_stats.csv"))
    if args.export_json:
        export_json(df, ts_dir, os.path.join(args.results, "dashboard_data.json"))
    write_report(df, args.results, cmp_tab, os.path.join(args.results, "report.md"))


if __name__ == "__main__":
    main()
