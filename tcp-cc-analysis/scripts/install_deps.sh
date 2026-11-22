#!/usr/bin/env bash
# Install ONLY the missing apt packages. Nothing is upgraded, downgraded or reconfigured.
# Run in the Ubuntu (WSL2) terminal:   bash scripts/install_deps.sh
#   --dry-run   show what would be installed and exit
set -euo pipefail

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

# package -> reason
declare -A PKGS=(
  [mininet]="network emulation"
  [iperf3]="traffic generator (kernel TCP, -C selects the algorithm)"
  [iproute2]="tc / ip / ss"
  [iputils-ping]="connectivity check"
  [net-tools]="ifconfig (used by Mininet)"
  [ethtool]="disable NIC offloads"
  [tcpdump]="packet capture"
  [tshark]="packet analysis (command line Wireshark)"
  [python3-venv]="virtual environment for the dashboard"
  [python3-numpy]="analysis"
  [python3-pandas]="analysis"
  [python3-matplotlib]="graphs"
  [build-essential]="g++ to build NS-3"
  [cmake]="NS-3 build system"
  [ninja-build]="faster NS-3 builds"
  [pkg-config]="NS-3 build"
  [curl]="download NS-3"
  [bzip2]="unpack NS-3"
)

MISSING=()
for p in "${!PKGS[@]}"; do
  if ! dpkg -s "$p" >/dev/null 2>&1; then MISSING+=("$p"); fi
done

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "All required apt packages are already installed. Nothing to do."
  exit 0
fi

echo "Missing packages:"
for p in "${MISSING[@]}"; do echo "  - $p  (${PKGS[$p]})"; done
[ "$DRY" = 1 ] && exit 0

echo
echo "Installing (sudo password may be requested)..."
# tshark asks "allow non-root capture?" - answer no (we capture as root inside Mininet)
echo "wireshark-common wireshark-common/install-setuid boolean false" | sudo debconf-set-selections
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING[@]}"
echo
echo "Done. Next: bash scripts/setup_venv.sh   then   sudo python3 scripts/preflight.py"
