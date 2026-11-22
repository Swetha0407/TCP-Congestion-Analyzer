/*
 * whatif.js - small educational fluid model of TCP Reno, CUBIC and BBR (v1) on one bottleneck link.
 *
 * It is NOT measured data and NOT the Linux kernel or NS-3: it steps a simplified model in 5 ms ticks
 * (one flow, one FIFO bottleneck, random loss before the queue) so you can see why the algorithms
 * behave differently when bandwidth, RTT, loss and buffer size change.
 *
 *   Reno  : slow start, +1 segment per RTT, halve on loss
 *   CUBIC : cubic window growth around the last loss window (beta 0.7, C 0.4) with the TCP-friendly floor
 *   BBR   : bottleneck-bandwidth max filter + min-RTT, startup / drain / probe-bandwidth cycle / probe-RTT;
 *           loss does not reduce its rate
 */
(function (root) {
  "use strict";

  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const PROBE_GAINS = [1.25, 0.75, 1, 1, 1, 1, 1, 1];

  /** p = {bw: Mbps, rtt: ms, loss: %, buf: x BDP, dur: s}. Returns time series + summary. */
  function simulate(algo, p) {
    const MSS = 1448, dt = 0.005, REC = 0.1;
    const rtt0 = p.rtt / 1000;
    const C = p.bw * 1e6 / 8 / MSS;                 // bottleneck rate, segments / s
    const bdp = C * rtt0;                           // segments
    const B = Math.max(3, p.buf * bdp);             // buffer, segments
    const pl = p.loss / 100;
    const rnd = mulberry32(12345 + Math.round(p.bw * 7 + p.rtt * 13 + p.loss * 1000 + p.buf * 100));
    const steps = Math.round(p.dur / dt);

    let q = 0, cwnd = 10, ssthresh = 1e9, lastCut = -1e9;
    let wmax = 0, epoch = -1, K = 0;                // CUBIC
    let btl = 0, minRtt = rtt0, mode = "startup";   // BBR
    let fullBw = 0, fullCnt = 0, roundEnd = rtt0, cycle = 2, cycleStart = 0;
    let probeRttUntil = -1, lastProbeRtt = 0;
    const win = [];                                 // delivery-rate samples {t, v} for the max filter

    const out = { t: [], thr: [], cwnd: [], qdelay: [], avgThr: 0, util: 0, avgQdelay: 0 };
    let accDel = 0, accQ = 0, accN = 0, totDel = 0, totQ = 0, nextRec = REC;

    for (let i = 0; i < steps; i++) {
      const t = i * dt;
      const rttNow = rtt0 + q / C;
      let rate, cwShown;

      if (algo === "bbr") {
        const inProbeRtt = probeRttUntil > t;
        let gain = mode === "startup" ? 2.885 : mode === "drain" ? 1 / 2.885 : PROBE_GAINS[cycle];
        const bwEst = btl > 0 ? btl : 10 / rtt0;
        const cwGain = mode === "startup" ? 2.885 : 2;
        let cap = Math.max(4, cwGain * bwEst * minRtt);
        if (inProbeRtt) cap = 4;
        rate = Math.min(gain * bwEst, cap / rttNow);
        cwShown = cap;
      } else {
        rate = cwnd / rttNow;
        cwShown = cwnd;
      }

      // bottleneck queue: random loss happens before the queue (as netem does in the testbed)
      const arrive = rate * dt * (1 - pl);
      const drain = C * dt;
      let space = q + arrive - drain, dropped = 0;
      if (space > B) { dropped = space - B; space = B; }
      if (space < 0) space = 0;
      const delivered = q + arrive - dropped - space;
      q = space;
      const overflow = dropped > 0;
      const randLoss = pl > 0 && rnd() < 1 - Math.pow(1 - pl, Math.max(rate * dt, 0));

      if (algo === "bbr") {
        const inProbeRtt = probeRttUntil > t;
        if (!inProbeRtt) {                              // samples taken during probe-RTT are not trusted
          win.push({ t: t, v: delivered / dt });
          const horizon = t - 10 * Math.max(rtt0, rttNow);
          while (win.length && win[0].t < horizon) win.shift();
          let m = 0;
          for (let k = 0; k < win.length; k++) if (win[k].v > m) m = win[k].v;
          btl = m;
        }
        if (rttNow < minRtt) minRtt = rttNow;
        if (t >= roundEnd) {
          roundEnd = t + rttNow;
          if (mode === "startup") {
            if (btl >= fullBw * 1.25) { fullBw = btl; fullCnt = 0; } else fullCnt++;
            if (fullCnt >= 3) mode = "drain";
          }
        }
        if (mode === "drain" && q <= 0.1 * bdp + 1) { mode = "probe"; cycle = 2; cycleStart = t; }
        if (mode === "probe") {
          const phase = t - cycleStart;
          const g = PROBE_GAINS[cycle];
          if (phase >= minRtt || (g < 1 && q <= 1)) { cycle = (cycle + 1) % 8; cycleStart = t; }
        }
        if (t - lastProbeRtt > 10 && mode === "probe") {
          probeRttUntil = t + 0.2 + rtt0; lastProbeRtt = probeRttUntil;
        }
      } else {
        const cut = (overflow || randLoss) && t - lastCut > rttNow;
        if (cut) {
          lastCut = t;
          if (algo === "reno") {
            ssthresh = Math.max(2, cwnd / 2); cwnd = ssthresh;
          } else {
            wmax = cwnd; cwnd = Math.max(2, cwnd * 0.7); ssthresh = cwnd;
            epoch = t; K = Math.cbrt(wmax * 0.3 / 0.4);
          }
        } else {
          const acked = delivered;
          if (cwnd < ssthresh) {
            cwnd += acked;                              // slow start
          } else if (algo === "reno") {
            cwnd += acked / cwnd;                       // congestion avoidance
          } else {
            if (epoch < 0) { epoch = t; wmax = cwnd; K = 0; }
            const tt = t - epoch + rttNow;
            const wCubic = 0.4 * Math.pow(tt - K, 3) + wmax;
            const wTcp = wmax * 0.7 + (3 * 0.3 / 1.7) * ((t - epoch) / rttNow);
            const target = Math.max(wCubic, wTcp);
            if (target > cwnd) cwnd += Math.min(target - cwnd, 0.5 * cwnd) / cwnd * acked;
            else cwnd += acked / (100 * cwnd);
          }
          cwnd = Math.min(cwnd, 20 * (bdp + B) + 10);
        }
      }

      accDel += delivered; accQ += q / C * 1000; accN++;
      totDel += delivered; totQ += q / C * 1000;
      if (t + dt >= nextRec - 1e-9) {
        out.t.push(+(nextRec).toFixed(2));
        out.thr.push(accDel * MSS * 8 / 1e6 / REC);
        out.cwnd.push(cwShown);
        out.qdelay.push(accQ / accN);
        accDel = 0; accQ = 0; accN = 0; nextRec += REC;
      }
    }
    out.avgThr = totDel * MSS * 8 / 1e6 / p.dur;
    out.util = out.avgThr / p.bw;
    out.avgQdelay = totQ / steps;
    return out;
  }

  const api = { simulate: simulate, ALGOS: ["reno", "cubic", "bbr"] };
  root.WhatIf = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
