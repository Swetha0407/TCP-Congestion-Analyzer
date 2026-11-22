#!/usr/bin/env python3
"""
run_ns3_matrix.py - run the experiment matrix (common/scenarios.py) in NS-3.

It copies tcp_variants.cc into <ns3-dir>/scratch, builds it, then runs every scenario / run
(optionally several in parallel) and writes results_ns3/ in the same layout as the Mininet runner.

Examples (Ubuntu/WSL2 terminal, no sudo needed):
    python3 ns3/run_ns3_matrix.py --quick
    python3 ns3/run_ns3_matrix.py --duration 30 --runs 3 --jobs 4
    python3 ns3/run_ns3_matrix.py --only sweep_loss --algos bbr cubic

Options:
  --ns3-dir   NS-3 folder (default: $NS3_DIR or ~/ns-3.46.1, where scripts/build_ns3.sh installs it)
  --binary    run an already built tcp_variants executable instead of using --ns3-dir
  --jobs N    simulations to run in parallel (default 1; use at most your CPU count)
  --resume    skip runs whose timeseries file already exists
"""
import argparse
import csv
import glob
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import envinfo  # noqa: E402
from common.scenarios import ALGOS, build_scenarios, scenario_id  # noqa: E402

SUMMARY_FIELDS = ["group", "scenario", "run", "flow", "algo", "n_flows", "bw_mbps", "rtt_ms",
                  "loss_pct", "buf_bdp", "throughput_mbps", "retransmits",
                  "mean_rtt_ms", "min_rtt_ms", "max_rtt_ms"]


def find_binary(ns3_dir):
    """Locate the built scratch program (name pattern: ns3.<ver>-tcp_variants-<profile>)."""
    cands = glob.glob(os.path.join(ns3_dir, "build", "scratch", "ns3*-tcp_variants-*"))
    cands += glob.glob(os.path.join(ns3_dir, "build", "scratch", "tcp_variants", "ns3*-tcp_variants-*"))
    cands = [c for c in cands if os.path.isfile(c) and os.access(c, os.X_OK)]
    return sorted(cands)[0] if cands else None


