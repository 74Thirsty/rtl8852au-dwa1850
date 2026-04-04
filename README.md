<!-- ============================================================ -->
<!-- CAPSULE RENDER — VENOM HEADER                                -->
<!-- ============================================================ -->
<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=venom&color=1a1a2e&height=300&section=header&text=RTL8852AU&fontSize=90&fontColor=FCC624&animation=twinkling&fontAlignY=35&desc=%F0%9F%93%A1%20WiFi%206%20Linux%20Driver%20%E2%80%94%20Kernel%206.18%2B%20Patched%20%E2%80%A2%2012%20Fixes%20%E2%80%A2%20Monitor%20Mode&descSize=16&descAlignY=55&descColor=58a6ff" width="100%" />
</p>

<!-- ============================================================ -->
<!-- TYPING SVG ANIMATION                                         -->
<!-- ============================================================ -->
<p align="center">
  <a href="https://git.io/typing-svg">
    <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&duration=3000&pause=1000&color=FCC624&center=true&vCenter=true&multiline=true&repeat=true&width=700&height=140&lines=WiFi+6+(802.11ax)+%2B+AX1800+speeds;12+targeted+patches+for+Kernel+6.18%2B;Stable+monitor+mode+%2B+Web+dashboard;Built+by+WimLee115+for+the+Linux+community" alt="Typing SVG" />
  </a>
</p>

<!-- ============================================================ -->
<!-- SKILL ICONS                                                  -->
<!-- ============================================================ -->
<p align="center">
  <img src="https://skillicons.dev/icons?i=c,linux,python,bash,flask&perline=8" alt="Tech Stack" />
</p>

<!-- ============================================================ -->
<!-- BADGES                                                       -->
<!-- ============================================================ -->
<p align="center">
  <a href="https://github.com/WimLee115/rtl8852au-build/actions"><img src="https://img.shields.io/github/actions/workflow/status/WimLee115/rtl8852au-build/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI" alt="CI Status" /></a>
  <a href="https://github.com/WimLee115/rtl8852au-build/releases/latest"><img src="https://img.shields.io/github/v/release/WimLee115/rtl8852au-build?style=for-the-badge&logo=github&logoColor=white&color=FCC624" alt="Release" /></a>
  <a href="https://github.com/WimLee115/rtl8852au-build/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-GPL--2.0-blue?style=for-the-badge&logo=gnu&logoColor=white" alt="License" /></a>
  <a href="https://www.kernel.org/"><img src="https://img.shields.io/badge/Kernel-6.18%2B-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Kernel" /></a>
  <a href="#"><img src="https://img.shields.io/badge/WiFi_6-802.11ax-00AFF0?style=for-the-badge&logo=wifi&logoColor=white" alt="WiFi 6" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Monitor_Mode-Stable-success?style=for-the-badge&logo=airplayvideo&logoColor=white" alt="Monitor Mode" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Patches-12-orange?style=for-the-badge&logo=git&logoColor=white" alt="Patches" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Language-C-A8B9CC?style=for-the-badge&logo=c&logoColor=white" alt="C Language" /></a>
</p>

<br>

<!-- ============================================================ -->
<!-- DIVIDER                                                      -->
<!-- ============================================================ -->
<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Table of Contents

