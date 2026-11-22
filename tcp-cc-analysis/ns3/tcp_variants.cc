/*
 * tcp_variants.cc - NS-3 simulation of TCP Reno / CUBIC / BBR on a dumbbell topology.
 *
 * IMPORTANT: these are NS-3's own implementations (ns3::TcpNewReno, ns3::TcpCubic, ns3::TcpBbr),
 * NOT the Linux kernel code. The Mininet experiments use the real Linux kernel implementations.
 * ns3::TcpBbr is BBR v1; Linux 6.6 also ships BBR v1.
 *
 * Topology (same logical layout as the Mininet experiments):
 *
 *   sender1 --+
 *             +-- R1 ==== bottleneck (bw, loss, buffer) ==== R2 -- receiver
 *   sender2 --+   (sender2 only in the 2-flow fairness scenarios)
 *
 *  - RTT: rtt/2 propagation delay on every sender access link (forward + reverse = rtt).
 *  - Buffer: FIFO queue disc on R1's bottleneck interface, sized in multiples of the BDP.
 *  - Random loss: RateErrorModel on R2's receive side (data direction only, ACKs are not dropped).
 *  - Pacing is enabled only for BBR sockets (as in Linux, where BBR needs internal pacing).
 *
 * Build:  copied to <ns-3>/scratch/ by ns3/run_ns3_matrix.py (or scripts/build_ns3.sh)
 * Manual: ./ns3 run "tcp_variants --algos=cubic,bbr --bw=50 --rtt=50 --loss=0 --buf=1 --out=results_ns3"
 *
 * Output (same layout as the Mininet runner, so analysis/analyze_results.py works on both):
 *   <out>/parts/<id>_run<k>.csv         summary rows (merged into summary.csv by run_ns3_matrix.py)
 *   <out>/timeseries/<id>_run<k>.csv    cwnd (segments), RTT sample, delivery rate every 0.1 s
 * The 'retransmits' column is the number of data packets lost in the network per flow
 * (FlowMonitor lostPackets). Every loss triggers a retransmission, so it tracks retransmits
 * closely, but it is not a direct retransmission counter like the kernel's.
 */
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-module.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("TcpVariants");

struct Flow
{
    int id = 0;
    std::string algo;
    uint16_t port = 0;
    Ptr<PacketSink> sink;
    Ptr<BulkSendApplication> app;
    uint32_t cwnd = 0; // bytes
    double rttMs = 0;  // last RTT sample
    double rttSum = 0;
    double rttMin = 1e9;
    double rttMax = 0;
    uint64_t rttN = 0;
    uint64_t lastRx = 0;
};

static std::vector<Flow> g_flows;
static std::ofstream g_ts;
static double g_start = 1.0; // first flow starts at 1 s
static double g_duration = 30;
static const double g_interval = 0.1;
static const uint32_t MSS = 1448;
static const uint16_t BASE_PORT = 5201;

static void
CwndTrace(Flow* f, uint32_t /*oldVal*/, uint32_t newVal)
{
    f->cwnd = newVal;
}

static void
RttTrace(Flow* f, Time /*oldVal*/, Time newVal)
{
    double ms = newVal.GetSeconds() * 1000.0;
    f->rttMs = ms;
    f->rttSum += ms;
    f->rttN++;
    f->rttMin = std::min(f->rttMin, ms);
    f->rttMax = std::max(f->rttMax, ms);
}

static void
ConnectTraces()
{
    for (auto& f : g_flows)
    {
        Ptr<Socket> s = f.app->GetSocket();
        if (s)
        {
            s->TraceConnectWithoutContext("CongestionWindow", MakeBoundCallback(&CwndTrace, &f));
            s->TraceConnectWithoutContext("RTT", MakeBoundCallback(&RttTrace, &f));
        }
    }
}

// The pacing default is read when a socket is created, so it is switched just before each flow starts.
static void
SetPacingDefault(bool on)
{
    Config::SetDefault("ns3::TcpSocketState::EnablePacing", BooleanValue(on));
}

static void
Sample()
{
    double t = Simulator::Now().GetSeconds() - g_start;
    for (auto& f : g_flows)
    {
        uint64_t rx = f.sink->GetTotalRx();
        double rate = (rx - f.lastRx) * 8.0 / g_interval / 1e6;
        f.lastRx = rx;
        g_ts << std::fixed << std::setprecision(2) << t << "," << f.id << "," << f.algo << ","
             << std::setprecision(1) << (f.cwnd / static_cast<double>(MSS)) << ","
             << std::setprecision(3) << f.rttMs << "," << rate << "\n";
    }
    if (Simulator::Now().GetSeconds() + g_interval <= g_start + g_duration + 1e-9)
    {
        Simulator::Schedule(Seconds(g_interval), &Sample);
    }
}

