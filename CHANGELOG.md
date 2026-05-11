# Changelog

All notable changes to this fork are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
the Realtek vendor version `1.15.0.1` as its baseline and tracks fork-local
changes in this file.

## [Unreleased]

### Added
- `LICENSE` file (GNU GPL-2.0 full text).
- `dashboard/requirements.txt` pinning Flask.
- `dkms-install.sh` and `dkms-remove.sh` helper scripts (idempotent).
- `tests/run_tests.sh` wrapper around the Python test suite, with category flags.
- `tests/__init__.py` so the test module can be imported by `unittest -m`.
- `patches/` directory containing post-baseline fixes as standalone
  `git format-patch` files, plus `patches/README.md`.
- `.github/workflows/ci.yml` — build matrix (Ubuntu 22.04 + 24.04), DKMS dry-run,
  Python lint + offline tests.
- `.github/ISSUE_TEMPLATE/` — structured forms for bug reports and hardware
  support requests.
- `.github/dependabot.yml` — monthly updates for GitHub Actions and pip.
- `ruff.toml` — conservative Python lint config.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.
- `tools/README.md` — explicit authorised-testing-only disclaimer for the
  RTSP brute-force tool.

### Changed
- README "Supported Devices" table regenerated from
  `os_dep/linux/usb_intf.c` (the previous list contained USB IDs that were
  not in the driver).
- README "Test Suite" section rewritten to reflect the actual
  `tests/test_driver.py` classes and `tests/run_tests.sh` flags.
- README "Patches Applied" section clarifies that the 12 baseline patches
  are integrated; the `patches/` directory holds post-baseline fixes.
- README "Tested On" updated with kernel 6.19.14 (Kali Rolling 2026.1).
- `.gitignore` no longer ignores `patches/` (was matching quilt's pattern).

### Fixed
- **Build: kernel 6.17 incompatible-pointer-types (`patches/0008`).**
  The cfg80211 MLO refactor (`radio_idx` on `set_wiphy_params`,
  `set_tx_power`, `get_tx_power`; `struct net_device *` on
  `set_monitor_channel`) landed in 6.17, not 6.18. The four
  `LINUX_VERSION_CODE` guards in `os_dep/linux/ioctl_cfg80211.c` were
  lowered from `>= 6.18` to `>= 6.17` so CI builds on the Ubuntu 24.04
  runner (kernel 6.17.0-1010-azure) no longer fail with
  `incompatible pointer type` for `.set_wiphy_params`, `.set_tx_power`,
  `.get_tx_power` and `.set_monitor_channel` in `rtw_cfg80211_ops`.
- **Build: `tests/test_driver.py` and `dashboard/app.py` ruff lint.**
  Six F541 (`f`-prefixed strings without placeholders) and two B007
  (unused loop variable `i`) findings cleared so the `Ruff (lint)` job
  in CI passes.
- **Driver: kernel panic on rapid `ifup`/`ifdown` and `rmmod`-while-associated
  (`patches/0007`).** `netdev_open()` took `hw_init_mutex` but
  `netdev_close()` did not, so a rapid `ip link up/down` cycle could race
  `rtw_hw_iface_init` against an in-flight `rtw_hw_iface_deinit` on the
  same adapter — a use-after-free of HAL state. In addition,
  `rtw_disassoc_cmd(WAIT_ACK)` blocked the close path for up to 2 s ×
  N cmds while `rtw_dev_remove()` was in progress, leaving the cmd path
  alive while NetworkManager raced against partially-torn-down state.
  Fix: `netdev_close()` now takes `hw_init_mutex` symmetrically, returns
  early if the interface is already down, and skips the disassoc / scan
  cmd path (jumps straight to `rtw_hw_iface_deinit`) when
  `dev_is_surprise_removed()` or `processing_dev_remove` is set.
- **Test suite no longer panics the kernel.** `TestModuleReload` and
  `TestStability` previously issued `rmmod` and 10× rapid ifup/ifdown
  (200 ms cycle) against an actively-associated interface. The 200 ms
  cycle is shorter than the time `netdev_close()` needs to drain
  (`rtw_disassoc_cmd(WAIT_ACK)` ≈ 500 ms + `wait_scan_req_empty(200 ms)`),
  causing stacked close-paths to race against incoming open() calls and a
  concurrent NetworkManager reassociation — a hard kernel panic with no
  written traceback was observed on kernel 6.19.14. Fix:
  - Both destructive classes are now opt-in (`--destructive` /
    `RTW_TEST_DESTRUCTIVE=1`) and refuse to start unless wlan is
    disconnected and NetworkManager / wpa_supplicant are stopped.
  - `TestModuleReload` brings the interface down and waits 2 s before
    `rmmod`, letting `netdev_close()` finish cleanly.
  - `TestStability` toggle cadence raised from 200 ms to 1.5 s per
    half-cycle; scan triggers spaced 2 s apart.
  - `tests/run_tests.sh` adds a shell-level pre-flight that exits 2 with
    instructions if the system is unsafe; new `--reload`, `--stability`,
    `--all` flags make the destructive selection explicit.

## [1.15.0.1] — Baseline

Fork inception. Realtek vendor driver `1.15.0.1-2` with the 12 compile-time
patches required to build on Linux kernel 6.18+:

- `cfg80211-wext-removal` — drop deprecated `wireless_ext` references.
- `netif-rx-timestamp` — `netif_rx` → `netif_rx_any_context`.
- `proc-ops-compat` — `file_operations` → `proc_ops` for /proc entries.
- `ndo-get-stats-removal` — switch to `ndo_get_stats64`.
- `timer-setup-macro` — `init_timer` → `timer_setup`.
- `skb-header-api` — update `skb_*_header()` calls for new API.
- `pci-alloc-consistent` — `pci_alloc_consistent` → DMA API.
- `usb-pipe-macros` — stricter type-checked USB pipe macros for 6.18.
- `access-ok-args` — 2-arg `access_ok()` signature.
- `implicit-fallthrough` — add `fallthrough;` annotations.
- `class-create-api` — drop `owner` arg from `class_create()`.
- `cfg80211-ch-switch` — updated `cfg80211_ch_switch_notify` signature.

### Post-baseline fixes (carried in the `patches/` directory and the tree)
- UBSAN array-out-of-bounds + NULL deref in monitor mode.
- `ethtool` reporting `Speed: unknown` — added `get_link_ksettings`.
- Monitor mode hard freeze: SKB use-after-free in RX path.
- Monitor mode kernel panic under load: race condition + double-free.
- Build fix for kernel 6.8.
- USB ID `3625:010f` for TP-Link Archer TX35U Plus (PR #3, contributor: jsiwrk).
