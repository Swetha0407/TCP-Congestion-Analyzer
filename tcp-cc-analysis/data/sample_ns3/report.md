# TCP congestion control comparison - report data

Generated 2026-11-21 06:13 from `data/sample_ns3` (source: **ns3**).

> Statements under *Automatic observations* are computed from the data in this folder. Check them against the graphs before quoting them.

> **SAMPLE DATA**: Sample data: NS-3 3.41 simulation run while packaging this project (20 s runs, 3 repetitions). Not NS-3 3.46.1 and not Linux kernel measurements. Run the experiments on your machine to replace it.

## Setup

| Item | Value |
|---|---|
| Source | ns3 |
| TCP implementations | NS-3 TcpNewReno / TcpCubic / TcpBbr (NS-3 implementations, not the Linux kernel) |
| Kernel | 6.18.44-fc-v726 |
| OS | Ubuntu 24.04.5 LTS |
| NS-3 | 3.41 (Ubuntu 24.04 package libns3-dev 3.41-1.1build1) |
| Run length (s) | 20 |
| Repetitions | 3 |
| mininet | 2.3.0 |
| openvswitch | 3.3.9 |
| iperf3 | 3.16 |
| tcpdump | 4.99.4 |
| cmake | 3.28.3 |
| gxx | 13.3.0 |
| ninja | 1.11.1 |
| tc | 6.1.0 |

Rows analysed: 216 (54 scenarios, 3 algorithms).

## Throughput vs Random loss (%) (single flow, other parameters at baseline)

| Random loss (%) | BBR (Mbps) | CUBIC (Mbps) | RENO (Mbps) | Highest |
|---|---|---|---|---|
| 0 | 46.9 +/- 0.0 | 47.6 +/- 0.0 | 47.3 +/- 0.0 | CUBIC |
| 0.1 | 42.9 +/- 3.2 | 13.1 +/- 2.4 | 8.2 +/- 1.4 | BBR |
| 0.5 | 34.2 +/- 0.1 | 4.1 +/- 1.3 | 2.6 +/- 0.3 | BBR |
| 1 | 16.1 +/- 0.6 | 2.0 +/- 1.3 | 1.7 +/- 0.3 | BBR |
| 2 | 8.8 +/- 1.8 | 1.4 +/- 0.8 | 0.5 +/- 0.5 | BBR |

## Throughput vs RTT (ms) (single flow, other parameters at baseline)

| RTT (ms) | BBR (Mbps) | CUBIC (Mbps) | RENO (Mbps) | Highest |
|---|---|---|---|---|
| 10 | 46.9 +/- 0.0 | 48.1 +/- 0.0 | 48.0 +/- 0.0 | CUBIC |
| 50 | 46.9 +/- 0.0 | 47.6 +/- 0.0 | 47.3 +/- 0.0 | CUBIC |
| 100 | 35.7 +/- 2.1 | 46.7 +/- 0.0 | 38.8 +/- 0.0 | CUBIC |
| 200 | 18.1 +/- 1.8 | 44.8 +/- 0.0 | 43.1 +/- 0.0 | CUBIC |

## Throughput vs Bottleneck bandwidth (Mbps) (single flow, other parameters at baseline)

| Bottleneck bandwidth (Mbps) | BBR (Mbps) | CUBIC (Mbps) | RENO (Mbps) | Highest |
|---|---|---|---|---|
| 10 | 8.6 +/- 0.1 | 9.6 +/- 0.0 | 9.5 +/- 0.0 | CUBIC |
| 50 | 46.9 +/- 0.0 | 47.6 +/- 0.0 | 47.3 +/- 0.0 | CUBIC |
| 100 | 84.6 +/- 1.5 | 94.9 +/- 0.0 | 94.2 +/- 0.0 | CUBIC |

## Throughput vs Buffer size (x BDP) (single flow, other parameters at baseline)

