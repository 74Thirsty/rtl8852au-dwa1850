# tools/

Auxiliary scripts used by the maintainer for CTF challenges, hardware
debugging, and research. They are **not** part of the driver itself and are
not installed by `make install` or DKMS.

> **Authorised testing only.** The scripts in this directory probe network
> services. Running them against systems you do not own or do not have
> written permission to test is illegal in most jurisdictions
> (Computer Fraud and Abuse Act, Computer Misuse Act, Wet Computercriminaliteit,
> and equivalents). The maintainer accepts no responsibility for misuse.

## Contents

### `tapo_rtsp_brute.py`

Multi-threaded RTSP Digest brute-force credential finder for TP-Link Tapo
cameras. Implements the Digest challenge/response handshake and the Tapo
KLAP protocol bypass. Built for the maintainer's own home-lab CTF practice;
useful for testing default-credential exposure on cameras you own.

Usage:

```bash
python3 tools/tapo_rtsp_brute.py <camera_ip> <wordlist>
```

The script writes nothing to disk and exits as soon as a valid credential
is found. Source: 220 lines, standard library only, no external
dependencies.

**Acceptable use:**

- Testing cameras on a network you own.
- Verifying that default credentials have been rotated on devices you
  administer.
- CTF challenges where the target is explicitly authorised.

**Unacceptable use:**

- Anything else.
