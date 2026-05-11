<!--
  Thanks for taking the time to send a PR.

  Bedankt voor je tijd om een PR in te dienen.

  Please fill in what is relevant; remove sections that don't apply.
  Vul in wat relevant is; verwijder secties die niet van toepassing zijn.
-->

## What this changes / Wat dit wijzigt

<!--
  One short paragraph. What problem does this solve, or which feature does
  it add? Link to the issue if there is one.

  Eén korte paragraaf. Welk probleem lost dit op, of welke feature voegt
  dit toe? Link naar het issue indien aanwezig.
-->

Closes #_____

## Type of change / Type wijziging

- [ ] Bug fix (kernel compatibility, monitor-mode race, etc.) / Bugfix
- [ ] Hardware support (new USB ID) / Hardware-ondersteuning (nieuwe USB-ID)
- [ ] New feature (dashboard, tests, tools) / Nieuwe functionaliteit
- [ ] Documentation only / Alleen documentatie
- [ ] Build / CI / packaging / Build / CI / packaging
- [ ] Refactor / chore (no functional change) / Refactor / chore

## Driver-source patches only / Alleen voor driver-source-patches

<!-- Skip this section if you're not touching core/, hal/, phl/, os_dep/. -->
<!-- Sla deze sectie over als je core/, hal/, phl/, os_dep/ niet aanraakt. -->

- [ ] Patch follows the Realtek vendor style (tabs, K&R braces, no large reformats)
      / Volgt de Realtek vendor-stijl (tabs, K&R braces, geen grote herformatteringen)
- [ ] Each commit message explains *why*, not just *what*
      / Elke commit-message legt het *waarom* uit, niet alleen het *wat*
- [ ] LINUX_VERSION_CODE guarded where appropriate
      / `LINUX_VERSION_CODE`-guards toegepast waar nodig

## Hardware additions only / Alleen voor hardware-toevoegingen

- [ ] `lsusb -v -d VVVV:PPPP` output attached / `lsusb -v`-output toegevoegd
- [ ] Confirmed RTL8852AU or RTL8832AU chipset (datasheet / FCC-ID lookup)
      / Bevestigd dat het een RTL8852AU- of RTL8832AU-chipset is
- [ ] Driver loads + interface appears on this device
      / Driver laadt en de interface verschijnt op dit apparaat

## How was this tested / Hoe is dit getest

<!--
  - Kernel version(s) you compiled against: e.g. 6.19.14+kali-amd64
  - Did `sudo ./tests/run_tests.sh` pass?
  - Anything destructive (rmmod, rapid toggle)? Did it stay stable?

  - Tegen welke kernel-versie(s) gecompileerd: bijv. 6.19.14+kali-amd64
  - Slaagde `sudo ./tests/run_tests.sh`?
  - Iets destructiefs (rmmod, rapide toggle)? Bleef het stabiel?
-->

## Checklist

- [ ] CI is green on this branch / CI is groen op deze branch
- [ ] `ruff check` passes on Python changes / `ruff check` slaagt voor Python-wijzigingen
- [ ] `shellcheck` passes on shell changes / `shellcheck` slaagt voor shell-wijzigingen
- [ ] CHANGELOG.md updated under `## [Unreleased]`
      / CHANGELOG.md bijgewerkt onder `## [Unreleased]`
- [ ] Docs updated where the behaviour changes (README, docs/dashboard.md, …)
      / Docs bijgewerkt waar gedrag verandert
