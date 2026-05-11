# tools/

**English** | [Nederlands](README.nl.md)

Auxiliary scripts used by the maintainer for CTF challenges, hardware
debugging, and security research on **own equipment**. They are **not**
part of the driver itself and are not installed by `make install` or
DKMS.

---

## Legal notice — authorised testing only

The scripts in this directory probe network services. Running them
against systems you do **not** own, or without explicit written
permission from the owner, is a criminal offence in nearly every
jurisdiction. The maintainer takes the relevant laws seriously:

| Jurisdiction   | Statute                                          | What it covers                                                |
|----------------|--------------------------------------------------|---------------------------------------------------------------|
| Netherlands    | **Sr art. 138ab**                                | Computervredebreuk (unauthorised computer intrusion)          |
| Netherlands    | **Sr art. 350a / 350b**                          | Damaging data / introducing malware                           |
| European Union | **Directive 2013/40/EU**                         | Attacks against information systems                           |
| United States  | **18 USC § 1030** (CFAA)                         | Unauthorised access to a protected computer                   |
| United Kingdom | **Computer Misuse Act 1990, ss. 1–3**            | Unauthorised access, modification, impairment                 |
| Germany        | **StGB § 202a / 202c**                           | Hacking-equivalent + "Hacker-Paragraph" on tool distribution  |
| Australia      | **Criminal Code Act 1995, Part 10.7**            | Unauthorised access, modification or impairment               |

The maintainer accepts **no liability whatsoever** for misuse of these
scripts. Distribution is for legitimate research, education, and
authorised testing only.

---

## Acceptable use

- Verifying default-credential exposure on **cameras you own**.
- **CTF challenges** where the organiser has explicitly authorised
  network-level probing of the target.
- **Pentest engagements** with a signed scope letter / rules of
  engagement from the system owner.
- Demonstrating to a system administrator how an attacker would
  approach their device, with their **written consent**.

## Unacceptable use

- Probing **any** device on a network you do not own or administer,
  even if you can reach it.
- "Just trying" credentials on a neighbour's, hotel's, café's or
  guest-network camera.
- Probing a device whose owner has not given written permission, even
  if you believe they would consent.
- Continuing to probe after a single failed attempt makes it likely the
  owner will notice / be billed for the traffic.

If you are not sure whether a test is authorised, it is not.

---

## Contents

### `tapo_rtsp_brute.py`

Multi-threaded RTSP Digest brute-force credential finder for TP-Link
Tapo cameras (and any RTSP server using Digest authentication).
Implements the RTSP DESCRIBE challenge/response handshake. Built for
the maintainer's own home-lab CTF practice and verifying that default
credentials have been rotated on cameras under their administration.

```bash
python3 tools/tapo_rtsp_brute.py <camera_ip> [wordlist]
```

On start the script prints the legal-use notice and waits 5 seconds —
Ctrl+C aborts. For unattended runs against your own infrastructure
(scripted CTF labs, scheduled checks of your own kit) set
`RTW_TAPO_AUTHORISED=1` in the environment to skip the prompt.

The script writes nothing to disk and exits as soon as a valid
credential is found. Source: ~250 lines, standard library only, no
external dependencies.
