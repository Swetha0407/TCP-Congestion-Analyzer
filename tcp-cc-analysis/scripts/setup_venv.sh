#!/usr/bin/env bash
# Create .venv for the analysis scripts and the Flask dashboard.
# The venv can see the system packages (--system-site-packages), so numpy / pandas / matplotlib from
# apt are reused as they are. Only a package that is MISSING is pip-installed, pinned to the reference version.
# The Mininet runner is NOT run from this venv: it uses the system python3 under sudo.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# module -> pinned version used when it must be installed
declare -A PINS=( [numpy]="2.3.5" [pandas]="2.3.3" [matplotlib]="3.10.7" [flask]="3.1.2" )
for mod in numpy pandas matplotlib flask; do
  if python - <<EOF 2>/dev/null
import importlib.metadata as m, sys
m.version("$mod")
EOF
  then
    echo "  [ok]       $mod $(python -c "import importlib.metadata as m; print(m.version('$mod'))")"
  else
    echo "  [install]  $mod==${PINS[$mod]}"
    pip install "$mod==${PINS[$mod]}"
  fi
done
echo
echo "Virtual environment ready. Activate it with:  source .venv/bin/activate"
