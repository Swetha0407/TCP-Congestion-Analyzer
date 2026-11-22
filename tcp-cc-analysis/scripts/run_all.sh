#!/usr/bin/env bash
# One command for the whole pipeline.   Run in the Ubuntu (WSL2) terminal from the project folder:
#
#   bash scripts/run_all.sh quick        # 10 s runs, 1 repetition (about 15 min Mininet + a few min NS-3)
#   bash scripts/run_all.sh full         # 30 s runs, 3 repetitions (roughly 2-3 h Mininet + NS-3)
#   bash scripts/run_all.sh full --pcap  # also capture sender-side pcaps (first run of each scenario)
#
# Steps: preflight -> Mininet/iPerf3 -> NS-3 -> analysis (graphs, report, comparison) -> SQLite import.
# Every step can also be run on its own (see README.md). Safe to re-run: finished runs are skipped.
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-quick}"
EXTRA="${2:-}"
case "$MODE" in
  quick) MN_ARGS=(--quick); NS_ARGS=(--quick) ;;
  full)  MN_ARGS=(--duration 30 --runs 3); NS_ARGS=(--duration 30 --runs 3 --jobs "$(nproc)") ;;
  *) echo "usage: bash scripts/run_all.sh quick|full [--pcap]"; exit 2 ;;
esac
PCAP=()
[ "$EXTRA" = "--pcap" ] && PCAP=(--pcap)

echo "== 1/5 preflight =="
sudo python3 scripts/preflight.py || { echo "Preflight reported failures. Fix them (docs/TROUBLESHOOTING.md) and rerun."; exit 1; }

echo "== 2/5 Mininet + iPerf3 (Linux kernel TCP) =="
sudo python3 mininet/run_experiments.py "${MN_ARGS[@]}" "${PCAP[@]}" --resume

echo "== 3/5 NS-3 simulation =="
python3 ns3/run_ns3_matrix.py "${NS_ARGS[@]}" --resume

echo "== 4/5 analysis =="
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
STATS=()
[ -n "$(ls results/pcap/*.pcap 2>/dev/null || true)" ] && STATS=(--pcap-stats)
$PY analysis/analyze_results.py --results results --compare-ns3 results_ns3 "${STATS[@]}"
$PY analysis/analyze_results.py --results results_ns3

echo "== 5/5 import into the dashboard database =="
$PY dashboard/import_results.py --mininet results --ns3 results_ns3

echo
echo "All done. Start the dashboard with:   $PY dashboard/app.py     then open http://localhost:5000"
