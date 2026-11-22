# TCP Congestion Control Lab - Reno vs CUBIC vs BBR

Analysis of TCP congestion control variants under varying network conditions using **Mininet + iPerf3 (real Linux kernel TCP)**,
**NS-3 (simulation)**, **tcpdump/Wireshark (tshark)**, and a **Flask + SQLite + Chart.js dashboard**.

Primary environment: **Windows 11 -> WSL2 -> Ubuntu 26.04**. Every command below is for the **Ubuntu terminal**.

| Module | What | Where |
|---|---|---|
| 1 Environment & CC config | version/kernel checks, functional tests of BBR/netem/tbf | `scripts/preflight.py`, `common/` |
| 2 NS-3 simulation | dumbbell sim, Reno/CUBIC/BBR | `ns3/` |
| 3 Mininet + iPerf3 | router topology, tc netem+tbf, `ss` sampling, pcaps | `mininet/` |
| 4 Packet analysis & report | graphs, fairness, NS-3 vs Linux, tshark stats, `report.md` | `analysis/` |
| Dashboard | 8-tab website (replay, what-if simulator...) | `dashboard/` |

> **Linux kernel vs NS-3:** Mininet/iPerf3 uses the *kernel's* TCP. NS-3 uses *its own* TCP models. They are never mixed up in the
> outputs, and differences between them are expected (see `docs/METHODOLOGY.md`).

## 0. What was and was NOT verified
Verified while building (in a Linux sandbox): NS-3 code compiles and runs (NS-3 **3.41**), the Mininet measurement chain runs
(with shaping off), analysis/report/SQLite/Flask/dashboard work, tshark pcap parsing (tshark 4.2.2).
**Not verifiable there:** NS-3 **3.46.1** build, Python 3.14.4, Ubuntu 26.04 packages, tc netem/tbf/BBR on your WSL2 kernel
(6.6.87.2). That is why step 3 (preflight) exists - it tests these on *your* machine. Version differences vs your reference list
are shown as warnings, never silently changed.

## 1. Unpack (in the Linux filesystem, NOT /mnt/c)
Windows: put the zip somewhere, then in Ubuntu:
```bash
cp /mnt/c/Users/<YourWindowsUser>/Downloads/tcp-cc-analysis.zip ~/
cd ~ && unzip tcp-cc-analysis.zip && cd tcp-cc-analysis
```
(`sudo apt install unzip` if missing.)

## 2. Install only what's missing
```bash
bash scripts/install_deps.sh --dry-run   # shows what it would install
bash scripts/install_deps.sh             # installs only missing apt packages
bash scripts/setup_venv.sh               # venv using system packages; pip-installs only missing pinned ones
source .venv/bin/activate
```
When the wireshark/tshark installer asks about non-root capture, answer **No**.

## 3. Preflight (verify before running anything)
```bash
sudo .venv/bin/python scripts/preflight.py          # add --deep for a Mininet self-test
```
It prints tool versions vs your reference, kernel TCP algorithms, and functional tests for BBR, netem and tbf. Module status is
**READY** or **BLOCKED**. If Mininet is BLOCKED (missing netem/tbf/BBR), follow `docs/WSL2_KERNEL.md`.

## 4. Build NS-3 3.46.1 (once, ~20-40 min)
```bash
bash scripts/build_ns3.sh        # downloads, configures (optimized), builds ns-3.46.1 into ~/ns-3.46.1
```
If your NS-3 is elsewhere: `export NS3_DIR=/path/to/ns-3.46.1`. Because the simulation source was only compiled against 3.41,
if the 3.46.1 build reports an API error, send me the first error lines - it's a small fix.

## 5. Run the experiments
Everything at once:
```bash
bash scripts/run_all.sh quick            # 10 s runs x1 (~15 min Mininet + NS-3)
bash scripts/run_all.sh full --pcap      # 30 s runs x3 (~2-3 h), with pcaps
```
Or step by step:
```bash
sudo .venv/bin/python mininet/run_experiments.py --selftest       # tiny check
sudo .venv/bin/python mininet/run_experiments.py --quick --pcap   # Linux kernel results -> results/
python3 ns3/run_ns3_matrix.py --quick                             # NS-3 results -> results_ns3/
```
Useful flags: `--algos reno cubic bbr`, `--only sweep_loss`, `--resume` (skip finished runs), `--pcap-runs N`.
Mininet needs `sudo`; `sudo .venv/bin/python` keeps the venv. Files are chown'd back to you. Interrupted? `sudo mn -c`, rerun with `--resume`.
pcaps are large (tens of MB each); default is one pcap per scenario.

## 6. Analysis and report
```bash
python3 analysis/analyze_results.py --results results --pcap-stats --compare-ns3 results_ns3 --export-json
```
Outputs in `results/`: `graphs/*.png`, `aggregated.csv`, `pcap_stats.csv`, **`report.md`** (data-driven observations).
Run it with `--help` for the exact options. For NS-3 alone, point `--results results_ns3`.

## 7. Dashboard
```bash
python3 dashboard/app.py --reimport
```
Open **http://localhost:5000** in your Windows browser (if it doesn't load, use `http://<output of hostname -I>:5000`).
Until you have real results it shows the bundled **NS-3 sample data** with a banner; real `results/` and `results_ns3/` replace it
automatically. After new runs press **Reload data**.
Tabs: Overview - Parameter sweeps - Live replay (animated real traces) - Fairness - NS-3 vs Linux - Packet analysis -
What-if simulator (educational model, not measured) - About & setup. Works offline (Chart.js bundled).

## 8. Wireshark on Windows
pcaps are in `results/pcap/`. Open in Windows Wireshark via `\\wsl.localhost\Ubuntu\home\<user>\tcp-cc-analysis\results\pcap\`
(use your distro name from `wsl -l`). Useful filters: `tcp.analysis.retransmission`, `tcp.analysis.duplicate_ack`;
Statistics -> TCP Stream Graphs -> Time Sequence (tcptrace).

## 9. Layout
```
common/    shared scenario matrix, env/kernel checks     mininet/   Linux-kernel runner
ns3/       simulation + matrix runner                    analysis/  graphs, report, tshark stats
dashboard/ Flask app, SQLite import, web UI              scripts/   install, venv, preflight, build, run_all
data/sample_ns3/  labelled sample NS-3 output            docs/      WSL2_KERNEL, TROUBLESHOOTING, METHODOLOGY
```
Problems? `docs/TROUBLESHOOTING.md`.
