"""Collect tool / kernel versions so every result set records how it was produced."""
import datetime
import json
import os
import platform
import re
import subprocess
import sys

# tool name -> command that prints its version
TOOL_COMMANDS = {
    "mininet": ["mn", "--version"],
    "openvswitch": ["ovs-vsctl", "--version"],
    "iperf3": ["iperf3", "--version"],
    "tshark": ["tshark", "--version"],
    "tcpdump": ["tcpdump", "--version"],
    "cmake": ["cmake", "--version"],
    "gxx": ["g++", "--version"],
    "ninja": ["ninja", "--version"],
    "tc": ["tc", "-V"],
}

PY_MODULES = ["numpy", "pandas", "matplotlib", "flask"]


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + "\n" + r.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_version(text):
    m = re.search(r"(\d+(?:\.\d+)+)", text or "")
    return m.group(1) if m else None


def tool_version(name):
    """Version string of a CLI tool, or None if it is not installed / not parseable."""
    return parse_version(_run(TOOL_COMMANDS[name]))


def module_version(name):
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return None


def available_cc():
    try:
        with open("/proc/sys/net/ipv4/tcp_available_congestion_control") as f:
            return f.read().split()
    except OSError:
        return []


def os_release():
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        pass
    return info


def collect(extra=None):
    osr = os_release()
    env = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "os": osr.get("PRETTY_NAME", platform.platform()),
        "kernel": platform.release(),
        "wsl": "microsoft" in platform.release().lower(),
        "python": platform.python_version(),
        "tcp_available_congestion_control": available_cc(),
        "tools": {k: tool_version(k) for k in TOOL_COMMANDS},
        "python_modules": {m: module_version(m) for m in PY_MODULES},
    }
    if extra:
        env.update(extra)
    return env


def write_environment(path, extra=None):
    env = collect(extra)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(env, f, indent=2)
    return env


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, indent=2)
    print()
