#!/usr/bin/env python3
"""
run_experiments.py - Mininet + iPerf3 experiments with the REAL Linux kernel TCP stack
(Reno, CUBIC, BBR).

Topology (dumbbell built from a plain Linux router, so no Open vSwitch / bridge module is needed):

    h1 --+
         +-- r ===== bottleneck (bw, loss, buffer) ===== d (receiver)
    h2 --+   (h2 only in the 2-flow fairness scenarios)

  * RTT: netem delay of rtt/2 on both ends of every sender access link (forward + reverse = rtt).
  * Bottleneck: on r's egress interface towards d:  netem (random loss)  ->  tbf (rate + buffer).
    Loss and rate limit apply to the data direction only; ACKs travel back unshaped.
  * Buffer size is given in multiples of the BDP (bandwidth x RTT) and set as the tbf limit.
    (tbf also admits a burst of about 1 ms of data, so the effective buffer is slightly larger.)

Each run produces (inside --out, default results/):
  raw/<id>_run<k>_flow<n>.json     raw iperf3 JSON
  timeseries/<id>_run<k>.csv       cwnd / RTT / delivery rate from `ss -ti`, every ~0.2 s
  pcap/<id>_run<k>.pcap            sender-side capture (only with --pcap) for Wireshark / tshark
  summary.csv                      one row per flow per run
  environment.json                 kernel + tool versions used

Usage (Ubuntu/WSL2 terminal, root needed for Mininet):
  sudo python3 mininet/run_experiments.py --selftest       # 3 short checks, ~30 s
  sudo python3 mininet/run_experiments.py --quick          # 10 s, 1 run per scenario
  sudo python3 mininet/run_experiments.py                  # 30 s x 3 runs (the real experiment)
  sudo python3 mininet/run_experiments.py --pcap --resume
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import envinfo, kernelcheck  # noqa: E402
from common.scenarios import ALGOS, BASE, build_scenarios, scenario_id  # noqa: E402

try:
    from mininet.net import Mininet
    from mininet.log import setLogLevel
except ImportError:
    sys.exit("Python cannot import Mininet. Install it with:  sudo apt install mininet\n"
             "Run this script with the system python3 (sudo python3 ...), not from a venv.")

BASE_PORT = 5201
MTU_BYTES = 1514
RCV_IP = "10.0.100.1"
SUMMARY_FIELDS = ["group", "scenario", "run", "flow", "algo", "n_flows", "bw_mbps", "rtt_ms",
                  "loss_pct", "buf_bdp", "throughput_mbps", "retransmits",
                  "mean_rtt_ms", "min_rtt_ms", "max_rtt_ms"]


# ----------------------------------------------------------------------------- helpers
def tc(node, cmd):
    """Run a tc command on a Mininet node and fail loudly (with a hint) if the kernel refuses."""
    out = node.cmd(cmd)
    if "RTNETLINK" in out or "Error" in out or "Illegal" in out or "unknown" in out:
        raise RuntimeError(
            "command failed on %s: %s\n%s\n"
            "-> your kernel probably lacks tc netem/tbf. Run  sudo python3 scripts/preflight.py  and see "
            "docs/WSL2_KERNEL.md." % (node.name, cmd, out.strip()))
    return out


def sample_ss(host, dst_ip, port):
    """Read cwnd / RTT / retrans / delivery rate of the data socket from `ss -tin`."""
    out = host.cmd("ss -tin dst %s:%d" % (dst_ip, port))
    socks = []
    for line in out.splitlines():
        if line.startswith("ESTAB"):
            socks.append(line)
        elif socks and line[:1].isspace():
            socks[-1] += " " + line.strip()
    best, best_acked = None, -1
    for s in socks:  # iperf3 has a control + a data socket: take the busy one
        m = re.search(r"bytes_acked:(\d+)", s)
        acked = int(m.group(1)) if m else 0
        if acked > best_acked:
            best, best_acked = s, acked
    if best is None:
        return None
    cwnd = re.search(r"\bcwnd:(\d+)", best)
    if not cwnd:
        return None
    rtt = re.search(r"\brtt:([\d.]+)/", best)
    ret = re.search(r"\bretrans:\d+/(\d+)", best)
    rate = re.search(r"\bdelivery_rate ([\d.]+)([KMG]?)bps", best)
    scale = {"": 1e-6, "K": 1e-3, "M": 1.0, "G": 1e3}
    return (int(cwnd.group(1)),
            float(rtt.group(1)) if rtt else 0.0,
            int(ret.group(1)) if ret else 0,
            float(rate.group(1)) * scale[rate.group(2)] if rate else 0.0)


def parse_iperf(path):
    try:
        with open(path) as f:
            j = json.load(f)
        if "error" in j:
            print("    iperf3 error:", j["error"])
            return None
        e = j["end"]
        snd = e["streams"][0]["sender"]
        return dict(
            throughput_mbps=e["sum_received"]["bits_per_second"] / 1e6,
            retransmits=e["sum_sent"].get("retransmits", 0),
            mean_rtt_ms=snd.get("mean_rtt", 0) / 1000.0,
            min_rtt_ms=snd.get("min_rtt", 0) / 1000.0,
            max_rtt_ms=snd.get("max_rtt", 0) / 1000.0,
            cc=e.get("sender_tcp_congestion", ""),
        )
    except (ValueError, KeyError, IndexError, OSError) as ex:
        print("    could not parse %s (%s)" % (path, ex))
        return None


def chown_tree(path):
    """The runner needs sudo; give the result files back to the normal user."""
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if not uid or not os.path.exists(path):
        return
    uid, gid = int(uid), int(gid)
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chown(os.path.join(root, name), uid, gid)
            except OSError:
                pass
    try:
        os.chown(path, uid, gid)
    except OSError:
        pass


# ----------------------------------------------------------------------------- one experiment
def run_one(sc, run_idx, duration, out, save_pcap, shaping=True):
    n = len(sc["algos"])
    sid = scenario_id(sc)
    tag = "%s_run%d" % (sid, run_idx)

    net = Mininet(controller=None, build=False, autoSetMacs=True)
    r = net.addHost("r", ip=None)
    senders = [net.addHost("h%d" % (i + 1), ip=None) for i in range(n)]
    d = net.addHost("d", ip=None)
    access = [net.addLink(h, r, params1={"ip": "10.0.%d.1/24" % (i + 1)},
                          params2={"ip": "10.0.%d.254/24" % (i + 1)})
              for i, h in enumerate(senders)]
    bott = net.addLink(r, d, params1={"ip": "10.0.100.254/24"}, params2={"ip": RCV_IP + "/24"})
    rows = []
    try:
        net.start()
        r.cmd("sysctl -w net.ipv4.ip_forward=1")
        for i, h in enumerate(senders):
            h.cmd("ip route add default via 10.0.%d.254" % (i + 1))
        d.cmd("ip route add default via 10.0.100.254")

        # offloads off so tc shaping and captures see real MTU-sized packets
        for node in senders + [r, d]:
            for intf in node.intfList():
                if intf.name != "lo":
                    node.cmd("ethtool -K %s tso off gso off gro off 2>/dev/null" % intf.name)

        # check connectivity (and warm up ARP) before adding delay
        for h in senders:
            pong = h.cmd("ping -c 1 -W 2 %s" % RCV_IP)
            if " 1 received" not in pong and "1 packets received" not in pong:
                raise RuntimeError("no connectivity %s -> %s (is iputils-ping installed?):\n%s"
                                   % (h.name, RCV_IP, pong.strip()))

        if shaping:
            half = sc["rtt"] / 2.0
            for link in access:  # rtt/2 at both ends of each access link
                for intf in (link.intf1, link.intf2):
                    tc(intf.node, "tc qdisc replace dev %s root netem delay %gms limit 100000"
                       % (intf.name, half))
            bdp_bytes = sc["bw"] * 1e6 / 8.0 * sc["rtt"] / 1000.0
            burst = max(3200, int(sc["bw"] * 1e6 / 8.0 / 1000.0))
            limit = max(int(bdp_bytes * sc["buf"]), 2 * MTU_BYTES, burst)
            bif = bott.intf1  # router side = data direction
            loss = " loss %g%%" % sc["loss"] if sc["loss"] > 0 else ""
            tc(bif.node, "tc qdisc replace dev %s root handle 1: netem%s limit 100000" % (bif.name, loss))
            tc(bif.node, "tc qdisc add dev %s parent 1:1 handle 10: tbf rate %gmbit burst %d limit %d"
               % (bif.name, sc["bw"], burst, limit))

        # iperf3 servers (one per flow) and optional sender-side capture
        servers = [d.popen(["iperf3", "-s", "-1", "-p", str(BASE_PORT + i)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                   for i in range(n)]
        time.sleep(1)
        cap = None
        if save_pcap:
            pcap = os.path.join(out, "pcap", tag + ".pcap")
            # -Z root: otherwise tcpdump drops privileges and cannot write into the results folder
            cap = senders[0].popen(["tcpdump", "-U", "-Z", "root", "-i", access[0].intf1.name,
                                    "-s", "96", "-w", pcap, "tcp"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)

        clients, jfiles = [], []
        for i, (h, algo) in enumerate(zip(senders, sc["algos"])):
            jf = os.path.join(out, "raw", "%s_flow%d.json" % (tag, i + 1))
            jfiles.append(jf)
            fh = open(jf, "w")
            p = h.popen(["iperf3", "-c", RCV_IP, "-p", str(BASE_PORT + i), "-t", str(duration),
                         "-i", "1", "-C", algo, "-J"], stdout=fh, stderr=subprocess.DEVNULL)
            clients.append((p, fh))

        # sample cwnd / rtt while the flows run
        samples = [[] for _ in senders]
        t0 = time.time()
        while any(p.poll() is None for p, _ in clients):
            t = round(time.time() - t0, 2)
            for i, h in enumerate(senders):
                s = sample_ss(h, RCV_IP, BASE_PORT + i)
                if s:
                    samples[i].append((t,) + s)
            time.sleep(0.2)
            if time.time() - t0 > duration + 30:
                print("    timeout, killing clients")
                for p, _ in clients:
                    p.kill()
                break
        for p, fh in clients:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            fh.close()
        if cap:
            time.sleep(0.5)
            cap.terminate()
        for s in servers:
            s.terminate()

        for i, jf in enumerate(jfiles):
            res = parse_iperf(jf)
            if not res:
                continue
            if res["cc"] and res["cc"] != sc["algos"][i]:
                print("    WARNING: flow %d used '%s' instead of '%s'" % (i + 1, res["cc"], sc["algos"][i]))
            rows.append(dict(group=sc["group"], scenario=sid, run=run_idx, flow=i + 1,
                             algo=sc["algos"][i], n_flows=n, bw_mbps=sc["bw"], rtt_ms=sc["rtt"],
                             loss_pct=sc["loss"], buf_bdp=sc["buf"],
                             throughput_mbps=round(res["throughput_mbps"], 3),
                             retransmits=res["retransmits"],
                             mean_rtt_ms=round(res["mean_rtt_ms"], 3),
                             min_rtt_ms=round(res["min_rtt_ms"], 3),
                             max_rtt_ms=round(res["max_rtt_ms"], 3)))

        if rows:
            ts_path = os.path.join(out, "timeseries", tag + ".csv")
            with open(ts_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t", "flow", "algo", "cwnd", "rtt_ms", "retrans", "delivery_mbps"])
                for i, srows in enumerate(samples):
                    for (t, cw, rt, rx, dr) in srows:
                        w.writerow([t, i + 1, sc["algos"][i], cw, rt, rx, round(dr, 3)])
    finally:
        net.stop()
    return rows


# ----------------------------------------------------------------------------- main
def append_summary(path, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def cleanup_mininet():
    subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def selftest(algos, out):
    """Short end-to-end check of the whole measurement chain, one 4 s run per algorithm."""
    print("Self-test: 4 s single-flow run per algorithm at 20 Mbps / 40 ms, no loss")
    ok_all = True
    for a in algos:
        sc = dict(group="selftest", algos=[a], bw=20, rtt=40, loss=0.0, buf=1.0)
        try:
            rows = run_one(sc, 1, 4, out, False)
        except Exception as ex:
            print("  [FAIL] %-5s %s" % (a, ex))
            ok_all = False
            cleanup_mininet()
            continue
        if not rows:
            print("  [FAIL] %-5s no result produced (iperf3 failed?)" % a)
            ok_all = False
            continue
        thr = rows[0]["throughput_mbps"]
        good = 10 <= thr <= 21
        print("  [%s] %-5s %.1f Mbps (expected roughly 14-19 on a 20 Mbps bottleneck)"
              % ("PASS" if good else "FAIL", a, thr))
        ok_all = ok_all and good
    return ok_all


def main():
    ap = argparse.ArgumentParser(description="Mininet + iPerf3 TCP congestion control experiments")
    ap.add_argument("--duration", type=int, default=30, help="seconds per run (default 30)")
    ap.add_argument("--runs", type=int, default=3, help="repetitions per scenario (default 3)")
    ap.add_argument("--quick", action="store_true", help="10 s, 1 run per scenario (smoke test)")
    ap.add_argument("--selftest", action="store_true", help="short end-to-end check, then exit")
    ap.add_argument("--algos", nargs="+", default=ALGOS, choices=ALGOS)
    ap.add_argument("--only", default="", help="only scenario groups containing this text (sweep_loss, fairness, ...)")
    ap.add_argument("--pcap", action="store_true", help="save a sender-side pcap (96-byte snaplen)")
    ap.add_argument("--pcap-runs", type=int, default=1,
                    help="with --pcap: capture only the first N runs of every scenario (default 1, keeps disk use low)")
    ap.add_argument("--resume", action="store_true", help="skip runs whose timeseries file already exists")
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    ap.add_argument("--no-shaping", action="store_true",
                    help="DEBUG ONLY: skip netem/tbf (results are NOT valid measurements)")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("Run with sudo (Mininet needs root):  sudo python3 mininet/run_experiments.py ...")
    if args.quick:
        args.duration, args.runs = 10, 1
    shaping = not args.no_shaping
    if not shaping:
        if args.out == os.path.join(ROOT, "results"):
            args.out = os.path.join(ROOT, "results_debug")
        print("!! --no-shaping: bandwidth/delay/loss are NOT applied. Debug output goes to %s and must not "
              "be used as results." % args.out)

    kernelcheck.try_load_modules()
    available = envinfo.available_cc()
    algos = [a for a in args.algos if a in available]
    for a in args.algos:
        if a not in available:
            print("WARNING: '%s' is not available in this kernel - skipping it. (see docs/WSL2_KERNEL.md)" % a)
    if not algos:
        sys.exit("None of the requested congestion control algorithms is available in this kernel.")

    if shaping:
        ok, msg = kernelcheck.netns_tc_test()
        if ok is False:
            sys.exit("Kernel check failed: %s\n-> see docs/WSL2_KERNEL.md (custom WSL2 kernel with "
                     "CONFIG_NET_SCH_NETEM and CONFIG_NET_SCH_TBF)." % msg)

    for sub in ("raw", "timeseries", "pcap", "graphs"):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)
    setLogLevel("warning")
    cleanup_mininet()

    if args.selftest:
        good = selftest(algos, args.out)
        chown_tree(args.out)
        print("SELF-TEST " + ("PASSED" if good else "FAILED - see messages above and docs/TROUBLESHOOTING.md"))
        sys.exit(0 if good else 1)

    envinfo.write_environment(os.path.join(args.out, "environment.json"), {
        "source": "mininet",
        "tcp_models": "Linux kernel TCP (%s) via iperf3 -C" % ", ".join(algos),
        "duration_s": args.duration,
        "runs": args.runs,
        "shaping": shaping,
    })
    summary = os.path.join(args.out, "summary.csv")

    scenarios = build_scenarios(algos, args.only)
    total = len(scenarios) * args.runs
    print("%d scenarios x %d runs = %d runs, about %.0f min"
          % (len(scenarios), args.runs, total, total * (args.duration + 6) / 60.0))

    k = 0
    for sc in scenarios:
        for run in range(1, args.runs + 1):
            k += 1
            tag = "%s_run%d" % (scenario_id(sc), run)
            if args.resume and os.path.exists(os.path.join(args.out, "timeseries", tag + ".csv")):
                print("[%d/%d] %s  (done, skipping)" % (k, total, tag))
                continue
            print("[%d/%d] %s" % (k, total, tag), flush=True)
            try:
                rows = run_one(sc, run, args.duration, args.out, args.pcap and run <= args.pcap_runs, shaping)
            except Exception as ex:  # keep going if one run breaks
                print("    FAILED:", ex)
                cleanup_mininet()
                continue
            if rows:
                append_summary(summary, rows)
                print("    " + ", ".join("%s %.1f Mbps" % (r["algo"], r["throughput_mbps"]) for r in rows))
            chown_tree(args.out)
    chown_tree(args.out)
    print("Done. Results in %s - next: python3 analysis/analyze_results.py" % args.out)


if __name__ == "__main__":
    main()