def read_ns3_version(ns3_dir):
    try:
        with open(os.path.join(ns3_dir, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return None


def merge_parts(out):
    """Append the per-run part files to summary.csv (single writer, so no races)."""
    parts = sorted(glob.glob(os.path.join(out, "parts", "*.csv")))
    if not parts:
        return 0
    summary = os.path.join(out, "summary.csv")
    new = not os.path.exists(summary)
    n = 0
    with open(summary, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(SUMMARY_FIELDS)
        for p in parts:
            with open(p, newline="") as pf:
                for row in csv.reader(pf):
                    if row:
                        w.writerow(row)
                        n += 1
            os.remove(p)
    return n


def run_sim(exe, env, ns3_dir, sc, run, duration, out):
    argv = [exe, "--algos=" + ",".join(sc["algos"]),
            "--bw=%g" % sc["bw"], "--rtt=%g" % sc["rtt"],
            "--loss=%g" % sc["loss"], "--buf=%g" % sc["buf"],
            "--duration=%d" % duration, "--run=%d" % run,
            "--group=" + sc["group"], "--out=" + out]
    r = subprocess.run(argv, cwd=ns3_dir or None, env=env, capture_output=True, text=True)
    return r


def main():
    ap = argparse.ArgumentParser(description="Run the TCP scenario matrix in NS-3")
    ap.add_argument("--ns3-dir", default=os.environ.get("NS3_DIR", os.path.expanduser("~/ns-3.46.1")))
    ap.add_argument("--binary", default="", help="path to a built tcp_variants executable")
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--quick", action="store_true", help="10 s, 1 run per scenario (smoke test)")
    ap.add_argument("--algos", nargs="+", default=ALGOS, choices=ALGOS)
    ap.add_argument("--only", default="")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "results_ns3"))
    ap.add_argument("--no-build", action="store_true", help="skip copying/building (already done)")
    ap.add_argument("--ns3-version", default="", help="version label stored in environment.json (for --binary runs)")
    ap.add_argument("--note", default="", help="free text stored in environment.json")
    ap.add_argument("--sample", action="store_true", help="mark the result set as sample data")
    args = ap.parse_args()

    if args.quick:
        args.duration, args.runs = 10, 1
    out = os.path.abspath(args.out)
    ns3_dir = ""
    env = dict(os.environ)
    version = None

    if args.binary:
        exe = os.path.abspath(args.binary)
        if not os.access(exe, os.X_OK):
            sys.exit("--binary is not an executable file: %s" % exe)
    else:
        ns3_dir = os.path.abspath(os.path.expanduser(args.ns3_dir))
        if not os.path.exists(os.path.join(ns3_dir, "ns3")):
            sys.exit("NS-3 not found in %s\n  Build it first:  bash scripts/build_ns3.sh\n"
                     "  or pass --ns3-dir / set NS3_DIR." % ns3_dir)
        version = read_ns3_version(ns3_dir)
        if not args.no_build:
            shutil.copy(os.path.join(ROOT, "ns3", "tcp_variants.cc"),
                        os.path.join(ns3_dir, "scratch", "tcp_variants.cc"))
            print("building tcp_variants in NS-3 (the first build can take a few minutes)...")
            r = subprocess.run(["./ns3", "build"], cwd=ns3_dir)
            if r.returncode != 0:
                sys.exit("NS-3 build failed - read the compiler error above (see docs/TROUBLESHOOTING.md).")
        exe = find_binary(ns3_dir)
        if not exe:
            sys.exit("Could not find the built tcp_variants executable under %s/build/scratch" % ns3_dir)
        env["LD_LIBRARY_PATH"] = os.path.join(ns3_dir, "build", "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")

    os.makedirs(os.path.join(out, "timeseries"), exist_ok=True)
    os.makedirs(os.path.join(out, "parts"), exist_ok=True)
    os.makedirs(os.path.join(out, "graphs"), exist_ok=True)
    merge_parts(out)  # leftovers from an interrupted earlier run

    envinfo.write_environment(os.path.join(out, "environment.json"), {
        "source": "ns3",
        "ns3_version": args.ns3_version or version or "unknown (--binary)",
        "tcp_models": "NS-3 TcpNewReno / TcpCubic / TcpBbr (NS-3 implementations, not the Linux kernel)",
        "sample": bool(args.sample),
        "note": args.note,
        "duration_s": args.duration,
        "runs": args.runs,
    })

    scenarios = build_scenarios(args.algos, args.only)
    jobs = [(sc, run) for sc in scenarios for run in range(1, args.runs + 1)]
    total = len(jobs)
    print("%d scenarios x %d runs = %d simulations (%d in parallel)" % (len(scenarios), args.runs, total, args.jobs))

    todo = []
    for sc, run in jobs:
        ts = os.path.join(out, "timeseries", "%s_run%d.csv" % (scenario_id(sc), run))
        if args.resume and os.path.exists(ts):
            continue
        todo.append((sc, run))
    if len(todo) != total:
        print("resume: %d already done, %d to go" % (total - len(todo), len(todo)))

    failed, done, t0 = 0, 0, time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = {pool.submit(run_sim, exe, env, ns3_dir, sc, run, args.duration, out): (sc, run)
                for sc, run in todo}
        for fut in as_completed(futs):
            sc, run = futs[fut]
            done += 1
            r = fut.result()
            tag = "%s run%d" % (scenario_id(sc), run)
            if r.returncode != 0:
                failed += 1
                print("[%d/%d] %s FAILED: %s" % (done, len(todo), tag, (r.stderr or r.stdout).strip()[-400:]))
                continue
            merge_parts(out)
            res = ", ".join(l.split(": ")[-1] for l in r.stdout.splitlines() if " Mbps" in l)
            print("[%d/%d] %s -> %s" % (done, len(todo), tag, res), flush=True)
    merge_parts(out)
    print("Done in %.0f s, %d failed. Results in %s" % (time.time() - t0, failed, out))
    print("Next: python3 analysis/analyze_results.py --results %s" % out)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
