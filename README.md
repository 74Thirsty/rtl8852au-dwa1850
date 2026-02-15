<p align="center">
  <img src="https://img.shields.io/badge/chipset-RTL8852AU%20/%20RTL8832AU-0078D4?style=for-the-badge" />
  <img src="https://img.shields.io/badge/kernel-6.18+-FCC624?style=for-the-badge&logo=linux&logoColor=black" />
  <img src="https://img.shields.io/badge/WiFi_6-802.11ax-00e5a0?style=for-the-badge&logo=wifi&logoColor=white" />
  <img src="https://img.shields.io/badge/speed-AX1800-ff6b35?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-GPL--2.0-blue?style=for-the-badge" />
</p>

<h1 align="center">RTL8852AU Linux Driver</h1>

<p align="center">
  <strong>Kernel 6.18+ patched &mdash; WiFi 6 USB driver that actually compiles on modern Linux.</strong><br>
  Out-of-tree driver for Realtek RTL8852AU / RTL8832AU chipsets with 7 targeted kernel compatibility patches.
</p>

---

## Why This Fork Exists

The original [lwfinger/rtl8852au](https://github.com/lwfinger/rtl8852au) driver (v1.15.0.1) **does not compile** on Linux kernel 6.18 and newer. The kernel introduced multiple breaking API changes — renamed functions, removed macros, changed subsystem signatures, and deprecated build flags — causing the build to fail with dozens of errors.

No upstream fix exists. This fork applies **7 targeted patches** developed by [WimLee115](https://github.com/WimLee115) that restore full compilation and functionality on kernel 6.18+ without altering driver behavior.

---

## Patches Applied

| # | Patch | Details |
|---|-------|---------|
| 1 | **Kbuild flags** | `EXTRA_CFLAGS` → `ccflags-y` across all makefiles (Makefile, common.mk, phl.mk, platform/i386_pc.mk, rtl8852a.mk). Kernel 6.18 dropped `EXTRA_CFLAGS` support — all include paths were silently ignored. |
| 2 | **Linker flags** | `EXTRA_LDFLAGS` → `ldflags-y` — same deprecation for linker flags. |
| 3 | **Timer header** | Added `#include <linux/timer.h>` in `osdep_service_linux.h`. Timer API declarations moved to a dedicated header in 6.x. |
| 4 | **Timer API rename** | `del_timer_sync()` → `timer_delete_sync()`, `del_timer()` → `timer_delete()`. Functions renamed in kernel 6.x series. |
| 5 | **Timer macro removal** | `from_timer()` → `container_of()`. The convenience macro was removed from the timer API. |
| 6 | **cfg80211 MLO signatures** | Updated cfg80211_ops function signatures with new `radio_idx` and `link_id` parameters. The WiFi subsystem added Multi-Link Operation (MLO) support in 6.18, changing all cfg80211 callback signatures. |
| 7 | **Symbol conflict** | `hmac_sha256` → `rtw_hmac_sha256` (+ vector/kdf variants). Kernel 6.18 exports its own `hmac_sha256`, causing linker conflicts with the driver's internal crypto implementation. |

**Bonus:** Removed in-function `MODULE_IMPORT_NS(VFS_internal...)` calls that became invalid when the macro changed to a file-scope static declaration.

### Firmware Compression

The 35 MB firmware source file (`hal8852a_fw.c`) is shipped as an **821 KB xz-compressed archive** to keep the repository under GitHub's file size limits. The Makefile automatically decompresses it on first build — no manual steps required.

---

## Supported Devices

| USB ID | Device | Chipset |
|--------|--------|---------|
| `2357:013F` | **TP-Link Archer TX20U Plus** | RTL8852AU |
| `2357:0140` | TP-Link Archer TX20U Plus v2 | RTL8852AU |
| `2357:0141` | TP-Link Archer TX20U Plus v3 | RTL8852AU |
| `0BDA:8832` | Realtek RTL8832AU / ipTIME AX2000U | RTL8832AU |
| `0BDA:885A` | Realtek RTL8852AU reference | RTL8852AU |
| `0BDA:885C` | Fenvi FU-AX1800P | RTL8852AU |
| `0B05:1A62` | ASUS USB-AX56 (no cradle) | RTL8852AU |
| `0B05:1997` | ASUS USB-AX56 | RTL8852AU |
| `2001:3321` | D-Link DWA-X1850 | RTL8852AU |
| `2001:0141` | D-Link adapter variant | RTL8852AU |
| `0411:0312` | Buffalo WI-U3-1200AX2(/N) | RTL8852AU |
| `056E:4020` | Elecom WDC-X1201DU3 | RTL8852AU |
| `35BC:0100` | EDUP EP-AX1696GS | RTL8852AU |

---

## Quick Install

### Prerequisites

```bash
# Debian / Ubuntu / Kali
sudo apt install build-essential bc dkms linux-headers-$(uname -r) xz-utils

# Fedora
sudo dnf install kernel-devel kernel-headers gcc make bc xz

# Arch / Manjaro
sudo pacman -S base-devel linux-headers bc xz
```

### Build & Install

```bash
git clone https://github.com/WimLee115/rtl8852au-build.git
cd rtl8852au-build
make -j$(nproc)
sudo make install
sudo modprobe 8852au
```

The firmware is automatically decompressed during the first build.

### Verify

```bash
lsmod | grep 8852au
iw dev
```

You should see a new `wlanX` interface listed.

---

## DKMS Install (Recommended)

DKMS automatically rebuilds the module on kernel updates, so your WiFi adapter keeps working after every upgrade.

```bash
git clone https://github.com/WimLee115/rtl8852au-build.git
sudo cp -r rtl8852au-build /usr/src/8852au-1.15.0.1
sudo dkms add -m 8852au -v 1.15.0.1
sudo dkms build -m 8852au -v 1.15.0.1
sudo dkms install -m 8852au -v 1.15.0.1
sudo modprobe 8852au
```

**Remove DKMS module:**
```bash
sudo dkms remove 8852au/1.15.0.1 --all
sudo rm -rf /usr/src/8852au-1.15.0.1
```

---

## Monitor Mode

```bash
sudo ip link set wlan1 down
sudo iw dev wlan1 set type monitor
sudo ip link set wlan1 up

# Verify
iw dev wlan1 info   # type should show "monitor"
```

**Back to managed mode:**
```bash
sudo ip link set wlan1 down
sudo iw dev wlan1 set type managed
sudo ip link set wlan1 up
```

### Supported Modes

| Mode | Status |
|------|--------|
| Managed (Station) | Working |
| Monitor | Working |
| AP (Access Point) | Working |
| AP/VLAN | Working |
| P2P-Client / P2P-GO | Working |

---

## Hardware Specs

| | |
|---|---|
| **Standard** | 802.11ax (WiFi 6) |
| **Speed** | AX1800 — 574 Mbps (2.4 GHz) + 1201 Mbps (5 GHz) |
| **Bands** | Dual-band 2.4 GHz / 5 GHz |
| **Chipset** | Realtek RTL8852AU / RTL8832AU |
| **Interface** | USB 3.0 |
| **Module name** | `8852au.ko` |
| **Base driver version** | v1.15.0.1 |

---

## Tested On

| Distribution | Kernel | Status |
|--------------|--------|--------|
| Kali Linux Rolling 2026.x | 6.18.9+kali-amd64 | Working |

Tested on other distros or kernel versions? Open an issue or PR to add your setup.

---

## D-Link DWA-X1850 USB Modeswitch

The DWA-X1850 initially enumerates as `0bda:1a2b` (a USB mass storage device containing the Windows driver). Add this udev rule to auto-switch to WiFi mode:

```
# /usr/lib/udev/rules.d/40-usb_modeswitch.rules
ATTR{idVendor}=="0bda", ATTR{idProduct}=="1a2b", RUN+="usb_modeswitch '/%k'"
```

---

## Troubleshooting

**Build fails on kernel < 6.18**

This fork targets kernel 6.18 and newer. For older kernels, use the original upstream driver: [lwfinger/rtl8852au](https://github.com/lwfinger/rtl8852au).

**`bc: not found` during build**

```bash
sudo apt install bc         # Debian/Ubuntu/Kali
sudo dnf install bc         # Fedora
sudo pacman -S bc           # Arch
```

**`xz: not found` during build**

```bash
sudo apt install xz-utils   # Debian/Ubuntu/Kali
sudo dnf install xz         # Fedora
sudo pacman -S xz           # Arch
```

**Module loads but no network interface appears**

Check for conflicting drivers:
```bash
lsmod | grep -E "rtw89|rtw88|8852"
sudo rmmod <conflicting_module>
sudo modprobe 8852au
```

**Secure Boot blocks unsigned module**

Either disable Secure Boot in BIOS/UEFI, or sign the module:
```bash
make -j$(nproc)
sudo make sign-install
```
You'll be prompted for a MOK password — remember it for the enrollment screen on next reboot.

---

## Uninstall

```bash
cd rtl8852au-build
sudo make uninstall
```

---

## Credits

This driver exists thanks to the work of:

- **[Larry Finger (lwfinger)](https://github.com/lwfinger)** — Original RTL8852AU Linux driver development and long-standing maintenance of Realtek wireless drivers for the Linux community. His years of work making Realtek chipsets usable on Linux are the foundation this project builds on.

- **Realtek Semiconductor Corp.** — Base driver source code (v1.15.0.1).

- **[morrownr](https://github.com/morrownr)** — Community driver documentation, maintenance patterns, and USB ID references that served as valuable upstream reference material.

- **[WimLee115](https://github.com/WimLee115)** — Kernel 6.18+ compatibility patches. Developed, tested, and maintains the 7 targeted patches that make this driver compile and function on modern Linux kernels where the upstream source fails to build.

---

## License

GPL-2.0 — as required by the Linux kernel module licensing terms. See [LICENSE](LICENSE) for details.