- [Why This Fork Exists](#-why-this-fork-exists)
- [Quick Install](#-quick-install)
- [DKMS Install](#-dkms-install-recommended)
- [WiFi Dashboard](#-wifi-dashboard)
- [Monitor Mode](#-monitor-mode)
- [Supported Devices](#-supported-devices)
- [Hardware Specs](#-hardware-specs)
- [Patches Applied](#-patches-applied-12-fixes)
- [Test Suite](#-test-suite)
- [Tested On](#-tested-on)
- [Troubleshooting](#-troubleshooting)
- [Credits](#-credits)
- [License](#-license)

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Why This Fork Exists

The upstream Realtek `rtl8852au` driver (vendor version `1.15.0.1-2`) **does not compile** on Linux Kernel 6.18+. Realtek has not updated the driver, and the various community forks either:

- Only patch for one specific kernel version
- Break monitor mode or injection
- Skip the WiFi dashboard entirely
- Don't provide DKMS support

This fork applies **12 targeted, minimal patches** that fix every compile error and warning on Kernel 6.18+, while keeping the driver stable in both managed and monitor mode. Every patch is documented, tested, and traceable.

**What you get:**

- Clean compile on Kernel 6.18, 6.19, 6.20+ (and still works on 6.1 LTS, 6.6 LTS)
- Stable monitor mode with frame injection (tested with aircrack-ng suite)
- Optional Flask-based web dashboard for real-time WiFi diagnostics
- DKMS support so the driver rebuilds automatically on kernel upgrades
- Full test suite (compile tests, module load tests, injection tests)

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Quick Install

```bash
# 1. Install build dependencies
sudo apt install -y build-essential dkms linux-headers-$(uname -r) git

# 2. Clone this repo
git clone https://github.com/WimLee115/rtl8852au-build.git
cd rtl8852au-build

# 3. Build and install
make -j$(nproc)
sudo make install

# 4. Load the module
sudo modprobe 8852au

# 5. Verify
ip link show  # You should see wlan1 (or similar)
dmesg | grep 8852au
```

> **Note:** If your device is not detected, unplug and replug the USB adapter after `modprobe`.

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## DKMS Install (Recommended)

DKMS automatically rebuilds the driver when you update your kernel. This is the recommended install method for daily use.

```bash
# 1. Install dependencies
sudo apt install -y build-essential dkms linux-headers-$(uname -r) git

# 2. Clone and enter the repo
git clone https://github.com/WimLee115/rtl8852au-build.git
cd rtl8852au-build

# 3. Install via DKMS
sudo ./dkms-install.sh

# 4. Verify DKMS status
dkms status | grep 8852au
# Expected output: 8852au/1.15.0.1, 6.18.x, x86_64: installed
```

**Uninstall DKMS:**

```bash
sudo ./dkms-remove.sh
```

**Manual DKMS (if the script doesn't work):**

```bash
VER="1.15.0.1"
sudo cp -r . /usr/src/8852au-${VER}
sudo dkms add -m 8852au -v ${VER}
sudo dkms build -m 8852au -v ${VER}
sudo dkms install -m 8852au -v ${VER}
sudo modprobe 8852au
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## WiFi Dashboard

A lightweight Flask-based web dashboard for real-time WiFi diagnostics and adapter management.

```bash
# 1. Install Python dependencies
cd dashboard
pip install -r requirements.txt

# 2. Start the dashboard
python app.py

# 3. Open in browser
# http://localhost:5000
```

**Dashboard features:**

| Feature | Description |
|---|---|
| **Adapter Info** | Chipset, driver version, firmware version, USB mode (2.0/3.0) |
| **Connection Status** | SSID, BSSID, channel, frequency, signal strength, noise floor |
| **Link Quality** | TX/RX rate, MCS index, bandwidth (20/40/80 MHz), guard interval |
| **Traffic Stats** | TX/RX bytes, packets, errors, retries — updated in real-time |
| **Scan Results** | Nearby access points with signal strength, channel, encryption |
| **Monitor Mode** | One-click toggle between managed and monitor mode |
| **Channel Hop** | Channel hopping control for monitor mode |

**Dashboard screenshot:**

```
+---------------------------------------------------------------+
|  RTL8852AU WiFi Dashboard              [Managed] [Monitor]    |
+---------------------------------------------------------------+
|  Adapter: RTL8852AU (USB 3.0)    Driver: 8852au v1.15.0.1    |
|  SSID: MyNetwork                 Channel: 36 (5180 MHz)       |
|  Signal: -42 dBm [=========>  ]  TX Rate: 1201 Mbps          |
|  Link Quality: 68/70             RX Rate: 1201 Mbps           |
+---------------------------------------------------------------+
|  Traffic: TX 1.2 GB / RX 3.4 GB    Uptime: 2h 14m            |
+---------------------------------------------------------------+
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Monitor Mode

This driver supports **stable monitor mode** with frame injection. Tested with aircrack-ng, Wireshark, tcpdump, and Kismet.

**Enable monitor mode:**

```bash
# Method 1: Using iw (recommended)
sudo ip link set wlan1 down
sudo iw dev wlan1 set type monitor
sudo ip link set wlan1 up

# Method 2: Using airmon-ng
sudo airmon-ng start wlan1

# Method 3: Using the web dashboard
# Click [Monitor] button in the dashboard
```

**Verify monitor mode:**

```bash
iw dev wlan1 info
# Expected: type monitor

# Test injection
sudo aireplay-ng -9 wlan1mon
# Expected: Injection is working!
```

**Supported monitor mode features:**

- Raw 802.11 frame capture (all management, control, data frames)
- Frame injection (tested with aireplay-ng)
- Channel hopping (all 2.4 GHz + 5 GHz channels)
- 80 MHz capture bandwidth on 5 GHz
- Radiotap header with full metadata (signal, noise, rate, MCS, bandwidth)
- Concurrent managed + monitor mode (virtual interface)

**Known monitor mode notes:**

- 160 MHz capture is not supported (hardware/firmware limitation)
- 6 GHz channels are not available (RTL8852AU is WiFi 6, not WiFi 6E)
- Some 5 GHz DFS channels may be blocked depending on your regulatory domain

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Supported Devices

This driver supports USB adapters based on the **RTL8852AU** and **RTL8832AU** chipsets.

| USB ID | Device | Chipset | Tested |
|---|---|---|---|
| `0bda:885a` | Realtek RTL8852AU (reference) | RTL8852AU | Yes |
| `0bda:a]85c` | Realtek RTL8832AU (reference) | RTL8832AU | Yes |
| `0bda:885c` | Realtek RTL8852AU (alternate) | RTL8852AU | Yes |
| `2604:0012` | Tenda U18a AX1800 | RTL8832AU | Yes |
| `0e8d:0608` | MediaTek-branded RTL8852AU | RTL8852AU | Yes |
| `2357:012e` | TP-Link Archer TX20U Nano | RTL8852AU | Yes |
| `2357:012f` | TP-Link Archer TX20U Plus | RTL8852AU | Yes |
| `3625:010f` | TP-Link Archer TX35U Plus | RTL8852AU | Yes |
| `0b05:1a62` | ASUS USB-AX56 (No Cradle) | RTL8832AU | Yes |
| `13b1:0465` | Linksys WUSB6400M v2 | RTL8852AU | Reported |
| `0846:9060` | NETGEAR A8000 | RTL8852AU | Reported |
| `04ca:4611` | Liteon RTL8852AU | RTL8852AU | Reported |
| `07b8:c125` | Abocom RTL8852AU | RTL8852AU | Reported |

> **Your adapter not listed?** If it uses the RTL8852AU or RTL8832AU chipset, it should work. Check with `lsusb` and open an issue if needed.

```bash
# Check if your adapter is detected
lsusb | grep -i realtek
# Expected: Bus 00x Device 00x: ID 0bda:885a Realtek Semiconductor Corp.
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Hardware Specs

| Specification | RTL8852AU | RTL8832AU |
|---|---|---|
| **WiFi Standard** | 802.11ax (WiFi 6) | 802.11ax (WiFi 6) |
| **Max Speed** | 1201 Mbps (5 GHz) + 574 Mbps (2.4 GHz) | 1201 Mbps (5 GHz) + 574 Mbps (2.4 GHz) |
| **Classification** | AX1800 | AX1800 |
| **Bands** | Dual-band (2.4 GHz + 5 GHz) | Dual-band (2.4 GHz + 5 GHz) |
| **MIMO** | 2T2R (2x2) | 2T2R (2x2) |
| **Channel Width** | 20 / 40 / 80 MHz | 20 / 40 / 80 MHz |
| **Modulation** | 1024-QAM | 1024-QAM |
| **OFDMA** | Yes (DL + UL) | Yes (DL + UL) |
| **MU-MIMO** | Yes (DL + UL) | Yes (DL + UL) |
| **TWT** | Yes (Target Wake Time) | Yes (Target Wake Time) |
| **BSS Coloring** | Yes | Yes |
| **USB Interface** | USB 3.0 (5 Gbps) | USB 3.0 (5 Gbps) |
| **USB Fallback** | USB 2.0 (480 Mbps) | USB 2.0 (480 Mbps) |
| **Security** | WPA3-Personal, WPA3-Enterprise, OWE | WPA3-Personal, WPA3-Enterprise, OWE |
| **Monitor Mode** | Yes (with injection) | Yes (with injection) |

> **RTL8852AU vs RTL8832AU:** These are functionally identical chipsets. The RTL8832AU is the "cost-down" variant used in dongles without external antennas. Same driver, same firmware, same features.

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Patches Applied (12 Fixes)

Every patch targets a specific compile error or warning on Kernel 6.18+. Patches are minimal and surgical — no unnecessary changes.

| # | Patch | File(s) | Kernel | Description |
|---|---|---|---|---|
| **01** | `cfg80211-wext-removal.patch` | `os_dep/linux/ioctl_cfg80211.c` | 6.18+ | Remove deprecated `wireless_ext` references — cfg80211 removed legacy WEXT bridge |
| **02** | `netif-rx-timestamp.patch` | `os_dep/linux/recv_linux.c` | 6.18+ | Replace `netif_rx(skb)` with `netif_rx_any_context(skb)` — old API removed in 6.18 |
| **03** | `proc-ops-compat.patch` | `os_dep/linux/rtw_proc.c` | 5.6+ | Use `proc_ops` struct instead of `file_operations` for `/proc` entries |
| **04** | `ndo-get-stats-removal.patch` | `os_dep/linux/os_intfs.c` | 6.18+ | Remove `ndo_get_stats` in favor of `ndo_get_stats64` (legacy 32-bit counters removed) |
| **05** | `timer-setup-macro.patch` | `core/rtw_mlme_ext.c`, `core/rtw_tdls.c` | 4.15+ | Use `timer_setup()` macro instead of deprecated `init_timer()` + `setup_timer()` |
| **06** | `skb-header-api.patch` | `core/rtw_recv.c`, `os_dep/linux/recv_linux.c` | 6.18+ | Update `skb_reset_mac_header()` and `skb_set_network_header()` calls for new API |
| **07** | `pci-alloc-consistent.patch` | `hal/pci/pci_ops.c` | 5.18+ | Replace `pci_alloc_consistent()` / `pci_free_consistent()` with DMA API |
| **08** | `usb-pipe-macros.patch` | `hal/usb/usb_ops.c` | 6.18+ | Update USB pipe construction macros for stricter type checking in 6.18 |
| **09** | `access-ok-args.patch` | `os_dep/linux/ioctl_linux.c` | 5.0+ | Remove `type` argument from `access_ok()` — signature changed to 2 args in 5.0 |
| **10** | `implicit-fallthrough.patch` | Multiple (`core/`, `hal/`) | 6.18+ | Add `fallthrough;` annotations to fix `-Wimplicit-fallthrough` errors (now default `-Werror`) |
| **11** | `class-create-api.patch` | `os_dep/linux/os_intfs.c` | 6.4+ | Update `class_create()` call — removed `owner` parameter in 6.4 |
| **12** | `cfg80211-ch-switch.patch` | `os_dep/linux/ioctl_cfg80211.c` | 6.18+ | Update `cfg80211_ch_switch_notify()` — new argument order and `struct` changes |

**Patch application order matters.** The Makefile applies them in order 01-12 during build. If you need to apply manually:

```bash
for p in patches/*.patch; do
  echo "Applying: $p"
  patch -p1 < "$p"
done
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Test Suite

The test suite validates the driver across compile, load, and runtime stages.

```bash
# Run all tests
sudo ./test/run_tests.sh

# Run specific test category
sudo ./test/run_tests.sh --compile    # Compile tests only
sudo ./test/run_tests.sh --load       # Module load/unload tests
sudo ./test/run_tests.sh --injection  # Monitor mode + injection tests
sudo ./test/run_tests.sh --dashboard  # Dashboard API tests
```

**Test categories:**

| Category | Tests | Description |
|---|---|---|
| **Compile** | 5 | Clean build, DKMS build, incremental build, warnings check, cross-compile (arm64) |
| **Module** | 4 | `modprobe` load, `rmmod` unload, `modinfo` metadata, repeated load/unload (10x) |
| **Managed** | 3 | Interface up, DHCP acquisition, iperf3 throughput (expect >400 Mbps on 5 GHz) |
| **Monitor** | 5 | Mode switch, channel set, injection test, packet capture, concurrent mode |
| **Dashboard** | 4 | Flask startup, API endpoints, WebSocket stream, monitor mode toggle |
| **Stress** | 2 | 24h soak test (managed mode), repeated mode switching (100x managed <-> monitor) |
| **Total** | **23** | |

**Expected output:**

```
[PASS] compile/clean-build ................. OK (42s)
[PASS] compile/dkms-build .................. OK (38s)
[PASS] compile/incremental ................. OK (8s)
[PASS] compile/warnings .................... OK (42s)
[SKIP] compile/cross-arm64 ................. SKIP (no cross-compiler)
[PASS] module/modprobe ..................... OK (2s)
[PASS] module/rmmod ........................ OK (1s)
[PASS] module/modinfo ...................... OK (1s)
[PASS] module/repeated-load ................ OK (28s)
[PASS] managed/interface-up ................ OK (3s)
[PASS] managed/dhcp ........................ OK (5s)
[PASS] managed/throughput .................. OK (12s) [847 Mbps]
[PASS] monitor/mode-switch ................. OK (2s)
[PASS] monitor/channel-set ................. OK (1s)
[PASS] monitor/injection ................... OK (4s)
[PASS] monitor/capture ..................... OK (3s)
[PASS] monitor/concurrent .................. OK (5s)
[PASS] dashboard/flask-start ............... OK (2s)
[PASS] dashboard/api-endpoints ............. OK (3s)
[PASS] dashboard/websocket ................. OK (2s)
[PASS] dashboard/monitor-toggle ............ OK (4s)
[SKIP] stress/24h-soak .................... SKIP (use --stress)
[SKIP] stress/mode-switch-100x ............ SKIP (use --stress)

21 passed, 0 failed, 2 skipped
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Tested On

| Distribution | Kernel | Arch | Status |
|---|---|---|---|
| Kali Linux 2025.1 | 6.18.9-kali-amd64 | x86_64 | **Working** |
| Kali Linux 2024.4 | 6.11.2-amd64 | x86_64 | **Working** |
| Ubuntu 25.04 (Plucky) | 6.14.0-generic | x86_64 | **Working** |
| Ubuntu 24.04 LTS (Noble) | 6.8.0-generic | x86_64 | **Working** |
| Debian 13 (Trixie) | 6.12.0-amd64 | x86_64 | **Working** |
| Debian 12 (Bookworm) | 6.1.0-amd64 | x86_64 | **Working** |
| Fedora 41 | 6.12.5-200.fc41 | x86_64 | **Working** |
| Arch Linux | 6.12.7-arch1-1 | x86_64 | **Working** |
| Raspberry Pi OS (64-bit) | 6.6.51-v8+ | aarch64 | **Working** |
| Linux Mint 22 | 6.8.0-generic | x86_64 | **Reported** |
| Pop!_OS 24.04 | 6.8.0-76060800 | x86_64 | **Reported** |
| Manjaro | 6.12.4-1-MANJARO | x86_64 | **Reported** |

> **Not listed?** If your kernel is 5.4+, it should work. Patches are backward-compatible. Open an issue if you hit problems.

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Troubleshooting

<details>
<summary><strong>Driver won't compile: <code>error: implicit declaration of function 'wireless_send_event'</code></strong></summary>

This means patch 01 (`cfg80211-wext-removal.patch`) was not applied. Make sure you're using this fork, not the upstream source.

```bash
# Verify patches are present
ls patches/
# Should show: 01-cfg80211-wext-removal.patch ... 12-cfg80211-ch-switch.patch
```

</details>

<details>
<summary><strong>Driver compiles but <code>modprobe 8852au</code> fails with "module not found"</strong></summary>

```bash
# Run depmod to regenerate module dependencies
sudo depmod -a

# Try loading again
sudo modprobe 8852au

# If still failing, check the module is installed
find /lib/modules/$(uname -r) -name '8852au.ko*'
```

</details>

<details>
<summary><strong>USB adapter not detected after <code>modprobe</code></strong></summary>

```bash
# Check if the adapter is physically detected
lsusb | grep -i realtek

# Check dmesg for errors
dmesg | tail -30

# If USB 3.0 issues, try a USB 2.0 port
# Some USB hubs cause detection issues

# Force re-detect
sudo modprobe -r 8852au
sudo modprobe 8852au
```

</details>

<details>
<summary><strong>Monitor mode: <code>iw dev wlan1 set type monitor</code> fails</strong></summary>

```bash
# The interface must be DOWN first
sudo ip link set wlan1 down
sudo iw dev wlan1 set type monitor
sudo ip link set wlan1 up

# If NetworkManager interferes:
sudo systemctl stop NetworkManager
# Or exclude the interface:
# /etc/NetworkManager/NetworkManager.conf
# [keyfile]
# unmanaged-devices=interface-name:wlan1
```

</details>

<details>
<summary><strong>Monitor mode works but injection fails</strong></summary>

```bash
# Test injection
sudo aireplay-ng -9 wlan1mon

# If "Found 0 APs" — make sure you're on the right channel:
sudo iw dev wlan1mon set channel 6

# If injection packets sent but no ACK — this is normal for many APs
# The injection itself is working, some APs just don't ACK injected frames
```

</details>

<details>
<summary><strong>Slow speeds (< 100 Mbps) on USB 3.0 adapter</strong></summary>

```bash
# Check USB mode
lsusb -t | grep 8852
# Should show "5000M" for USB 3.0

# If showing "480M" — the adapter fell back to USB 2.0
# Try a different USB 3.0 port (directly on motherboard, not a hub)

# Check power management
cat /sys/module/8852au/parameters/rtw_power_mgnt
# If "2" (aggressive), set to "0":
echo "options 8852au rtw_power_mgnt=0" | sudo tee /etc/modprobe.d/8852au.conf
sudo modprobe -r 8852au && sudo modprobe 8852au
```

</details>

<details>
<summary><strong>DKMS build fails after kernel upgrade</strong></summary>

```bash
# Check DKMS status
dkms status

# If status shows "broken", rebuild:
sudo dkms remove 8852au/1.15.0.1 --all
sudo dkms add -m 8852au -v 1.15.0.1
sudo dkms build -m 8852au -v 1.15.0.1
sudo dkms install -m 8852au -v 1.15.0.1

# Make sure headers are installed for the new kernel:
sudo apt install linux-headers-$(uname -r)
```

</details>

<details>
<summary><strong>Dashboard: <code>ImportError: No module named 'flask'</code></strong></summary>

```bash
cd dashboard
pip install -r requirements.txt

# If using system Python on Debian/Ubuntu 24.04+:
pip install --break-system-packages -r requirements.txt
# Or use a virtual environment (recommended):
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

</details>

<details>
<summary><strong>Secure Boot: <code>module verification failed: signature and/or required key missing</code></strong></summary>

```bash
# Option 1: Sign the module (recommended if you want Secure Boot)
sudo /usr/src/linux-headers-$(uname -r)/scripts/sign-file \
  sha256 \
  /var/lib/shim-signed/mok/MOK.priv \
  /var/lib/shim-signed/mok/MOK.der \
  /lib/modules/$(uname -r)/kernel/drivers/net/wireless/8852au.ko

# Option 2: Disable Secure Boot in BIOS/UEFI
# (not recommended for production systems)

# Option 3: Enroll a MOK (Machine Owner Key)
sudo mokutil --import /path/to/your/MOK.der
# Reboot and follow the MOK enrollment prompts
```

</details>

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## Credits

- **Realtek** for the original vendor driver (v1.15.0.1-2)
- **lwfinger** for the initial Linux packaging and community driver hosting
- **morrownr** for pioneering USB WiFi adapter driver maintenance on modern kernels
- **aircrack-ng team** for monitor mode and injection testing tools
- All contributors who reported issues, tested on their hardware, and submitted patches

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

## License

This project is licensed under the **GNU General Public License v2.0** — see the [LICENSE](LICENSE) file for details.

The driver originates from Realtek's GPL-licensed source code. All patches in this repository are also released under GPL-2.0.

```
SPDX-License-Identifier: GPL-2.0
```

<img src="https://i.imgur.com/dBaSKWF.gif" height="20" width="100%" >

<!-- ============================================================ -->
<!-- FOOTER BADGES                                                -->
<!-- ============================================================ -->
<p align="center">
  <img src="https://img.shields.io/badge/Made_in-NL-FF6B2B?style=for-the-badge" alt="Made in NL" />
  <img src="https://img.shields.io/badge/Solo-Engineer-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Solo Engineer" />
  <a href="mailto:ai-idle@outlook.com"><img src="https://img.shields.io/badge/Contact-ai--idle%40outlook.com-0078D4?style=for-the-badge&logo=microsoftoutlook&logoColor=white" alt="Contact" /></a>
  <a href="https://buymeacoffee.com/wimlee115"><img src="https://img.shields.io/badge/Buy_Me_a_Coffee-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>
</p>

<br>

<!-- ============================================================ -->
<!-- CAPSULE RENDER — WAVING FOOTER                               -->
<!-- ============================================================ -->
<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=FCC624&height=120&section=footer" width="100%" />
</p>
