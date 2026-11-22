#!/usr/bin/env python3
"""
preflight.py - verify the environment BEFORE running experiments. Nothing is assumed:
versions are read from the installed tools and kernel features are tested for real.

  python3 scripts/preflight.py            # versions + kernel config + socket tests (no root)
  sudo python3 scripts/preflight.py       # additionally tests netns + tc netem/tbf
  sudo python3 scripts/preflight.py --deep  # additionally runs the Mininet self-test (~30 s)

Results: PASS / WARN (works, but differs from the reference setup) / FAIL (blocks a module).
The last block tells you which project modules are READY or BLOCKED.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import envinfo, kernelcheck  # noqa: E402

# Reference environment this project was written for (prefix match: "15.2" matches 15.2.0)
EXPECTED = {
    "kernel": "6.6.87.2-microsoft-standard-WSL2",
    "os": "Ubuntu 26.04",
    "python": "3.14.4",
    "ns3": "3.46.1",
    "mininet": "2.3.0",
    "openvswitch": "3.7.1",
    "iperf3": "3.20",
    "tshark": "4.6.4",
    "tcpdump": "4.99.6",
    "cmake": "4.2.3",
    "gxx": "15.2",
    "ninja": "1.13.2",
    "numpy": "2.3.5",
    "pandas": "2.3.3",
    "matplotlib": "3.10.7",
}

results = []  # (status, area, text)


def add(status, area, text):
    results.append((status, area, text))
    mark = {"PASS": "[ PASS ]", "WARN": "[ WARN ]", "FAIL": "[ FAIL ]", "INFO": "[ INFO ]"}[status]
    print("%s %-9s %s" % (mark, area, text))


def version_ok(found, expected):
    return found is not None and (found == expected or found.startswith(expected + "."))


def check_tool(area, key, label, required, hint, expected=None):
    exp = expected if expected is not None else EXPECTED.get(key, "")
    found = envinfo.tool_version(key)
    if found is None:
        add("FAIL" if required else "WARN", area, "%s not found - %s" % (label, hint))
        return None
    if not exp:
        add("PASS", area, "%s %s" % (label, found))
    elif version_ok(found, exp):
        add("PASS", area, "%s %s" % (label, found))
    else:
        add("WARN", area, "%s %s (reference %s) - should still work, results may differ slightly" % (label, found, exp))
    return found


def check_module(key, required=True):
    found = envinfo.module_version(key)
    if found is None:
        add("FAIL" if required else "WARN", "python", "%s not importable - run: bash scripts/setup_venv.sh" % key)
        return
    exp = EXPECTED.get(key)
    if exp and not version_ok(found, exp):
        add("WARN", "python", "%s %s (reference %s)" % (key, found, exp))
    else:
        add("PASS", "python", "%s %s" % (key, found))


def ns3_dir():
    return os.path.abspath(os.path.expanduser(os.environ.get("NS3_DIR", "~/ns-3.46.1")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true", help="also run the Mininet self-test (needs sudo)")
    args = ap.parse_args()
    is_root = os.geteuid() == 0

    print("== System ==")
    osr = envinfo.os_release()
    pretty = osr.get("PRETTY_NAME", platform.platform())
    add("PASS" if osr.get("VERSION_ID", "").startswith("26.04") else "WARN", "system",
        "%s (reference %s)" % (pretty, EXPECTED["os"]))
    kernel = platform.release()
    wsl = kernelcheck.is_wsl()
    add("PASS" if kernel == EXPECTED["kernel"] else "WARN", "system",
        "kernel %s%s (reference %s)" % (kernel, " [WSL2]" if wsl else "", EXPECTED["kernel"]))
    py = platform.python_version()
    add("PASS" if version_ok(py, EXPECTED["python"]) else "WARN", "system",
        "python %s (reference %s)" % (py, EXPECTED["python"]))
    if os.path.abspath(ROOT).startswith("/mnt/"):
        add("WARN", "system", "project is on the Windows drive (%s): Mininet/iperf3 results are slower and file "
            "permissions break. Move it to your Linux home: cp -r to ~/" % ROOT)
    else:
        add("PASS", "system", "project is on the Linux filesystem (%s)" % ROOT)

    print("\n== Tools ==")
    check_tool("mininet", "mininet", "mininet", True, "sudo apt install mininet")
    check_tool("iperf3", "iperf3", "iperf3", True, "sudo apt install iperf3")
    check_tool("tcpdump", "tcpdump", "tcpdump", False, "sudo apt install tcpdump (needed only for --pcap)")
    check_tool("tshark", "tshark", "tshark", False, "sudo apt install tshark (needed only for --pcap-stats)")
    check_tool("tc", "tc", "tc (iproute2)", True, "sudo apt install iproute2", expected="")
    if shutil.which("ping") is None:
        add("FAIL", "tools", "ping not found - sudo apt install iputils-ping")
    if shutil.which("ethtool") is None:
        add("WARN", "tools", "ethtool not found - sudo apt install ethtool (offloads would stay on)")
    ovs = envinfo.tool_version("openvswitch")
    if ovs:
        add("INFO", "tools", "Open vSwitch %s found (reference %s) - not required: this project's Mininet "
            "topology uses a plain Linux router" % (ovs, EXPECTED["openvswitch"]))
    else:
        add("INFO", "tools", "Open vSwitch not installed - fine, this project does not need it")
    check_tool("build", "cmake", "cmake", False, "sudo apt install cmake (needed to build NS-3)")
    check_tool("build", "gxx", "g++", False, "sudo apt install build-essential (needed to build NS-3)")
    check_tool("build", "ninja", "ninja", False, "sudo apt install ninja-build (optional, speeds up the NS-3 build)")
    for m in ("numpy", "pandas", "matplotlib"):
        check_module(m)
    check_module("flask")

    print("\n== Linux kernel TCP (used by the Mininet experiments) ==")
    kernelcheck.try_load_modules()
    avail = envinfo.available_cc()
    add("INFO", "kernel", "tcp_available_congestion_control = %s" % " ".join(avail))
    cfg = kernelcheck.kernel_config()
    if cfg is None:
        add("INFO", "kernel", "/proc/config.gz not exposed - skipping kernel config check")
    else:
        for opt, what in kernelcheck.WANTED_CONFIG.items():
            val = cfg.get(opt)
            if val in ("y", "m"):
                add("PASS", "kernel", "%s=%s (%s)" % (opt, val, what))
            else:
                add("FAIL" if opt in ("CONFIG_NET_SCH_NETEM", "CONFIG_NET_SCH_TBF") else "WARN", "kernel",
                    "%s is not set (%s) - see docs/WSL2_KERNEL.md" % (opt, what))
    for algo in ("reno", "cubic", "bbr"):
        ok, msg = kernelcheck.socket_cc_test(algo)
        add("PASS" if ok else "FAIL", "kernel", "TCP socket can use %s: %s" % (algo, msg))
    ok, msg = kernelcheck.netns_tc_test()
    if ok is None:
        add("WARN", "kernel", "netns + tc netem/tbf test skipped: %s" % msg)
    else:
        add("PASS" if ok else "FAIL", "kernel", "netns + tc: %s" % msg)

    print("\n== NS-3 (used by the simulation module) ==")
    d = ns3_dir()
    vfile = os.path.join(d, "VERSION")
    if os.path.exists(os.path.join(d, "ns3")):
        try:
            v = open(vfile).read().strip().replace("ns-", "")
        except OSError:
            v = None
        if v and version_ok(v, EXPECTED["ns3"]):
            add("PASS", "ns3", "NS-3 %s at %s" % (v, d))
        else:
            add("WARN", "ns3", "NS-3 %s at %s (reference %s)" % (v or "unknown version", d, EXPECTED["ns3"]))
        built = any(f.startswith("libns3") for f in os.listdir(os.path.join(d, "build", "lib"))) \
            if os.path.isdir(os.path.join(d, "build", "lib")) else False
        add("PASS" if built else "FAIL", "ns3", "NS-3 is built" if built else
            "NS-3 is not built yet - bash scripts/build_ns3.sh")
    else:
        add("FAIL", "ns3", "NS-3 not found at %s - bash scripts/build_ns3.sh (or set NS3_DIR)" % d)

    if args.deep:
        print("\n== Mininet self-test ==")
        if not is_root:
            add("WARN", "mininet", "--deep needs sudo; skipped")
        else:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "mininet", "run_experiments.py"), "--selftest"])
            add("PASS" if r.returncode == 0 else "FAIL", "mininet", "self-test %s" % ("passed" if r.returncode == 0 else "failed"))

    # ---- module readiness
    def failed(*areas):
        return [t for s, a, t in results if s == "FAIL" and a in areas]

    mn_block = failed("mininet", "iperf3", "kernel", "tools")
    ns_block = failed("ns3", "build")
    an_block = failed("python")
    print("\n== Module readiness ==")
    for name, block in (("Mininet + iPerf3 emulation (Linux kernel TCP)", mn_block),
                        ("NS-3 simulation", ns_block),
                        ("Analysis + Flask dashboard", an_block)):
        if block:
            print("  BLOCKED  %s" % name)
            for t in block[:4]:
                print("           - %s" % t)
        else:
            print("  READY    %s" % name)
    if not is_root:
        print("\nTip: run with sudo to also test netns + tc netem/tbf (the usual WSL2 blocker).")
    nfail = sum(1 for s, _, _ in results if s == "FAIL")
    nwarn = sum(1 for s, _, _ in results if s == "WARN")
    print("\n%d failure(s), %d warning(s)." % (nfail, nwarn))
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
