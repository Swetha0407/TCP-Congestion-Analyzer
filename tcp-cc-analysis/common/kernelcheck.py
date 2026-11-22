"""Functional checks of the Linux kernel features the Mininet experiments depend on.

Nothing here assumes a feature works: each check really tries it and reports the result.
Needs root only for the network-namespace / tc test.
"""
import gzip
import os
import platform
import socket
import subprocess

# kernel config options the Mininet experiments rely on
WANTED_CONFIG = {
    "CONFIG_TCP_CONG_BBR": "BBR congestion control",
    "CONFIG_TCP_CONG_CUBIC": "CUBIC congestion control",
    "CONFIG_NET_SCH_NETEM": "tc netem (delay + random loss)",
    "CONFIG_NET_SCH_TBF": "tc tbf (bottleneck rate + buffer)",
    "CONFIG_NET_NS": "network namespaces (Mininet hosts)",
    "CONFIG_VETH": "virtual ethernet pairs (Mininet links)",
}


def is_wsl():
    return "microsoft" in platform.release().lower()


def kernel_config():
    """Return {option: 'y'|'m'|'n'} from /proc/config.gz, or None if it is not exposed."""
    try:
        with gzip.open("/proc/config.gz", "rt") as f:
            text = f.read()
    except OSError:
        return None
    cfg = {}
    for line in text.splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k] = v
    return cfg


def socket_cc_test(algo):
    """Can a TCP socket actually be switched to this algorithm? Returns (ok, message)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, algo.encode())
            got = s.getsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, 16)
            got = got.split(b"\0", 1)[0].decode()
        finally:
            s.close()
        return (got == algo, "socket reports '%s'" % got)
    except OSError as ex:
        return (False, "setsockopt failed: %s" % ex)


def try_load_modules():
    """Best effort: load the CUBIC / BBR modules (root only). Harmless if built in."""
    if os.geteuid() != 0:
        return
    for m in ("tcp_cubic", "tcp_bbr"):
        subprocess.run(["modprobe", m], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def netns_tc_test():
    """Create a throw-away network namespace and install the exact qdisc chain the runner uses.

    Returns (True|False|None, message). None means 'not tested' (not root / no tc).
    """
    if os.geteuid() != 0:
        return (None, "not tested (run with sudo)")
    ns = "ccpf%d" % os.getpid()

    def sh(cmd):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()

    if subprocess.run("command -v tc", shell=True, stdout=subprocess.DEVNULL).returncode != 0:
        return (None, "tc not installed (sudo apt install iproute2)")
    rc, out = sh("ip netns add %s" % ns)
    if rc != 0:
        return (False, "cannot create network namespace: %s" % out)
    try:
        steps = [
            ("netem loss+delay", "ip netns exec %s tc qdisc add dev lo root handle 1: netem loss 1%% delay 5ms limit 1000" % ns),
            ("tbf rate+buffer", "ip netns exec %s tc qdisc add dev lo parent 1:1 handle 10: tbf rate 50mbit burst 6250 limit 100000" % ns),
        ]
        for name, cmd in steps:
            rc, out = sh(cmd)
            if rc != 0:
                return (False, "%s failed: %s" % (name, out.splitlines()[-1] if out else "unknown error"))
        return (True, "netem + tbf qdiscs can be created")
    finally:
        sh("ip netns del %s" % ns)
