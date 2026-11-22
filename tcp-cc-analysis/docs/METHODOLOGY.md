# Methodology and caveats

**Linux kernel vs NS-3.** Mininet/iPerf3 results use the real Linux kernel TCP stack (Reno, CUBIC, BBR v1,
chosen with `iperf3 -C`). NS-3 results use NS-3's own re-implementations (`ns3::TcpNewReno`, `TcpCubic`, `TcpBbr`).
They are different code and are *expected* to differ; the "NS-3 vs Linux" tab shows this, it is not an error.
NS-3's BBR in particular is known to be weaker at high RTT / loss - this is model behaviour, not a config bug.

**Topology.** Senders - router - receiver, built from a plain Linux router in Mininet. Bottleneck shaping on the
router egress: `tc netem` (delay, random loss) + `tbf` (rate, buffer). Buffer = multiple of BDP. NIC offloads disabled.

**Scenarios.** One baseline (50 Mbps, 50 ms RTT, 0 % loss, 1xBDP) with one-at-a-time sweeps of loss, RTT, bandwidth,
buffer, plus 6 two-flow fairness pairs x 3 buffer sizes (54 scenarios; `common/scenarios.py`).

**Metrics.** Throughput (iperf3), cwnd / RTT / delivery rate sampled with `ss -tin`, retransmissions, Jain's fairness
index. NS-3 "retransmits" are approximated with FlowMonitor lost packets. NS-3 without loss is deterministic, so
its std-dev across runs is 0. pcap statistics (retransmissions, dup ACKs, ack RTT) come from tshark.

**Sample data.** `data/sample_ns3/` is real NS-3 output produced while building the project (NS-3 3.41, not 3.46.1)
and is labelled as sample in the dashboard. No Mininet results are shipped - you generate them.
**What-if tab.** A simplified fluid model for intuition, not measured data.
