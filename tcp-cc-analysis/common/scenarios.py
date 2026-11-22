"""Single source of truth for the experiment matrix.

Used by the Mininet runner, the NS-3 runner and the analysis scripts, so that both
platforms always run exactly the same scenarios and produce identical scenario IDs.
"""

ALGOS = ["reno", "cubic", "bbr"]

# Baseline operating point (units: Mbps, ms, percent, multiples of the BDP)
BASE = dict(bw=50, rtt=50, loss=0.0, buf=1.0)

# One-factor-at-a-time sweeps around BASE
SWEEPS = {
    "loss": [0, 0.1, 0.5, 1, 2],
    "rtt": [10, 50, 100, 200],
    "bw": [10, 50, 100],
    "buf": [0.25, 1, 4],
}

# Two competing flows (fairness tests), each run at every buffer size
FAIR_PAIRS = [
    ("reno", "reno"), ("cubic", "cubic"), ("bbr", "bbr"),
    ("cubic", "bbr"), ("reno", "bbr"), ("reno", "cubic"),
]


def scenario_id(sc):
    """Stable ID, e.g. 'bbr_bw50_rtt50_loss1_buf1' (same format in Python and C++)."""
    return "{}_bw{:g}_rtt{:g}_loss{:g}_buf{:g}".format(
        "-".join(sc["algos"]), sc["bw"], sc["rtt"], sc["loss"], sc["buf"])


def build_scenarios(algos=None, only=""):
    """Return the list of scenario dicts: group, algos, bw, rtt, loss, buf."""
    algos = list(algos or ALGOS)
    seen, out = set(), []

    def add(group, algo_list, **over):
        cfg = dict(BASE)
        cfg.update(over)
        sc = dict(group=group, algos=list(algo_list), **cfg)
        sid = scenario_id(sc)
        if sid not in seen:
            seen.add(sid)
            out.append(sc)

    for param, values in SWEEPS.items():
        for v in values:
            for a in algos:
                add("sweep_" + param, [a], **{param: v})
    for pair in FAIR_PAIRS:
        if all(a in algos for a in pair):
            for b in SWEEPS["buf"]:
                add("fairness", pair, buf=b)
    return [s for s in out if only in s["group"]]
