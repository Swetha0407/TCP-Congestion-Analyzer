#!/usr/bin/env bash
# Download (if needed), configure and build NS-3 3.46.1 with ONLY the modules this project uses.
# Run in the Ubuntu (WSL2) terminal:   bash scripts/build_ns3.sh
# Environment overrides:
#   NS3_DIR=~/ns-3.46.1        where NS-3 lives / will be unpacked
#   NS3_TARBALL=/path/file     use a tarball you already downloaded (skips the download)
#   JOBS=4                     parallel build jobs (default: number of CPUs)
set -euo pipefail

VERSION="3.46.1"
NS3_DIR="${NS3_DIR:-$HOME/ns-$VERSION}"
URL="https://www.nsnam.org/releases/ns-$VERSION.tar.bz2"
JOBS="${JOBS:-$(nproc)}"
MODULES="core,network,internet,point-to-point,applications,traffic-control,flow-monitor"

if [ ! -x "$NS3_DIR/ns3" ]; then
  TARBALL="${NS3_TARBALL:-$HOME/ns-$VERSION.tar.bz2}"
  if [ ! -f "$TARBALL" ]; then
    echo "Downloading $URL"
    curl -fL --retry 3 -o "$TARBALL" "$URL" || {
      echo "Download failed. Download ns-$VERSION.tar.bz2 manually from https://www.nsnam.org/releases/"
      echo "and rerun with:  NS3_TARBALL=/path/to/ns-$VERSION.tar.bz2 bash scripts/build_ns3.sh"
      exit 1
    }
  fi
  echo "Unpacking $TARBALL"
  mkdir -p "$NS3_DIR"
  tar xjf "$TARBALL" -C "$NS3_DIR" --strip-components=1
fi

cd "$NS3_DIR"
if [ -f VERSION ]; then echo "NS-3 version file says: $(cat VERSION)"; fi

# optimized profile: fast simulations, no -Werror surprises; only the modules we need
./ns3 configure -d optimized --disable-examples --disable-tests --enable-modules="$MODULES"
./ns3 build -j "$JOBS"

echo
echo "NS-3 is built in $NS3_DIR"
echo "Next:  python3 ns3/run_ns3_matrix.py --quick    (it copies and builds tcp_variants.cc itself)"