static TypeId
AlgoType(const std::string& a)
{
    if (a == "reno")
    {
        return TypeId::LookupByName("ns3::TcpNewReno");
    }
    if (a == "cubic")
    {
        return TypeId::LookupByName("ns3::TcpCubic");
    }
    if (a == "bbr")
    {
        return TypeId::LookupByName("ns3::TcpBbr");
    }
    NS_FATAL_ERROR("unknown algorithm '" << a << "' (use reno, cubic or bbr)");
    return TypeId();
}

static std::vector<std::string>
Split(const std::string& s)
{
    std::vector<std::string> v;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ','))
    {
        if (!item.empty())
        {
            v.push_back(item);
        }
    }
    return v;
}

int
main(int argc, char* argv[])
{
    std::string algosStr = "cubic";
    std::string out = "results_ns3";
    std::string group = "manual";
    double bw = 50;  // Mbps
    double rtt = 50; // ms
    double loss = 0; // %
    double buf = 1;  // x BDP
    uint32_t run = 1;

    CommandLine cmd(__FILE__);
    cmd.AddValue("algos", "comma separated: reno,cubic,bbr (one entry per flow)", algosStr);
    cmd.AddValue("bw", "bottleneck bandwidth in Mbps", bw);
    cmd.AddValue("rtt", "round trip time in ms", rtt);
    cmd.AddValue("loss", "random packet loss in percent", loss);
    cmd.AddValue("buf", "bottleneck buffer in multiples of the BDP", buf);
    cmd.AddValue("duration", "flow duration in seconds", g_duration);
    cmd.AddValue("run", "run number (random seed)", run);
    cmd.AddValue("group", "scenario group label", group);
    cmd.AddValue("out", "output folder", out);
    cmd.Parse(argc, argv);

    std::vector<std::string> algos = Split(algosStr);
    const uint32_t n = algos.size();
    NS_ABORT_MSG_IF(n == 0 || n > 8, "need 1..8 algorithms");

    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(run);

    // TCP defaults chosen to resemble a Linux host
    Config::SetDefault("ns3::TcpSocket::SegmentSize", UintegerValue(MSS));
    Config::SetDefault("ns3::TcpSocket::SndBufSize", UintegerValue(1 << 24));
    Config::SetDefault("ns3::TcpSocket::RcvBufSize", UintegerValue(1 << 24));
    Config::SetDefault("ns3::TcpSocket::InitialCwnd", UintegerValue(10));
    Config::SetDefault("ns3::TcpSocketBase::MinRto", TimeValue(MilliSeconds(200)));

    // scenario id: identical format to common/scenarios.py
    std::ostringstream idss;
    for (uint32_t i = 0; i < n; i++)
    {
        idss << (i ? "-" : "") << algos[i];
    }
    idss << "_bw" << bw << "_rtt" << rtt << "_loss" << loss << "_buf" << buf;
    const std::string sid = idss.str();

    // ---------------------------------------------------------------- topology
    NodeContainer senders;
    senders.Create(n);
    NodeContainer routers;
    routers.Create(2);
    NodeContainer receiver;
    receiver.Create(1);

    InternetStackHelper stack;
    stack.Install(senders);
    stack.Install(routers);
    stack.Install(receiver);

    // congestion control per sender node
    for (uint32_t i = 0; i < n; i++)
    {
        std::ostringstream path;
        path << "/NodeList/" << senders.Get(i)->GetId() << "/$ns3::TcpL4Protocol/SocketType";
        Config::Set(path.str(), TypeIdValue(AlgoType(algos[i])));
    }

    PointToPointHelper access;
    access.SetDeviceAttribute("DataRate", StringValue("1Gbps"));
    access.SetChannelAttribute("Delay", TimeValue(Seconds(rtt / 2000.0)));

    PointToPointHelper bottleneck;
    bottleneck.SetDeviceAttribute("DataRate",
                                  DataRateValue(DataRate(static_cast<uint64_t>(bw * 1e6))));
    bottleneck.SetChannelAttribute("Delay", StringValue("1us"));
    // the real buffer is the queue disc below, so the device queue is kept minimal
    bottleneck.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", StringValue("1p"));

    PointToPointHelper egress;
    egress.SetDeviceAttribute("DataRate", StringValue("1Gbps"));
    egress.SetChannelAttribute("Delay", StringValue("1us"));

    Ipv4AddressHelper ipv4;
    for (uint32_t i = 0; i < n; i++)
    {
        NetDeviceContainer d = access.Install(senders.Get(i), routers.Get(0));
        std::ostringstream net;
        net << "10.1." << (i + 1) << ".0";
        ipv4.SetBase(net.str().c_str(), "255.255.255.0");
        ipv4.Assign(d);
    }

    // bottleneck: queue disc must be installed before addresses are assigned
    NetDeviceContainer bdev = bottleneck.Install(routers.Get(0), routers.Get(1));
    const double bdpBytes = bw * 1e6 / 8.0 * rtt / 1000.0;
    const uint32_t limitBytes = static_cast<uint32_t>(std::max(bdpBytes * buf, 3.0 * 1500));
    TrafficControlHelper tch;
    tch.SetRootQueueDisc("ns3::FifoQueueDisc",
                         "MaxSize",
                         QueueSizeValue(QueueSize(QueueSizeUnit::BYTES, limitBytes)));
    tch.Install(bdev.Get(0));
    ipv4.SetBase("10.2.1.0", "255.255.255.0");
    ipv4.Assign(bdev);

    if (loss > 0)
    {
        Ptr<RateErrorModel> em = CreateObject<RateErrorModel>();
        em->SetAttribute("ErrorRate", DoubleValue(loss / 100.0));
        em->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
        bdev.Get(1)->SetAttribute("ReceiveErrorModel", PointerValue(em)); // data direction only
    }

    NetDeviceContainer edev = egress.Install(routers.Get(1), receiver.Get(0));
    ipv4.SetBase("10.3.1.0", "255.255.255.0");
    Ipv4InterfaceContainer eif = ipv4.Assign(edev);
    const Ipv4Address rcvAddr = eif.GetAddress(1);

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();

    // ---------------------------------------------------------------- applications
    g_flows.assign(n, Flow());
    for (uint32_t i = 0; i < n; i++)
    {
        Flow& f = g_flows[i];
        f.id = i + 1;
        f.algo = algos[i];
        f.port = BASE_PORT + i;

        PacketSinkHelper sinkHelper("ns3::TcpSocketFactory",
                                    InetSocketAddress(Ipv4Address::GetAny(), f.port));
        ApplicationContainer sinkApp = sinkHelper.Install(receiver.Get(0));
        sinkApp.Start(Seconds(0));
        sinkApp.Stop(Seconds(g_start + g_duration + 1));
        f.sink = DynamicCast<PacketSink>(sinkApp.Get(0));

        BulkSendHelper bulk("ns3::TcpSocketFactory", InetSocketAddress(rcvAddr, f.port));
        bulk.SetAttribute("MaxBytes", UintegerValue(0));
        bulk.SetAttribute("SendSize", UintegerValue(65536));
        ApplicationContainer sendApp = bulk.Install(senders.Get(i));
        // flows start 1 ms apart so the pacing default can be switched per flow, deterministically
        const double startAt = g_start + 0.001 * i;
        Simulator::Schedule(Seconds(startAt - 0.0005), &SetPacingDefault, algos[i] == "bbr");
        sendApp.Start(Seconds(startAt));
        sendApp.Stop(Seconds(g_start + g_duration));
        f.app = DynamicCast<BulkSendApplication>(sendApp.Get(0));
    }

    FlowMonitorHelper fmHelper;
    Ptr<FlowMonitor> monitor = fmHelper.InstallAll();

    // ---------------------------------------------------------------- output files
    std::filesystem::create_directories(out + "/timeseries");
    std::filesystem::create_directories(out + "/parts");
    const std::string tag = sid + "_run" + std::to_string(run);
    g_ts.open(out + "/timeseries/" + tag + ".csv");
    g_ts << "t,flow,algo,cwnd,rtt_ms,delivery_mbps\n";

    Simulator::Schedule(Seconds(g_start + 0.01), &ConnectTraces);
    Simulator::Schedule(Seconds(g_start + g_interval), &Sample);
    Simulator::Stop(Seconds(g_start + g_duration));
    Simulator::Run();

    // ---------------------------------------------------------------- results
    g_ts.close();
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier = DynamicCast<Ipv4FlowClassifier>(fmHelper.GetClassifier());
    std::map<uint16_t, uint32_t> lost; // by destination port = data direction of each flow
    for (const auto& kv : monitor->GetFlowStats())
    {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(kv.first);
        if (t.protocol == 6 && t.destinationPort >= BASE_PORT && t.destinationPort < BASE_PORT + n)
        {
            lost[t.destinationPort] += kv.second.lostPackets;
        }
    }

    // one small file per run: safe when several simulations run in parallel
    std::ofstream part(out + "/parts/" + tag + ".csv");
    for (auto& f : g_flows)
    {
        double thr = f.sink->GetTotalRx() * 8.0 / g_duration / 1e6;
        double meanRtt = f.rttN ? f.rttSum / f.rttN : 0.0;
        double minRtt = f.rttN ? f.rttMin : 0.0;
        part << std::defaultfloat << group << "," << sid << "," << run << "," << f.id << "," << f.algo
             << "," << n << "," << bw << "," << rtt << "," << loss << "," << buf << "," << std::fixed
             << std::setprecision(3) << thr << "," << lost[f.port] << "," << meanRtt << "," << minRtt
             << "," << f.rttMax << "\n";
        std::cout << sid << " run" << run << " flow" << f.id << " (" << f.algo << "): " << std::fixed
                  << std::setprecision(2) << thr << " Mbps" << std::endl;
    }
    part.close();

    Simulator::Destroy();
    return 0;
}
