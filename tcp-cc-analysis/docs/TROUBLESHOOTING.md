# Troubleshooting

| Symptom | Fix |
|---|---|
| Preflight: `bbr` BLOCKED / netem or tbf missing | See `docs/WSL2_KERNEL.md`. Try `sudo modprobe tcp_bbr sch_netem sch_tbf` first. |
| `iperf3: error - unable to set congestion control` | Algorithm not in `/proc/sys/net/ipv4/tcp_available_congestion_control`; `sudo modprobe tcp_bbr`. |
| Mininet: `Cannot find required executable` | Run `bash scripts/install_deps.sh`. |
| Mininet leftovers after Ctrl+C | `sudo mn -c` |
| NS-3 build fails on `libgsl` | `sudo apt install libgsl-dev`, then `bash scripts/build_ns3.sh` again. |
| NS-3 binary not found | `bash scripts/build_ns3.sh`; or pass `--ns3-dir` / set `NS3_DIR`. |
| `--pcap-stats` empty | `which tshark`; install with `sudo apt install tshark`. pcaps are only recorded with `--pcap`. |
| Dashboard shows "sample data" banner | Normal until you run real experiments, then press **Reload data** (or `python3 dashboard/app.py --reimport`). |
| Port 5000 in use | `python3 dashboard/app.py --port 8080` |
| Windows browser can't open localhost:5000 | Use the WSL IP: `hostname -I`, then `http://<ip>:5000`. |
| Disk fills up | pcaps are large (tens of MB per run). Use `--pcap-runs 1` (default) or fewer scenarios via `--only`. |
