"""SQLite storage for the dashboard (standard library only)."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    source TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
    PRIMARY KEY (source, key)
);
CREATE TABLE IF NOT EXISTS runs (
    source TEXT NOT NULL, scenario TEXT NOT NULL, grp TEXT, run INTEGER, flow INTEGER, algo TEXT,
    n_flows INTEGER, bw_mbps REAL, rtt_ms REAL, loss_pct REAL, buf_bdp REAL,
    throughput_mbps REAL, retransmits REAL, mean_rtt_ms REAL, min_rtt_ms REAL, max_rtt_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_runs_src ON runs (source, n_flows, algo);
CREATE INDEX IF NOT EXISTS idx_runs_scn ON runs (source, scenario);
CREATE TABLE IF NOT EXISTS timeseries (
    source TEXT NOT NULL, scenario TEXT NOT NULL, run INTEGER, flow INTEGER, algo TEXT,
    t REAL, cwnd REAL, rtt_ms REAL, retrans REAL, delivery_mbps REAL
);
CREATE INDEX IF NOT EXISTS idx_ts ON timeseries (source, scenario, run);
CREATE TABLE IF NOT EXISTS pcap_stats (
    source TEXT NOT NULL, pcap TEXT, scenario TEXT, run INTEGER, packets INTEGER,
    retransmissions INTEGER, fast_retransmissions INTEGER, dup_acks INTEGER,
    rtt_mean_ms REAL, rtt_p95_ms REAL
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
