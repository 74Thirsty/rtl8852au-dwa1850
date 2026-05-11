# Patches

[English](README.md) | **Nederlands**

Deze map bevat de post-baseline-fixes en hardware-toevoegingen die
zijn aangebracht bovenop de initiële commit (`2be21aaa`).

De baseline-commit ("RTL8852AU driver v1.15.0.1 — patched for kernel
6.18+") bevat al de oorspronkelijke 12 kernel-6.18-compatibiliteit-
patches die in de hoofd-README zijn beschreven. Die patches passen de
Realtek-vendor-bron aan zodat hij op moderne kernels compileert; ze
zijn in de boom geïntegreerd omdat ze veel bestanden raken en
verplicht zijn voor *elke* build.

De onderstaande patches zijn losse opvolgers — bugfixes die na de
baseline zijn ontdekt en hardware-ID-toevoegingen. Elk bestand is een
standaard `git format-patch`-output en kan worden toegepast met
`git am` of `patch -p1`.

## Index

| #    | Patch                                                | Type     | Samenvatting                                                                                                                                                                                                              |
|------|------------------------------------------------------|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0001 | `monitor-fix-ubsan-array-oob-and-null-deref`         | Bugfix   | UBSAN array-out-of-bounds + NULL-deref in monitor-mode                                                                                                                                                                    |
| 0002 | `ethtool-add-get_link_ksettings-to-report-speed`     | Bugfix   | `ethtool` meldde `Speed: unknown` — `get_link_ksettings` toegevoegd                                                                                                                                                       |
| 0003 | `monitor-fix-skb-use-after-free-in-rx-path`          | Bugfix   | Hard freeze in monitor-mode veroorzaakt door SKB-use-after-free                                                                                                                                                           |
| 0004 | `monitor-fix-kernel-panic-race-and-double-free`      | Bugfix   | Kernel-panic onder belasting: race condition + double-free                                                                                                                                                                |
| 0005 | `build-fix-for-kernel-6.8`                           | Build    | Compatibiliteits-shim voor kernel 6.8                                                                                                                                                                                     |
| 0006 | `hw-add-usb-id-3625-010f-tp-link-archer-tx35u-plus`  | Hardware | USB-ID `3625:010f` (TP-Link Archer TX35U Plus)                                                                                                                                                                            |
| 0007 | `os-serialise-netdev-close-with-hw_init_mutex`       | Bugfix   | Kernel-panic bij rapide `ifup`/`ifdown` en `rmmod`-tijdens-associatie — `netdev_close()` neemt nu `hw_init_mutex` symmetrisch met `netdev_open()` en slaat het disassoc-cmd-pad over bij surprise-removed. **Hardware-geverifieerd** op TX20U Plus (Linux 6.19): 30× toggle @ 50 ms + rmmod-tijdens-up = 198 ms schone unload, geen panic |
| 0008 | `cfg80211-lower-mlo-signature-guards-to-6.17`        | Build    | Build-fout op kernel 6.17 — de MLO-refactor (`radio_idx`, `net_device *` op `set_monitor_channel`) landde in 6.17, niet 6.18. Vier `LINUX_VERSION_CODE`-guards in `os_dep/linux/ioctl_cfg80211.c` verlaagd van `>= 6.18` naar `>= 6.17` |

## Toepassen

Deze patches maken al deel uit van de huidige broncode-boom. Ze
worden hier bewaard als historische registratie en voor downstream-
maintainers die alleen de baseline volgen:

```bash
# Tegen een checkout van de baseline (2be21aa):
for p in patches/*.patch; do
    git am "$p"
done

# Of zonder git:
for p in patches/*.patch; do
    patch -p1 < "$p"
done
```

## Opnieuw genereren

```bash
git format-patch --no-stat -k -o patches/ 2be21aa..HEAD
```

Filter daarna README-only en binary-blob-commits eruit als je alleen
code-patches wilt.
