# Patches

This directory contains the post-baseline fixes and hardware additions that
have been applied on top of the initial commit (`2be21aaa`).

The baseline commit ("RTL8852AU driver v1.15.0.1 — patched for kernel 6.18+")
already incorporates the original 12 kernel-6.18 compatibility patches
described in the main README. Those patches modify the Realtek vendor source
to compile on modern kernels; they are integrated into the source tree
because they touch many files and are required for *any* build to succeed.

The patches below are independent, follow-up changes — bugfixes discovered
after the baseline and hardware-ID additions. Each file is a standard
`git format-patch` output and can be applied with `git am` or `patch -p1`.

## Index

| # | Patch | Type | Summary |
|---|---|---|---|
| 0001 | `monitor-fix-ubsan-array-oob-and-null-deref` | Bugfix | UBSAN array-out-of-bounds + NULL deref in monitor mode |
| 0002 | `ethtool-add-get_link_ksettings-to-report-speed` | Bugfix | `ethtool` was reporting `Speed: unknown` — added `get_link_ksettings` |
| 0003 | `monitor-fix-skb-use-after-free-in-rx-path` | Bugfix | Hard freeze in monitor mode caused by SKB use-after-free |
| 0004 | `monitor-fix-kernel-panic-race-and-double-free` | Bugfix | Kernel panic under load: race condition + double-free |
| 0005 | `build-fix-for-kernel-6.8` | Build | Compatibility shim for kernel 6.8 |
| 0006 | `hw-add-usb-id-3625-010f-tp-link-archer-tx35u-plus` | Hardware | USB ID `3625:010f` (TP-Link Archer TX35U Plus) |
| 0007 | `os-serialise-netdev-close-with-hw_init_mutex` | Bugfix | Kernel panic on rapid `ifup`/`ifdown` and `rmmod`-while-associated — `netdev_close()` now takes `hw_init_mutex` symmetrically with `netdev_open()` and skips the disassoc cmd path when the device is surprise-removed. **Hardware-verified** on TX20U Plus (Linux 6.19): 30× toggle @ 50 ms + rmmod-while-up = 198 ms clean unload, no panic |
| 0008 | `cfg80211-lower-mlo-signature-guards-to-6.17` | Build | Build failure on kernel 6.17 — the MLO refactor (`radio_idx`, `net_device *` on `set_monitor_channel`) landed in 6.17, not 6.18. Four `LINUX_VERSION_CODE` guards in `os_dep/linux/ioctl_cfg80211.c` lowered from `>= 6.18` to `>= 6.17` |

## Applying

These patches are already part of the current source tree. They are kept
here as historical record and for downstream maintainers who track only the
baseline:

```bash
# Against a checkout of the baseline (2be21aa):
for p in patches/*.patch; do
    git am "$p"
done

# Or, without git:
for p in patches/*.patch; do
    patch -p1 < "$p"
done
```

## Regenerating

```bash
git format-patch --no-stat -k -o patches/ 2be21aa..HEAD
```

Then filter out README-only and binary-blob commits if you only want code patches.
