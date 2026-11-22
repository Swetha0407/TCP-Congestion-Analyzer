# Custom WSL2 kernel (only if preflight says BLOCKED)

The Mininet/iPerf3 module needs the Linux kernel to provide **BBR** (`tcp_bbr`), **netem** and **tbf**
(traffic control). The stock WSL2 kernel (6.6.87.2-microsoft-standard-WSL2) may or may not ship them -
this was not verifiable when the project was built. Run `sudo python3 scripts/preflight.py` first;
only follow this guide if it reports a missing feature.

## 1. Build a kernel (Ubuntu terminal)
```bash
sudo apt install -y build-essential flex bison libssl-dev libelf-dev bc dwarves python3
git clone --depth 1 -b linux-msft-wsl-6.6.y https://github.com/microsoft/WSL2-Linux-Kernel.git
cd WSL2-Linux-Kernel
cp Microsoft/config-wsl .config
scripts/config --enable NET_SCH_NETEM --enable NET_SCH_TBF --enable TCP_CONG_BBR --enable NET_SCH_FQ --enable NET_SCH_HTB
make olddefconfig
make -j$(nproc) KCONFIG_CONFIG=.config
```
(Use `=m` instead of `--enable` if you prefer modules; then also run `sudo make modules_install`.)

## 2. Point WSL at it (Windows side)
Copy `arch/x86/boot/bzImage` to e.g. `C:\wsl-kernel\bzImage`, then edit `%UserProfile%\.wslconfig`:
```
[wsl2]
kernel=C:\\wsl-kernel\\bzImage
```
In PowerShell: `wsl --shutdown`, then reopen Ubuntu.

## 3. Verify
```bash
uname -r
sudo python3 scripts/preflight.py
```
To undo: remove the `kernel=` line, `wsl --shutdown`.