| Buffer size (x BDP) | BBR (Mbps) | CUBIC (Mbps) | RENO (Mbps) | Highest |
|---|---|---|---|---|
| 0.25 | 41.8 +/- 0.2 | 43.1 +/- 0.0 | 39.8 +/- 0.0 | CUBIC |
| 1 | 46.9 +/- 0.0 | 47.6 +/- 0.0 | 47.3 +/- 0.0 | CUBIC |
| 4 | 47.0 +/- 0.0 | 47.6 +/- 0.0 | 47.3 +/- 0.0 | CUBIC |

## Fairness of two competing flows (mean over runs)

| Pair | Buffer (x BDP) | Flow 1 (Mbps) | Flow 2 (Mbps) | Jain index |
|---|---|---|---|---|
| BBR vs BBR | 0.25 | 21.6 | 14.5 | 0.850 |
| BBR vs BBR | 1 | 16.8 | 22.5 | 0.975 |
| BBR vs BBR | 4 | 23.6 | 23.5 | 1.000 |
| CUBIC vs BBR | 0.25 | 3.0 | 41.3 | 0.571 |
| CUBIC vs BBR | 1 | 18.3 | 26.3 | 0.955 |
| CUBIC vs BBR | 4 | 43.8 | 3.9 | 0.589 |
| CUBIC vs CUBIC | 0.25 | 26.7 | 20.4 | 0.982 |
| CUBIC vs CUBIC | 1 | 27.9 | 19.8 | 0.971 |
| CUBIC vs CUBIC | 4 | 24.2 | 23.3 | 1.000 |
| RENO vs BBR | 0.25 | 2.3 | 38.1 | 0.559 |
| RENO vs BBR | 1 | 2.4 | 44.6 | 0.555 |
| RENO vs BBR | 4 | 27.6 | 19.8 | 0.973 |
| RENO vs CUBIC | 0.25 | 17.1 | 30.0 | 0.930 |
| RENO vs CUBIC | 1 | 11.6 | 36.0 | 0.792 |
| RENO vs CUBIC | 4 | 16.4 | 31.2 | 0.912 |
| RENO vs RENO | 0.25 | 26.8 | 18.4 | 0.966 |
| RENO vs RENO | 1 | 29.8 | 17.7 | 0.939 |
| RENO vs RENO | 4 | 31.7 | 15.8 | 0.898 |

## Automatic observations

- At 0.1% random loss BBR reached 42.9 Mbps, 5.2x the 8.2 Mbps of RENO.
- At 0.5% random loss BBR reached 34.2 Mbps, 13.0x the 2.6 Mbps of RENO.
- At 1% random loss BBR reached 16.1 Mbps, 9.5x the 1.7 Mbps of RENO.
- At 2% random loss BBR reached 8.8 Mbps, 18.9x the 0.5 Mbps of RENO.
- Mean RTT with the largest buffer (4 x BDP): BBR 83 ms, CUBIC 206 ms, RENO 189 ms (base propagation RTT 50 ms).
- Least fair pairing: RENO vs BBR at 1 x BDP buffer (Jain index 0.555, 2.4 vs 44.6 Mbps).

## Figures

- `graphs/fairness_jain.png`
- `graphs/fairness_share.png`
- `graphs/mean_rtt_ms_vs_buf.png`
- `graphs/mean_rtt_ms_vs_bw.png`
- `graphs/mean_rtt_ms_vs_loss.png`
- `graphs/mean_rtt_ms_vs_rtt.png`
- `graphs/retransmits_vs_buf.png`
- `graphs/retransmits_vs_bw.png`
- `graphs/retransmits_vs_loss.png`
- `graphs/retransmits_vs_rtt.png`
- `graphs/throughput_mbps_vs_buf.png`
- `graphs/throughput_mbps_vs_bw.png`
- `graphs/throughput_mbps_vs_loss.png`
- `graphs/throughput_mbps_vs_rtt.png`
- `graphs/timeseries_loss0.png`
- `graphs/timeseries_loss1.png`
