#!/usr/bin/env python3
"""
RTL8852AU WiFi Adapter Dashboard
Flask-based web interface for monitoring and configuring the WiFi adapter.

Usage: sudo python3 dashboard/app.py [--port 8080] [--host 127.0.0.1]

The dashboard binds to loopback by default. All endpoints (including the
HTML root) are protected by HTTP Basic Auth — username is ignored, the
password is the per-user token stored in ~/.config/rtl8852au/dashboard.token
(generated on first run). Pass `--host 0.0.0.0` to expose to the LAN; in
that case the token is the only thing standing between the network and
root-level operations on this host.
"""

import argparse
import glob
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request

app = Flask(__name__)

DRIVER_NAME = "rtl8852au"
MODULE_NAME = "8852au"

# ── Auth + Host-header hardening ─────────────────────────────────────
# Goal: the dashboard runs as root and exposes endpoints that can change
# WiFi state, reload the kernel module, and run the test suite. Without
# auth, any process on this machine (or — when --host 0.0.0.0 — anyone on
# the LAN, plus drive-by JS via DNS-rebinding) could trigger those.
#
# We use HTTP Basic Auth so the browser handles credential caching for us
# (no JS changes in the embedded UI), and a Host-header whitelist so a
# DNS-rebind attack cannot reach the loopback endpoint from a remote tab.

# Resolve XDG_CONFIG_HOME (sudo keeps the original HOME; if not, fall back
# to /root/.config). The token file is mode 0600 and survives restarts.
def _config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "rtl8852au"


TOKEN_PATH = _config_dir() / "dashboard.token"
ALLOWED_HOSTS = set()  # populated in __main__ before app.run


def _load_or_create_token():
    """Return the dashboard auth token, generating one on first run."""
    try:
        if TOKEN_PATH.is_file():
            existing = TOKEN_PATH.read_text().strip()
            if existing:
                return existing
    except (IOError, OSError):
        pass
    token = secrets.token_urlsafe(32)
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(token + "\n")
        TOKEN_PATH.chmod(0o600)
    except (IOError, OSError) as exc:
        print(f"WARNING: could not persist token to {TOKEN_PATH}: {exc}")
        print("         A fresh token will be generated on every restart.")
    return token


AUTH_TOKEN = _load_or_create_token()


@app.before_request
def _enforce_auth_and_host():
    """Reject requests with an unexpected Host header (DNS-rebinding
    defence) or without valid HTTP Basic credentials."""
    host = (request.host or "").split(":")[0].lower()
    if host not in ALLOWED_HOSTS:
        return Response("forbidden host\n", status=403, mimetype="text/plain")

    auth = request.authorization
    supplied = (auth.password or "") if auth is not None else ""
    if not hmac.compare_digest(supplied, AUTH_TOKEN):
        return Response(
            "authentication required\n",
            status=401,
            mimetype="text/plain",
            headers={"WWW-Authenticate": 'Basic realm="RTL8852AU Dashboard"'},
        )
    return None


def _escape_wpa_string(value):
    """Escape a string for use inside a double-quoted wpa_supplicant value.

    Strips newlines (would split into a fresh directive and let an
    attacker inject network blocks or override ctrl_interface). Escapes
    the two characters the wpa_supplicant parser treats specially inside
    a quoted string: backslash and double-quote.
    """
    value = value.replace("\r", "").replace("\n", "")
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return value


def run(cmd, timeout=15):
    """Run a command and return (rc, stdout, stderr).

    Accepts either a list (preferred, executed directly without a shell)
    or a string (legacy path via `shell=True`, kept for the few commands
    that genuinely need pipes / redirects — none in this codebase anymore
    but the path is retained so external callers don't break).

    Using a list eliminates the shell-injection oppervlak completely:
    even if a user-controlled string ends up in argv, the kernel sees it
    as a single argument, not a shell command. Capture_output also lets
    us drop the `2>/dev/null` redirects that used to be sprinkled around.
    """
    use_shell = isinstance(cmd, str)
    try:
        r = subprocess.run(
            cmd,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as exc:
        return -1, "", f"{exc.filename}: not found"


def get_wlan_interface():
    for iface_dir in glob.glob("/sys/class/net/wlan*"):
        iface = os.path.basename(iface_dir)
        driver_link = os.path.join(iface_dir, "device", "driver")
        if os.path.islink(driver_link):
            if DRIVER_NAME in os.readlink(driver_link):
                return iface
    return None


def read_sysfs(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8", errors="replace").strip()
        if "\ufffd" in text:
            return None
        return text
    except (IOError, OSError):
        return None


# \u2500\u2500 Metric history \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
# Rolling ringbuffer of samples for the trend sparklines on the Overview
# tab. We append one sample per /api/status call; with the default
# 5-second client poll that gives 60 minutes of history (720 samples).
# Capped on memory regardless of polling rate. Read by /api/history.
METRIC_HISTORY = deque(maxlen=720)
_HISTORY_LOCK = threading.Lock()


def _parse_bitrate_mbps(s):
    """Pull the leading float out of an `iw dev <iface> link` bitrate
    string (e.g. '780.0 MBit/s'). Returns None when no match."""
    if not s:
        return None
    m = re.match(r'\s*([0-9.]+)\s*MBit/s', s)
    return float(m.group(1)) if m else None


def _record_sample(payload):
    """Append a single trend sample derived from the /api/status payload."""
    conn = payload.get("connection") or {}
    stats = payload.get("statistics") or {}
    sample = {
        "t": time.time(),
        "signal": conn.get("signal_dbm"),
        "bitrate": _parse_bitrate_mbps(conn.get("tx_bitrate")),
        "tx_bytes": stats.get("tx_bytes", 0),
        "rx_bytes": stats.get("rx_bytes", 0),
        "errors": (stats.get("tx_errors", 0) or 0) + (stats.get("rx_errors", 0) or 0),
    }
    with _HISTORY_LOCK:
        METRIC_HISTORY.append(sample)


# ── API Endpoints ─────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found", "driver_loaded": False})

    dev_path = os.path.realpath(f"/sys/class/net/{iface}/device")
    usb_parent = os.path.dirname(dev_path)

    # Basic info
    mac = read_sysfs(f"/sys/class/net/{iface}/address") or "unknown"
    operstate = read_sysfs(f"/sys/class/net/{iface}/operstate") or "unknown"
    mtu = read_sysfs(f"/sys/class/net/{iface}/mtu") or "unknown"
    tx_bytes = read_sysfs(f"/sys/class/net/{iface}/statistics/tx_bytes") or "0"
    rx_bytes = read_sysfs(f"/sys/class/net/{iface}/statistics/rx_bytes") or "0"
    tx_packets = read_sysfs(f"/sys/class/net/{iface}/statistics/tx_packets") or "0"
    rx_packets = read_sysfs(f"/sys/class/net/{iface}/statistics/rx_packets") or "0"
    tx_errors = read_sysfs(f"/sys/class/net/{iface}/statistics/tx_errors") or "0"
    rx_errors = read_sysfs(f"/sys/class/net/{iface}/statistics/rx_errors") or "0"
    tx_dropped = read_sysfs(f"/sys/class/net/{iface}/statistics/tx_dropped") or "0"
    rx_dropped = read_sysfs(f"/sys/class/net/{iface}/statistics/rx_dropped") or "0"
    speed = read_sysfs(os.path.join(usb_parent, "speed")) or "unknown"

    # USB info
    vendor = read_sysfs(os.path.join(usb_parent, "idVendor")) or "unknown"
    product = read_sysfs(os.path.join(usb_parent, "idProduct")) or "unknown"
    manufacturer = read_sysfs(os.path.join(usb_parent, "manufacturer")) or "unknown"
    product_name = read_sysfs(os.path.join(usb_parent, "product")) or "unknown"

    # Module info
    srcversion = read_sysfs(f"/sys/module/{MODULE_NAME}/srcversion") or "unknown"

    # Connection info from iw
    rc, iw_out, _ = run(["iw", "dev", iface, "link"])
    connected_ssid = None
    signal_dbm = None
    freq = None
    bitrate = None
    if rc == 0 and "Connected" in iw_out:
        m = re.search(r'SSID: (.+)', iw_out)
        if m:
            connected_ssid = m.group(1)
        m = re.search(r'signal: (-?\d+) dBm', iw_out)
        if m:
            signal_dbm = int(m.group(1))
        m = re.search(r'freq: (\d+)', iw_out)
        if m:
            freq = int(m.group(1))
        m = re.search(r'tx bitrate: (.+)', iw_out)
        if m:
            bitrate = m.group(1)

    # IP address
    rc, ip_out, _ = run(["ip", "-4", "addr", "show", iface])
    ip_addr = None
    if rc == 0:
        m = re.search(r'inet (\S+)', ip_out)
        if m:
            ip_addr = m.group(1)

    payload = {
        "driver_loaded": True,
        "interface": iface,
        "mac_address": mac,
        "operstate": operstate,
        "mtu": mtu,
        "ip_address": ip_addr,
        "usb_speed_mbps": speed,
        "usb_vendor": vendor,
        "usb_product": product,
        "usb_manufacturer": manufacturer,
        "usb_product_name": product_name,
        "module_srcversion": srcversion,
        "connection": {
            "ssid": connected_ssid,
            "signal_dbm": signal_dbm,
            "frequency_mhz": freq,
            "tx_bitrate": bitrate,
        },
        "statistics": {
            "tx_bytes": int(tx_bytes),
            "rx_bytes": int(rx_bytes),
            "tx_packets": int(tx_packets),
            "rx_packets": int(rx_packets),
            "tx_errors": int(tx_errors),
            "rx_errors": int(rx_errors),
            "tx_dropped": int(tx_dropped),
            "rx_dropped": int(rx_dropped),
        }
    }
    _record_sample(payload)
    return jsonify(payload)


@app.route("/api/history")
def api_history():
    """Return the rolling buffer of trend samples (newest last)."""
    with _HISTORY_LOCK:
        return jsonify({"samples": list(METRIC_HISTORY)})


@app.route("/api/scan")
def api_scan():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    run(["ip", "link", "set", iface, "up"])
    run(["iw", "dev", iface, "scan", "trigger"])
    time.sleep(4)
    rc, out, err = run(["iw", "dev", iface, "scan", "dump"], timeout=20)
    if rc != 0:
        return jsonify({"error": f"Scan failed: {err}"}), 500

    networks = []
    current = None
    for line in out.split('\n'):
        line = line.strip()
        m = re.match(r'BSS ([0-9a-f:]+)', line)
        if m:
            if current:
                networks.append(current)
            current = {"bssid": m.group(1), "ssid": "", "signal": None,
                       "frequency": None, "channel": None, "security": "Open"}
        if current is None:
            continue
        if line.startswith("SSID:"):
            current["ssid"] = line[6:].strip()
        elif line.startswith("signal:"):
            m2 = re.search(r'(-?\d+\.?\d*)', line)
            if m2:
                current["signal"] = float(m2.group(1))
        elif line.startswith("freq:"):
            m2 = re.search(r'(\d+)', line)
            if m2:
                current["frequency"] = int(m2.group(1))
        elif "WPA" in line or "RSN" in line:
            current["security"] = "WPA2/WPA3" if "RSN" in line else "WPA"
        elif line.startswith("DS Parameter set: channel"):
            m2 = re.search(r'channel (\d+)', line)
            if m2:
                current["channel"] = int(m2.group(1))
    if current:
        networks.append(current)

    # Sort by signal strength
    networks.sort(key=lambda n: n["signal"] if n["signal"] is not None else -999, reverse=True)
    return jsonify({"networks": networks, "count": len(networks)})


@app.route("/api/connect", methods=["POST"])
def api_connect():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    data = request.get_json(silent=True) or {}
    ssid = data.get("ssid", "") or ""
    password = data.get("password", "") or ""

    # SSID: IEEE 802.11 limits to 32 bytes. Reject newlines/embedded NUL.
    if not ssid or len(ssid.encode("utf-8")) > 32:
        return jsonify({"error": "SSID must be 1-32 bytes UTF-8"}), 400
    # WPA passphrase spec: 8-63 ASCII chars (or 64 hex). Empty = open network.
    if password and not (8 <= len(password) <= 63):
        return jsonify({"error": "WPA passphrase must be 8-63 characters"}), 400

    # Escape both for the quoted wpa_supplicant string literal. Without
    # this, an SSID like  evil"\nnetwork={ssid="x  would inject extra
    # network blocks (rogue-AP redirect, ctrl_interface override).
    ssid_esc = _escape_wpa_string(ssid)
    password_esc = _escape_wpa_string(password)

    conf = f'network={{\n    ssid="{ssid_esc}"\n'
    if password_esc:
        conf += f'    psk="{password_esc}"\n'
    else:
        conf += '    key_mgmt=NONE\n'
    conf += '}\n'

    conf_path = f"/run/wpa_{iface}.conf"
    fd = os.open(conf_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f'ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\n\n{conf}')

    run(["killall", "-9", "wpa_supplicant"])
    time.sleep(1)
    run(["ip", "link", "set", iface, "up"])

    # Discard stderr from wpa_supplicant — it can echo the passphrase on
    # failure paths (e.g. "Line N: invalid PSK 'mypass123'").
    rc, _, _ = run(["wpa_supplicant", "-B", "-i", iface, "-c", conf_path], timeout=10)
    if rc != 0:
        return jsonify({"error": "wpa_supplicant failed to start"}), 500

    run(["dhclient", "-r", iface])
    rc, _, _ = run(["dhclient", iface], timeout=30)
    if rc != 0:
        return jsonify({"warning": "Connected but DHCP failed", "ssid": ssid})

    time.sleep(2)
    return jsonify({"success": True, "ssid": ssid})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    run(["iw", "dev", iface, "disconnect"])
    run(["killall", "wpa_supplicant"])
    run(["dhclient", "-r", iface])
    return jsonify({"success": True})


@app.route("/api/driver")
def api_driver():
    rc, modinfo, _ = run(["modinfo", MODULE_NAME])
    info = {}
    if rc == 0:
        for line in modinfo.split('\n'):
            m = re.match(r'(\w+):\s+(.+)', line)
            if m:
                key = m.group(1)
                if key not in info:
                    info[key] = m.group(2)
                elif key == "alias":
                    if isinstance(info[key], list):
                        info[key].append(m.group(2))
                    else:
                        info[key] = [info[key], m.group(2)]

    srcversion = read_sysfs(f"/sys/module/{MODULE_NAME}/srcversion") or "unknown"
    _, kver, _ = run("uname -r")

    return jsonify({
        "module_name": MODULE_NAME,
        "driver_name": DRIVER_NAME,
        "kernel_version": kver,
        "srcversion": srcversion,
        "modinfo": info
    })


@app.route("/api/ifconfig", methods=["POST"])
def api_ifconfig():
    """Change interface settings (MTU, power save, etc.)."""
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    data = request.get_json()
    results = []

    if "mtu" in data:
        mtu = int(data["mtu"])
        if 576 <= mtu <= 9000:
            rc, _, err = run(["ip", "link", "set", iface, "mtu", str(mtu)])
            results.append({"mtu": "ok" if rc == 0 else err})

    if "txpower" in data:
        txp = int(data["txpower"])
        if 0 <= txp <= 30:
            rc, _, err = run(["iw", "dev", iface, "set", "txpower", "fixed", str(txp * 100)])
            results.append({"txpower": "ok" if rc == 0 else err})

    if "power_save" in data:
        ps = "on" if data["power_save"] else "off"
        rc, _, err = run(["iw", "dev", iface, "set", "power_save", ps])
        results.append({"power_save": "ok" if rc == 0 else err})

    return jsonify({"results": results})


@app.route("/api/tests/run", methods=["POST"])
def api_run_tests():
    """Run the driver test suite and return results."""
    test_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tests", "test_driver.py")
    if not os.path.exists(test_script):
        return jsonify({"error": "Test script not found"}), 404

    rc, out, err = run(["python3", test_script], timeout=120)
    report_path = os.path.join(os.path.dirname(test_script), "test_report.json")
    report = None
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)

    return jsonify({
        "exit_code": rc,
        "output": out,
        "stderr": err,
        "report": report
    })


# ── Advanced Configuration ───────────────────────────────────────────

MODPROBE_CONF = "/etc/modprobe.d/8852au.conf"

# Whitelist of module parameters exposed in the Advanced tab.
# Each entry: param_name -> {type, options (for select), min/max (for number)}
ADVANCED_PARAMS = {
    # Draadloze Modus
    "rtw_ht_enable":      {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    "rtw_vht_enable":     {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto"}},
    "rtw_he_enable":      {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto"}},
    "rtw_wireless_mode":  {"vtype": "number", "min": 0, "max": 255},
    "rtw_band_type":      {"vtype": "select", "opts": {"1": "Alleen 2.4 GHz", "2": "Alleen 5 GHz", "3": "Dual-band (2.4 + 5 GHz)"}},
    # Kanaal & Bandbreedte
    "rtw_channel":        {"vtype": "number", "min": 0, "max": 165},
    "rtw_bw_mode":        {"vtype": "number", "min": 0, "max": 255},
    "rtw_channel_plan":   {"vtype": "number", "min": 0, "max": 255},
    "rtw_country_code":   {"vtype": "text"},
    # Energiebeheer
    "rtw_power_mgnt":     {"vtype": "select", "opts": {"0": "Uit", "1": "Minimaal", "2": "Maximaal"}},
    "rtw_ips_mode":       {"vtype": "select", "opts": {"0": "Geen", "1": "Normaal", "2": "Level 2"}},
    "rtw_lps_level":      {"vtype": "select", "opts": {"0": "Normaal", "1": "Clock Gating", "2": "Power Gating"}},
    # Prestaties
    "rtw_ampdu_enable":   {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    "rtw_en_napi":        {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    "rtw_en_gro":         {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    "rtw_switch_usb_mode":{"vtype": "select", "opts": {"0": "Geen wijziging", "1": "USB 3.0", "2": "USB 2.0"}},
    "rtw_wmm_enable":     {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    # Antenne & Beamforming
    "rtw_beamform_cap":   {"vtype": "number", "min": 0, "max": 255},
    "rtw_dyn_txbf":       {"vtype": "select", "opts": {"0": "Uit", "1": "Aan"}},
    "rtw_tx_nss":         {"vtype": "select", "opts": {"0": "Auto", "1": "1 Stream", "2": "2 Streams"}},
    "rtw_rx_nss":         {"vtype": "select", "opts": {"0": "Auto", "1": "1 Stream", "2": "2 Streams"}},
    "rtw_antdiv_cfg":     {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto (Efuse)"}},
    "rtw_rx_stbc":        {"vtype": "select", "opts": {"0": "Uit", "1": "Alleen 2.4 GHz", "2": "Alleen 5 GHz", "3": "Beide banden"}},
    # Roaming & Verbinding
    "rtw_max_roaming_times": {"vtype": "number", "min": 0, "max": 8},
    "rtw_btcoex_enable":  {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto (Efuse)"}},
    # Debug
    "rtw_drv_log_level":  {"vtype": "select", "opts": {"0": "Geen", "1": "Error", "2": "Warning", "3": "Notice", "4": "Info", "5": "Debug"}},
    "rtw_tx_pwr_by_rate": {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto (Efuse)"}},
    "rtw_tx_pwr_lmt_enable": {"vtype": "select", "opts": {"0": "Uit", "1": "Aan", "2": "Auto (Efuse)"}},
}


def read_module_param(name):
    """Read a single module parameter from sysfs."""
    val = read_sysfs(f"/sys/module/{MODULE_NAME}/parameters/{name}")
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return val


def read_modprobe_conf():
    """Parse saved settings from /etc/modprobe.d/8852au.conf."""
    pending = {}
    if os.path.exists(MODPROBE_CONF):
        try:
            with open(MODPROBE_CONF) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"options {MODULE_NAME}"):
                        parts = line.split()[2:]
                        for part in parts:
                            if "=" in part:
                                k, v = part.split("=", 1)
                                if k in ADVANCED_PARAMS:
                                    pending[k] = v
        except (IOError, OSError):
            pass
    return pending


def write_modprobe_conf(params):
    """Write module parameters to /etc/modprobe.d/8852au.conf (merge)."""
    other_lines = []
    existing = {}
    if os.path.exists(MODPROBE_CONF):
        try:
            with open(MODPROBE_CONF) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(f"options {MODULE_NAME}"):
                        for part in stripped.split()[2:]:
                            if "=" in part:
                                k, v = part.split("=", 1)
                                existing[k] = v
                    elif not stripped.startswith("# RTL8852AU") and not stripped.startswith("# Automatisch"):
                        other_lines.append(line)
        except (IOError, OSError):
            pass

    existing.update(params)
    valid = {k: v for k, v in existing.items() if k in ADVANCED_PARAMS}

    with open(MODPROBE_CONF, "w") as f:
        f.write("# RTL8852AU advanced settings - managed by dashboard\n")
        f.write("# Automatisch gegenereerd - niet handmatig bewerken\n")
        if valid:
            opts = " ".join(f"{k}={v}" for k, v in sorted(valid.items()))
            f.write(f"options {MODULE_NAME} {opts}\n")
        for line in other_lines:
            f.write(line)


@app.route("/api/advanced")
def api_advanced():
    """Read all advanced parameters: current from sysfs, pending from modprobe.d."""
    params = {}
    for name in ADVANCED_PARAMS:
        current = read_module_param(name)
        params[name] = {"current": current}

    pending = read_modprobe_conf()
    has_pending = False
    for name, val in pending.items():
        if name in params:
            try:
                pval = int(val)
            except ValueError:
                pval = val
            params[name]["pending"] = pval
            if params[name]["current"] is not None and str(params[name]["current"]) != str(pval):
                has_pending = True

    return jsonify({
        "parameters": params,
        "has_pending_changes": has_pending,
        "modprobe_conf_exists": os.path.exists(MODPROBE_CONF),
    })


@app.route("/api/advanced", methods=["POST"])
def api_advanced_save():
    """Save advanced settings. Live settings applied immediately, module settings persisted."""
    data = request.get_json()
    results = []
    iface = get_wlan_interface()

    # Apply live settings via iw
    live = data.get("live", {})
    if iface and "txpower" in live:
        txp = int(live["txpower"])
        if 0 <= txp <= 30:
            rc, _, err = run(["iw", "dev", iface, "set", "txpower", "fixed", str(txp * 100)])
            results.append({"txpower": "ok" if rc == 0 else err})
    if iface and "power_save" in live:
        ps = "on" if live["power_save"] else "off"
        rc, _, err = run(["iw", "dev", iface, "set", "power_save", ps])
        results.append({"power_save": "ok" if rc == 0 else err})

    # Persist module settings
    module = data.get("module", {})
    reload_needed = False
    if module:
        safe = {}
        for k, v in module.items():
            if k not in ADVANCED_PARAMS:
                continue
            spec = ADVANCED_PARAMS[k]
            sv = str(v)
            if spec["vtype"] == "number":
                try:
                    iv = int(sv)
                    if "min" in spec and iv < spec["min"]:
                        continue
                    if "max" in spec and iv > spec["max"]:
                        continue
                except ValueError:
                    continue
            elif spec["vtype"] == "select":
                if sv not in spec["opts"]:
                    continue
            safe[k] = sv
        if safe:
            try:
                write_modprobe_conf(safe)
                reload_needed = True
                results.append({"module": "ok", "saved": list(safe.keys())})
            except (IOError, OSError) as e:
                results.append({"module": f"error: {e}"})

    return jsonify({"results": results, "reload_needed": reload_needed})


@app.route("/api/advanced/reload", methods=["POST"])
def api_advanced_reload():
    """Safely reload the kernel module to apply new parameters."""
    iface = get_wlan_interface()
    warnings = []

    if iface:
        rc, link_out, _ = run(["iw", "dev", iface, "link"])
        if rc == 0 and "Connected" in link_out:
            warnings.append("Adapter was verbonden met een netwerk. Verbinding is verbroken.")
        run(["ip", "link", "set", iface, "down"])
        run(["killall", "wpa_supplicant"])
        run(["dhclient", "-r", iface])
        time.sleep(1)

    rc, _, err = run(["modprobe", "-r", MODULE_NAME], timeout=10)
    if rc != 0:
        rc, _, err = run(["rmmod", MODULE_NAME], timeout=10)
        if rc != 0:
            return jsonify({
                "success": False,
                "error": f"Kan module niet verwijderen: {err}",
                "hint": "Sluit alle programma's die de adapter gebruiken en probeer opnieuw.",
            }), 500

    time.sleep(2)

    rc, _, err = run(["modprobe", MODULE_NAME], timeout=15)
    if rc != 0:
        return jsonify({"success": False, "error": f"Kan module niet laden: {err}"}), 500

    new_iface = None
    for _ in range(10):
        time.sleep(1)
        new_iface = get_wlan_interface()
        if new_iface:
            break

    if not new_iface:
        return jsonify({
            "success": True,
            "warning": "Module geladen maar interface nog niet beschikbaar.",
            "warnings": warnings,
        })

    run(["ip", "link", "set", new_iface, "up"])
    return jsonify({
        "success": True,
        "interface": new_iface,
        "warnings": warnings,
        "message": "Module succesvol herladen met nieuwe instellingen.",
    })


# ── HTML Dashboard ────────────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en" id="html-root">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RTL8852AU WiFi Dashboard</title>
<style>
/* ── Theme tokens ────────────────────────────────────────────────── */
:root[data-theme="dark"], :root:not([data-theme]) {
    --bg-base: #0f172a;     --bg-card: #1e293b;   --bg-input: #0f172a;
    --border:  #334155;     --border-strong: #475569;
    --text:    #e2e8f0;     --text-muted: #94a3b8;  --text-dim: #64748b;
    --accent:  #38bdf8;     --accent-hover: #1d4ed8;
    --ok-bg:   #065f46;     --ok-fg: #6ee7b7;
    --err-bg:  #7f1d1d;     --err-fg: #fca5a5;
    --warn-bg: #78350f;     --warn-fg: #fde68a;     --warn-border: #92400e;
    --row-border: #1e293b;  --tr-hover: #0f172a;
    --header-gradient: linear-gradient(135deg, #1e293b, #334155);
    --shadow: none;
}
:root[data-theme="light"] {
    --bg-base: #f8fafc;     --bg-card: #ffffff;   --bg-input: #ffffff;
    --border:  #e2e8f0;     --border-strong: #cbd5e1;
    --text:    #0f172a;     --text-muted: #475569;  --text-dim: #94a3b8;
    --accent:  #0284c7;     --accent-hover: #0369a1;
    --ok-bg:   #d1fae5;     --ok-fg: #065f46;
    --err-bg:  #fee2e2;     --err-fg: #991b1b;
    --warn-bg: #fef3c7;     --warn-fg: #92400e;     --warn-border: #fcd34d;
    --row-border: #f1f5f9;  --tr-hover: #f8fafc;
    --header-gradient: linear-gradient(135deg, #e0f2fe, #bae6fd);
    --shadow: 0 1px 3px rgba(15,23,42,0.08);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: var(--bg-base); color: var(--text); min-height: 100vh; }
.header { background: var(--header-gradient); position: relative;
           padding: 20px 30px; border-bottom: 1px solid var(--border-strong);
           text-align: center; }
.header-title { display: inline-block; }
.header h1 { font-size: 1.5rem; color: var(--accent); line-height: 1.2; }
.header-link { display: block; margin-top: 4px; color: var(--text-muted);
               font-size: 0.85rem; text-decoration: none; font-family: monospace; }
.header-link:hover { color: var(--accent); text-decoration: underline; }
.header-controls { position: absolute; right: 30px; top: 50%; transform: translateY(-50%);
                   display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.header .status-badge { padding: 6px 16px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
.footer { text-align: center; padding: 30px 20px 24px;
          color: var(--text-dim); font-size: 0.85rem;
          border-top: 1px solid var(--border); margin-top: 40px; }
.footer a { color: var(--accent); text-decoration: none; }
.footer a:hover { text-decoration: underline; }
.footer .footer-by { letter-spacing: 0.06em; text-transform: uppercase; font-size: 0.75rem; }
.badge-ok { background: var(--ok-bg); color: var(--ok-fg); }
.badge-err { background: var(--err-bg); color: var(--err-fg); }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 20px; margin-bottom: 20px; }
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; box-shadow: var(--shadow); }
.card h2 { font-size: 1.1rem; color: var(--text-muted); margin-bottom: 16px; text-transform: uppercase;
            letter-spacing: 0.05em; font-weight: 600; }
.info-row { display: flex; justify-content: space-between; padding: 8px 0;
            border-bottom: 1px solid var(--row-border); }
.info-row:last-child { border-bottom: none; }
.info-label { color: var(--text-dim); font-size: 0.9rem; }
.info-value { color: var(--text); font-weight: 500; font-size: 0.9rem; }
.stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.stat-box { background: var(--bg-input); border: 1px solid var(--border); border-radius: 8px; padding: 14px; text-align: center; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; text-transform: uppercase; }
.signal-bar { height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; margin-top: 8px; }
.signal-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
/* Trend sparklines */
.trend-row { display: grid; grid-template-columns: 140px 1fr 90px; align-items: center; gap: 10px;
             padding: 8px 0; border-bottom: 1px solid var(--row-border); }
.trend-row:last-child { border-bottom: none; }
.trend-label { color: var(--text-dim); font-size: 0.85rem; }
.trend-canvas { width: 100%; height: 36px; display: block; }
.trend-value { color: var(--text); font-size: 0.9rem; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; }
table th { text-align: left; padding: 10px 12px; background: var(--bg-input); color: var(--text-dim);
           font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
table td { padding: 10px 12px; border-bottom: 1px solid var(--row-border); font-size: 0.9rem; }
table tr:hover td { background: var(--tr-hover); }
.btn { padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer;
       font-size: 0.9rem; font-weight: 600; transition: all 0.2s; }
.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: var(--accent-hover); }
.btn-danger { background: #dc2626; color: white; }
.btn-danger:hover { background: #b91c1c; }
.btn-success { background: #059669; color: white; }
.btn-success:hover { background: #047857; }
.btn-sm { padding: 5px 12px; font-size: 0.8rem; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; color: var(--text-muted); font-size: 0.85rem; margin-bottom: 4px; }
.form-group input, .form-group select { width: 100%; padding: 8px 12px; background: var(--bg-input);
    border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-size: 0.9rem; }
.form-group input:focus { outline: none; border-color: var(--accent); }
.toast { position: fixed; bottom: 20px; right: 20px; padding: 12px 24px; border-radius: 8px;
         color: white; font-weight: 500; z-index: 100; transition: opacity 0.3s; }
.toast-ok { background: #059669; }
.toast-err { background: #dc2626; }
.actions { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap; }
.tab-bar { display: flex; gap: 4px; margin-bottom: 20px; flex-wrap: wrap; }
.tab { padding: 10px 20px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px 8px 0 0;
       cursor: pointer; color: var(--text-dim); font-weight: 500; }
.tab.active { background: var(--border); color: var(--accent); border-bottom-color: var(--border); }
.tab-content { display: none; }
.tab-content.active { display: block; }
#test-output { background: var(--bg-input); padding: 16px; border-radius: 8px; font-family: monospace;
               font-size: 0.85rem; white-space: pre-wrap; max-height: 500px; overflow-y: auto;
               line-height: 1.6; color: var(--text); border: 1px solid var(--border); }
.test-pass { color: #16a34a; }
.test-fail { color: #dc2626; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border-strong);
           border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
/* Keyboard-help overlay */
.kbd-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center;
               justify-content: center; z-index: 200; }
.kbd-overlay.open { display: flex; }
.kbd-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 24px 28px;
             max-width: 420px; box-shadow: var(--shadow); color: var(--text); }
.kbd-panel h3 { font-size: 1.1rem; margin-bottom: 14px; color: var(--accent); }
.kbd-row { display: flex; justify-content: space-between; padding: 6px 0; font-size: 0.9rem; }
.kbd { display: inline-block; background: var(--bg-input); border: 1px solid var(--border-strong); border-radius: 4px;
       padding: 1px 6px; font-family: monospace; font-size: 0.8rem; color: var(--text); }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .adv-container { flex-direction: column; } .adv-sidebar { width: 100%; } }
@media (max-width: 900px) {
    .header { padding-bottom: 70px; }
    .header-controls { position: static; transform: none; justify-content: center; margin-top: 14px; }
}
@media (max-width: 600px) {
    .header { padding: 14px 16px 70px; }
    .header h1 { font-size: 1.15rem; }
    .header-link { font-size: 0.75rem; }
    .container { padding: 12px; }
    .card { padding: 14px; }
    .tab { padding: 8px 12px; font-size: 0.85rem; }
    .stat-grid { grid-template-columns: 1fr 1fr; }
    .trend-row { grid-template-columns: 1fr; gap: 4px; }
    .trend-value { text-align: left; }
    .footer { padding: 20px 14px 18px; }
}
/* Advanced tab - Windows Device Manager style */
.adv-container { display: flex; gap: 16px; min-height: 520px; }
.adv-sidebar { width: 270px; flex-shrink: 0; background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; }
.adv-main { flex: 1; background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; display: flex; flex-direction: column; }
.adv-cat { padding: 10px 16px; cursor: pointer; color: #94a3b8; border-left: 3px solid transparent;
           font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
           background: #1e293b; transition: all 0.15s; }
.adv-cat:hover { color: #e2e8f0; background: #262f3f; }
.adv-cat.active { color: #38bdf8; border-left-color: #38bdf8; background: #0f172a; }
.adv-props { border-top: 1px solid #334155; }
.adv-prop { padding: 8px 16px 8px 28px; cursor: pointer; color: #cbd5e1; font-size: 0.85rem;
            border-bottom: 1px solid #1e293b; transition: all 0.1s; display: flex; justify-content: space-between; align-items: center; }
.adv-prop:hover:not(.active) { background: #334155; }
.adv-prop.active { background: #2563eb; color: white; }
.adv-prop .adv-modified-dot { width: 8px; height: 8px; border-radius: 50%; background: #fbbf24; flex-shrink: 0; }
.adv-editor-label { font-size: 0.9rem; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600; }
.adv-editor-name { font-size: 1.15rem; color: #e2e8f0; font-weight: 600; margin-bottom: 16px; }
.adv-editor-input select, .adv-editor-input input { width: 100%; max-width: 320px; padding: 10px 14px; background: #0f172a;
    border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; font-size: 0.95rem; }
.adv-editor-input select:focus, .adv-editor-input input:focus { outline: none; border-color: #2563eb; }
.adv-current { color: #64748b; font-size: 0.8rem; margin-top: 10px; }
.adv-desc { background: #0f172a; border-radius: 8px; padding: 14px; color: #94a3b8; font-size: 0.85rem;
            line-height: 1.6; margin-top: auto; min-height: 80px; }
.badge-live { display: inline-block; background: #065f46; color: #6ee7b7; font-size: 0.7rem;
              padding: 2px 8px; border-radius: 10px; font-weight: 600; margin-left: 6px; }
.badge-module { display: inline-block; background: #78350f; color: #fde68a; font-size: 0.7rem;
                padding: 2px 8px; border-radius: 10px; font-weight: 600; margin-left: 6px; }
.adv-actions { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap; }
.adv-pending-banner { background: #78350f; border: 1px solid #92400e; border-radius: 8px;
                      padding: 12px 16px; color: #fde68a; margin-top: 12px; font-size: 0.85rem; }
.adv-empty { color: #64748b; padding: 40px 20px; text-align: center; font-size: 0.9rem; }
.btn-warning { background: #d97706; color: white; }
.btn-warning:hover { background: #b45309; }
.btn-outline { background: transparent; border: 1px solid #475569; color: #94a3b8; }
.btn-outline:hover { background: #334155; color: #e2e8f0; }
.lang-switch { display: flex; gap: 4px; align-items: center; }
.lang-btn { background: transparent; border: 1px solid #475569; color: #94a3b8; padding: 4px 10px;
            border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
.lang-btn.active { background: #2563eb; border-color: #2563eb; color: white; }
.lang-btn:hover:not(.active) { background: #334155; color: #e2e8f0; }
</style>
</head>
<body>

<div class="header">
    <div class="header-title">
        <h1>RTL8852AU WiFi Dashboard</h1>
        <a class="header-link"
           href="https://github.com/WimLee115/rtl8852au-build"
           target="_blank" rel="noopener noreferrer">github.com/WimLee115/rtl8852au-build</a>
    </div>
    <div class="header-controls">
        <div class="lang-switch">
            <button class="lang-btn" data-theme-btn="dark" onclick="setTheme('dark')" title="Dark mode">●</button>
            <button class="lang-btn" data-theme-btn="light" onclick="setTheme('light')" title="Light mode">○</button>
        </div>
        <div class="lang-switch">
            <button class="lang-btn" data-lang="en" onclick="setLanguage('en')">EN</button>
            <button class="lang-btn" data-lang="nl" onclick="setLanguage('nl')">NL</button>
        </div>
        <span id="status-badge" class="status-badge badge-ok" data-i18n="status.loading">Loading...</span>
    </div>
</div>

<div class="kbd-overlay" id="kbd-overlay" onclick="if(event.target===this)toggleKbdHelp()">
    <div class="kbd-panel">
        <h3 data-i18n="kbd.title">Keyboard shortcuts</h3>
        <div class="kbd-row"><span data-i18n="kbd.tab1">Overview tab</span><span><kbd class="kbd">1</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.tab2">Networks tab</span><span><kbd class="kbd">2</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.tab3">Settings tab</span><span><kbd class="kbd">3</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.tab4">Tests tab</span><span><kbd class="kbd">4</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.tab5">Advanced tab</span><span><kbd class="kbd">5</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.scan">Scan networks</span><span><kbd class="kbd">/</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.refresh">Refresh status</span><span><kbd class="kbd">r</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.theme">Toggle theme</span><span><kbd class="kbd">t</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.lang">Toggle language</span><span><kbd class="kbd">l</kbd></span></div>
        <div class="kbd-row"><span data-i18n="kbd.help">Show this help</span><span><kbd class="kbd">?</kbd></span></div>
    </div>
</div>

<div class="container">
    <div class="tab-bar">
        <div class="tab active" onclick="switchTab('overview')" data-tab="overview" data-i18n="tab.overview">Overview</div>
        <div class="tab" onclick="switchTab('networks')" data-tab="networks" data-i18n="tab.networks">Networks</div>
        <div class="tab" onclick="switchTab('settings')" data-tab="settings" data-i18n="tab.settings">Settings</div>
        <div class="tab" onclick="switchTab('tests')" data-tab="tests" data-i18n="tab.tests">Tests</div>
        <div class="tab" onclick="switchTab('advanced')" data-tab="advanced" data-i18n="tab.advanced">Advanced</div>
    </div>

    <!-- Overview Tab -->
    <div id="tab-overview" class="tab-content active">
        <div class="grid">
            <div class="card">
                <h2 data-i18n="card.adapter">Adapter Info</h2>
                <div id="adapter-info" data-i18n="status.loading">Loading...</div>
            </div>
            <div class="card">
                <h2 data-i18n="card.connection">Connection</h2>
                <div id="connection-info" data-i18n="status.loading">Loading...</div>
            </div>
            <div class="card">
                <h2 data-i18n="card.stats">Statistics</h2>
                <div id="stats-info" class="stat-grid"></div>
            </div>
            <div class="card">
                <h2 data-i18n="card.driver">Driver Info</h2>
                <div id="driver-info" data-i18n="status.loading">Loading...</div>
            </div>
            <div class="card" style="grid-column: 1 / -1;">
                <h2 data-i18n="card.trends">Trends (last 60 min)</h2>
                <div id="trends-info">
                    <div class="trend-row"><span class="trend-label" data-i18n="trend.signal">Signal</span><canvas class="trend-canvas" id="trend-signal"></canvas><span class="trend-value" id="trend-signal-val">–</span></div>
                    <div class="trend-row"><span class="trend-label" data-i18n="trend.bitrate">TX bitrate</span><canvas class="trend-canvas" id="trend-bitrate"></canvas><span class="trend-value" id="trend-bitrate-val">–</span></div>
                    <div class="trend-row"><span class="trend-label" data-i18n="trend.throughput">RX throughput</span><canvas class="trend-canvas" id="trend-throughput"></canvas><span class="trend-value" id="trend-throughput-val">–</span></div>
                    <div class="trend-row"><span class="trend-label" data-i18n="trend.errors">Errors (Δ)</span><canvas class="trend-canvas" id="trend-errors"></canvas><span class="trend-value" id="trend-errors-val">–</span></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Networks Tab -->
    <div id="tab-networks" class="tab-content">
        <div class="card">
            <h2><span data-i18n="card.scan">Available networks</span>
                <button class="btn btn-primary btn-sm" onclick="doScan()" style="float:right;" data-i18n="btn.scan">
                    Scan
                </button>
            </h2>
            <div id="scan-status" style="margin: 10px 0; color: #64748b;"></div>
            <table>
                <thead>
                    <tr>
                        <th data-i18n="th.ssid">SSID</th>
                        <th data-i18n="th.bssid">BSSID</th>
                        <th data-i18n="th.signal">Signal</th>
                        <th data-i18n="th.freq">Freq</th>
                        <th data-i18n="th.security">Security</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="network-list"><tr><td colspan="6" data-i18n="scan.click">Click Scan...</td></tr></tbody>
            </table>
        </div>
        <div class="card" style="margin-top: 20px;">
            <h2 data-i18n="card.connect">Connect manually</h2>
            <div class="form-group">
                <label data-i18n="th.ssid">SSID</label>
                <input type="text" id="connect-ssid" data-i18n-placeholder="ph.network" placeholder="Network name">
            </div>
            <div class="form-group">
                <label data-i18n="label.password">Password</label>
                <input type="password" id="connect-pass" data-i18n-placeholder="ph.password" placeholder="Password (leave blank for open)">
            </div>
            <div class="actions">
                <button class="btn btn-success" onclick="doConnect()" data-i18n="btn.connect">Connect</button>
                <button class="btn btn-danger" onclick="doDisconnect()" data-i18n="btn.disconnect">Disconnect</button>
            </div>
        </div>
    </div>

    <!-- Settings Tab -->
    <div id="tab-settings" class="tab-content">
        <div class="grid">
            <div class="card">
                <h2 data-i18n="card.iface">Interface Settings</h2>
                <div class="form-group">
                    <label>MTU</label>
                    <input type="number" id="set-mtu" value="1500" min="576" max="9000">
                </div>
                <div class="form-group">
                    <label data-i18n="label.txpower">TX Power (dBm)</label>
                    <input type="number" id="set-txpower" value="20" min="0" max="30">
                </div>
                <div class="form-group">
                    <label data-i18n="label.powersave">Power Save</label>
                    <select id="set-powersave">
                        <option value="0" data-i18n="opt.off">Off</option>
                        <option value="1" data-i18n="opt.on">On</option>
                    </select>
                </div>
                <div class="actions">
                    <button class="btn btn-primary" onclick="applySettings()" data-i18n="btn.apply">Apply</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Tests Tab -->
    <div id="tab-tests" class="tab-content">
        <div class="card">
            <h2><span data-i18n="card.tests">Driver Test Suite</span>
                <button class="btn btn-primary btn-sm" onclick="runTests()" style="float:right;" id="btn-run-tests" data-i18n="btn.runtests">
                    Run tests
                </button>
            </h2>
            <div id="test-summary" style="margin: 16px 0; color: #94a3b8;"></div>
            <div id="test-output" data-i18n="tests.click">Click "Run tests" to start the suite...</div>
        </div>
    </div>

    <!-- Advanced Tab -->
    <div id="tab-advanced" class="tab-content">
        <div class="adv-container">
            <div class="adv-sidebar">
                <div id="adv-categories"></div>
                <div id="adv-proplist" class="adv-props"></div>
            </div>
            <div class="adv-main">
                <div id="adv-editor" class="adv-empty" data-i18n="adv.pickcat">Select a category and property to configure.</div>
            </div>
        </div>
        <div class="adv-actions">
            <button class="btn btn-primary" onclick="saveAdvanced()" data-i18n="btn.saveapply">Save &amp; Apply</button>
            <button class="btn btn-outline" onclick="resetAdvanced()" data-i18n="btn.resetdefault">Reset to default</button>
            <button class="btn btn-warning" onclick="reloadModule()" data-i18n="btn.reloadmod">Reload module</button>
        </div>
        <div id="adv-pending-banner" class="adv-pending-banner" style="display:none;"></div>
    </div>
</div>

<footer class="footer">
    <div class="footer-by">
        <span data-i18n="footer.by">by</span>
        <a href="https://github.com/WimLee115" target="_blank" rel="noopener noreferrer">WimLee115</a>
        <span data-i18n="footer.and">&amp; the Linux community</span>
    </div>
</footer>

<div id="toast" class="toast" style="opacity: 0;"></div>

<script>
// ─── i18n ──────────────────────────────────────────────────────────────
const I18N = {
    en: {
        'status.loading': 'Loading...',
        'status.driver_off': 'Driver not loaded',
        'status.connected': 'Connected',
        'status.disconnected': 'Not connected',
        'status.none': 'None',
        'tab.overview': 'Overview', 'tab.networks': 'Networks',
        'tab.settings': 'Settings', 'tab.tests': 'Tests', 'tab.advanced': 'Advanced',
        'card.adapter': 'Adapter Info', 'card.connection': 'Connection',
        'card.stats': 'Statistics', 'card.driver': 'Driver Info',
        'card.scan': 'Available networks', 'card.connect': 'Connect manually',
        'card.iface': 'Interface Settings', 'card.tests': 'Driver Test Suite',
        'btn.scan': 'Scan', 'btn.connect': 'Connect', 'btn.disconnect': 'Disconnect',
        'btn.apply': 'Apply', 'btn.runtests': 'Run tests',
        'btn.saveapply': 'Save & Apply', 'btn.resetdefault': 'Reset to default',
        'btn.reloadmod': 'Reload module', 'btn.quickconnect': 'Connect',
        'th.ssid': 'SSID', 'th.bssid': 'BSSID', 'th.signal': 'Signal',
        'th.freq': 'Freq', 'th.security': 'Security',
        'label.password': 'Password', 'label.txpower': 'TX Power (dBm)',
        'label.powersave': 'Power Save', 'label.interface': 'Interface',
        'label.mac': 'MAC address', 'label.ip': 'IP address',
        'label.status': 'Status', 'label.mtu': 'MTU',
        'label.usbspeed': 'USB speed', 'label.usbdev': 'USB device',
        'label.signal': 'Signal', 'label.freq': 'Frequency',
        'label.txbitrate': 'TX bitrate', 'label.module': 'Module',
        'label.driver': 'Driver', 'label.kernel': 'Kernel',
        'label.srcversion': 'Srcversion', 'label.version': 'Version',
        'label.current': 'Current value (active)',
        'label.pending': 'Saved (waiting for restart)',
        'label.property': 'Property',
        'opt.off': 'Off', 'opt.on': 'On', 'opt.auto': 'Auto',
        'opt.auto_efuse': 'Auto (Efuse)', 'opt.none': 'None',
        'opt.minimal': 'Minimal', 'opt.maximal': 'Maximal',
        'opt.normal': 'Normal', 'opt.level2': 'Level 2',
        'opt.clockgating': 'Clock Gating', 'opt.powergating': 'Power Gating',
        'opt.nochange': 'No change', 'opt.only24': '2.4 GHz only',
        'opt.only5': '5 GHz only', 'opt.dualband': 'Dual-band',
        'opt.both_bands': 'Both bands',
        'opt.1stream': '1 stream', 'opt.2streams': '2 streams',
        'opt.error': 'Error', 'opt.warning': 'Warning', 'opt.notice': 'Notice',
        'opt.info': 'Info', 'opt.debug': 'Debug',
        'opt.usb3': 'USB 3.0', 'opt.usb2': 'USB 2.0',
        'opt.hidden': '(Hidden)',
        'stat.tx_data': 'TX Data', 'stat.rx_data': 'RX Data',
        'stat.tx_pkts': 'TX Packets', 'stat.rx_pkts': 'RX Packets',
        'stat.tx_err': 'TX Errors', 'stat.rx_err': 'RX Errors',
        'stat.tx_drop': 'TX Dropped', 'stat.rx_drop': 'RX Dropped',
        'ph.network': 'Network name',
        'ph.password': 'Password (leave blank for open)',
        'scan.click': 'Click Scan...',
        'scan.scanning': 'Scanning...',
        'scan.found': 'networks found',
        'scan.none': 'No networks found',
        'scan.error': 'Scan error',
        'scan.errorfmt': 'Error: ',
        'tests.click': 'Click "Run tests" to start the suite...',
        'tests.running': 'Running tests...',
        'tests.busy': 'Busy...',
        'tests.nooutput': 'No output',
        'tests.error': 'Error running tests',
        'tests.passed': 'passed',
        'tests.failed': 'failed',
        'tests.errors': 'errors',
        'tests.skipped': 'skipped',
        'conn.notconnected': 'Not connected to a network',
        'toast.enterssid': 'Enter an SSID',
        'toast.connected': 'Connected to ',
        'toast.connectfail': 'Connect failed',
        'toast.connecterr': 'Error connecting',
        'toast.disconnected': 'Disconnected',
        'toast.disconnerr': 'Error disconnecting',
        'toast.applied': 'Settings applied',
        'toast.applyerr': 'Error applying settings',
        'toast.nochanges': 'No changes to save',
        'toast.saved': 'Settings saved.',
        'toast.savedrestart': 'Settings saved. Module restart needed.',
        'toast.saveerr': 'Error saving',
        'toast.resetlocal': 'Local changes discarded',
        'toast.reloading': 'Reloading module...',
        'toast.reloaded': 'Module reloaded successfully',
        'toast.reloadfail': 'Reload failed',
        'toast.reloaderr': 'Error reloading',
        'adv.pickcat': 'Select a category and property to configure.',
        'adv.pickprop': 'Select a property to configure.',
        'adv.unavailable': 'Not available — this parameter is not compiled into the current module.',
        'adv.modulerestart': 'Module parameter — restart needed',
        'adv.reloadconfirm': 'Reload module?\\n\\nThe WiFi connection will be briefly interrupted. The adapter will reinitialise with the saved settings.\\n\\nContinue?',
        'adv.pending_1': ' unsaved change. Click "Save & Apply" to save, then "Reload module" to activate.',
        'adv.pending_n': ' unsaved changes. Click "Save & Apply" to save, then "Reload module" to activate.',
        'adv.pending_saved': 'There are saved changes that require a module restart. Click "Reload module" to activate.',
        'adv.cat.wireless': 'Wireless Mode',
        'adv.cat.channel': 'Channel & Bandwidth',
        'adv.cat.power': 'Power Management',
        'adv.cat.performance': 'Performance',
        'adv.cat.antenna': 'Antenna & Beamforming',
        'adv.cat.roaming': 'Roaming & Connection',
        'adv.cat.debug': 'Debug & Advanced',
        'card.trends': 'Trends (last 60 min)',
        'trend.signal': 'Signal',
        'trend.bitrate': 'TX bitrate',
        'trend.throughput': 'RX throughput',
        'trend.errors': 'Errors (Δ)',
        'trend.nodata': 'no data yet',
        'kbd.title': 'Keyboard shortcuts',
        'kbd.tab1': 'Overview tab', 'kbd.tab2': 'Networks tab',
        'kbd.tab3': 'Settings tab', 'kbd.tab4': 'Tests tab',
        'kbd.tab5': 'Advanced tab', 'kbd.scan': 'Scan networks',
        'kbd.refresh': 'Refresh status', 'kbd.theme': 'Toggle theme',
        'kbd.lang': 'Toggle language', 'kbd.help': 'Show this help',
        'footer.by': 'by',
        'footer.and': '& the Linux community',
    },
    nl: {
        'status.loading': 'Laden...',
        'status.driver_off': 'Driver niet geladen',
        'status.connected': 'Verbonden',
        'status.disconnected': 'Niet verbonden',
        'status.none': 'Geen',
        'tab.overview': 'Overzicht', 'tab.networks': 'Netwerken',
        'tab.settings': 'Instellingen', 'tab.tests': 'Tests', 'tab.advanced': 'Geavanceerd',
        'card.adapter': 'Adapter Info', 'card.connection': 'Verbinding',
        'card.stats': 'Statistieken', 'card.driver': 'Driver Info',
        'card.scan': 'Beschikbare Netwerken', 'card.connect': 'Handmatig Verbinden',
        'card.iface': 'Interface Instellingen', 'card.tests': 'Driver Test Suite',
        'btn.scan': 'Scannen', 'btn.connect': 'Verbinden', 'btn.disconnect': 'Verbreken',
        'btn.apply': 'Toepassen', 'btn.runtests': 'Tests Draaien',
        'btn.saveapply': 'Opslaan & Toepassen', 'btn.resetdefault': 'Standaard Herstellen',
        'btn.reloadmod': 'Module Herladen', 'btn.quickconnect': 'Verbind',
        'th.ssid': 'SSID', 'th.bssid': 'BSSID', 'th.signal': 'Signaal',
        'th.freq': 'Freq', 'th.security': 'Beveiliging',
        'label.password': 'Wachtwoord', 'label.txpower': 'TX Power (dBm)',
        'label.powersave': 'Power Save', 'label.interface': 'Interface',
        'label.mac': 'MAC Adres', 'label.ip': 'IP Adres',
        'label.status': 'Status', 'label.mtu': 'MTU',
        'label.usbspeed': 'USB Snelheid', 'label.usbdev': 'USB Apparaat',
        'label.signal': 'Signaal', 'label.freq': 'Frequentie',
        'label.txbitrate': 'TX Bitrate', 'label.module': 'Module',
        'label.driver': 'Driver', 'label.kernel': 'Kernel',
        'label.srcversion': 'Srcversion', 'label.version': 'Versie',
        'label.current': 'Huidige waarde (actief)',
        'label.pending': 'Opgeslagen (wacht op herstart)',
        'label.property': 'Eigenschap',
        'opt.off': 'Uit', 'opt.on': 'Aan', 'opt.auto': 'Auto',
        'opt.auto_efuse': 'Auto (Efuse)', 'opt.none': 'Geen',
        'opt.minimal': 'Minimaal', 'opt.maximal': 'Maximaal',
        'opt.normal': 'Normaal', 'opt.level2': 'Level 2',
        'opt.clockgating': 'Clock Gating', 'opt.powergating': 'Power Gating',
        'opt.nochange': 'Geen wijziging', 'opt.only24': 'Alleen 2.4 GHz',
        'opt.only5': 'Alleen 5 GHz', 'opt.dualband': 'Dual-band',
        'opt.both_bands': 'Beide banden',
        'opt.1stream': '1 Stream', 'opt.2streams': '2 Streams',
        'opt.error': 'Error', 'opt.warning': 'Warning', 'opt.notice': 'Notice',
        'opt.info': 'Info', 'opt.debug': 'Debug',
        'opt.usb3': 'USB 3.0', 'opt.usb2': 'USB 2.0',
        'opt.hidden': '(Verborgen)',
        'stat.tx_data': 'TX Data', 'stat.rx_data': 'RX Data',
        'stat.tx_pkts': 'TX Pakketten', 'stat.rx_pkts': 'RX Pakketten',
        'stat.tx_err': 'TX Fouten', 'stat.rx_err': 'RX Fouten',
        'stat.tx_drop': 'TX Dropped', 'stat.rx_drop': 'RX Dropped',
        'ph.network': 'Netwerknaam',
        'ph.password': 'Wachtwoord (leeg voor open)',
        'scan.click': 'Klik op Scannen...',
        'scan.scanning': 'Scannen...',
        'scan.found': 'netwerken gevonden',
        'scan.none': 'Geen netwerken gevonden',
        'scan.error': 'Fout bij scannen',
        'scan.errorfmt': 'Fout: ',
        'tests.click': 'Klik op "Tests Draaien" om de testsuite te starten...',
        'tests.running': 'Tests worden uitgevoerd...',
        'tests.busy': 'Bezig...',
        'tests.nooutput': 'Geen output',
        'tests.error': 'Fout bij uitvoeren tests',
        'tests.passed': 'geslaagd',
        'tests.failed': 'gefaald',
        'tests.errors': 'fouten',
        'tests.skipped': 'overgeslagen',
        'conn.notconnected': 'Niet verbonden met een netwerk',
        'toast.enterssid': 'Voer een SSID in',
        'toast.connected': 'Verbonden met ',
        'toast.connectfail': 'Verbinden mislukt',
        'toast.connecterr': 'Fout bij verbinden',
        'toast.disconnected': 'Verbinding verbroken',
        'toast.disconnerr': 'Fout bij verbreken',
        'toast.applied': 'Instellingen toegepast',
        'toast.applyerr': 'Fout bij toepassen',
        'toast.nochanges': 'Geen wijzigingen om op te slaan',
        'toast.saved': 'Instellingen opgeslagen.',
        'toast.savedrestart': 'Instellingen opgeslagen. Module herstart nodig.',
        'toast.saveerr': 'Fout bij opslaan',
        'toast.resetlocal': 'Lokale wijzigingen gewist',
        'toast.reloading': 'Module wordt herladen...',
        'toast.reloaded': 'Module succesvol herladen',
        'toast.reloadfail': 'Herladen mislukt',
        'toast.reloaderr': 'Fout bij herladen',
        'adv.pickcat': 'Selecteer een categorie en eigenschap om te configureren.',
        'adv.pickprop': 'Selecteer een eigenschap om te configureren.',
        'adv.unavailable': 'Niet beschikbaar — deze parameter is niet gecompileerd in de huidige module.',
        'adv.modulerestart': 'Module parameter — herstart nodig',
        'adv.reloadconfirm': 'Module herladen?\\n\\nDe WiFi-verbinding wordt tijdelijk verbroken. De adapter wordt opnieuw geïnitialiseerd met de opgeslagen instellingen.\\n\\nDoorgaan?',
        'adv.pending_1': ' onopgeslagen wijziging. Klik "Opslaan & Toepassen" om op te slaan, daarna "Module Herladen" om te activeren.',
        'adv.pending_n': ' onopgeslagen wijzigingen. Klik "Opslaan & Toepassen" om op te slaan, daarna "Module Herladen" om te activeren.',
        'adv.pending_saved': 'Er zijn opgeslagen wijzigingen die een module herstart vereisen. Klik "Module Herladen" om te activeren.',
        'adv.cat.wireless': 'Draadloze Modus',
        'adv.cat.channel': 'Kanaal & Bandbreedte',
        'adv.cat.power': 'Energiebeheer',
        'adv.cat.performance': 'Prestaties',
        'adv.cat.antenna': 'Antenne & Beamforming',
        'adv.cat.roaming': 'Roaming & Verbinding',
        'adv.cat.debug': 'Debug & Geavanceerd',
        'card.trends': 'Trends (laatste 60 min)',
        'trend.signal': 'Signaal',
        'trend.bitrate': 'TX bitrate',
        'trend.throughput': 'RX doorvoer',
        'trend.errors': 'Fouten (Δ)',
        'trend.nodata': 'nog geen data',
        'kbd.title': 'Sneltoetsen',
        'kbd.tab1': 'Overzicht-tab', 'kbd.tab2': 'Netwerken-tab',
        'kbd.tab3': 'Instellingen-tab', 'kbd.tab4': 'Tests-tab',
        'kbd.tab5': 'Geavanceerd-tab', 'kbd.scan': 'Netwerken scannen',
        'kbd.refresh': 'Status verversen', 'kbd.theme': 'Thema wisselen',
        'kbd.lang': 'Taal wisselen', 'kbd.help': 'Deze help tonen',
        'footer.by': 'door',
        'footer.and': '& de Linux-community',
    }
};

let LANG = localStorage.getItem('rtw_lang')
        || (navigator.language && navigator.language.toLowerCase().startsWith('nl') ? 'nl' : 'en');
let THEME = localStorage.getItem('rtw_theme') || 'dark';

function t(k) { return (I18N[LANG] && I18N[LANG][k]) || I18N.en[k] || k; }

function applyTranslations() {
    document.documentElement.setAttribute('lang', LANG);
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('.lang-btn[data-lang]').forEach(b => {
        b.classList.toggle('active', b.dataset.lang === LANG);
    });
    document.querySelectorAll('.lang-btn[data-theme-btn]').forEach(b => {
        b.classList.toggle('active', b.dataset.themeBtn === THEME);
    });
}

function setLanguage(lang) {
    if (!I18N[lang]) return;
    LANG = lang;
    localStorage.setItem('rtw_lang', lang);
    applyTranslations();
    refreshStatus();
    refreshDriverInfo();
    if (advLoaded) {
        renderAdvCategories();
        if (advSelectedCat) {
            renderAdvProperties(advSelectedCat);
            if (advSelectedParam) renderAdvEditor(advSelectedCat, advSelectedParam);
        }
        updatePendingBanner(Object.keys(advChanges).length > 0);
    }
    drawAllTrends();
}

function setTheme(theme) {
    if (theme !== 'light' && theme !== 'dark') return;
    THEME = theme;
    localStorage.setItem('rtw_theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    applyTranslations();
    drawAllTrends();
}

function toggleKbdHelp() {
    document.getElementById('kbd-overlay').classList.toggle('open');
}

document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tabs = ['overview','networks','settings','tests','advanced'];
    if (e.key >= '1' && e.key <= '5') { switchTab(tabs[+e.key - 1]); }
    else if (e.key === '/') { e.preventDefault(); switchTab('networks'); doScan(); }
    else if (e.key === 'r') { refreshStatus(); refreshDriverInfo(); refreshTrends(); }
    else if (e.key === 't') { setTheme(THEME === 'dark' ? 'light' : 'dark'); }
    else if (e.key === 'l') { setLanguage(LANG === 'en' ? 'nl' : 'en'); }
    else if (e.key === '?' || (e.shiftKey && e.key === '/')) { toggleKbdHelp(); }
    else if (e.key === 'Escape') { document.getElementById('kbd-overlay').classList.remove('open'); }
});

// ── Trend sparklines ───────────────────────────────────────────────────
let TRENDS = { samples: [] };

function themeColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function drawSparkline(canvas, values, opts) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(rect.width * dpr, 100);
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    const w = rect.width, h = rect.height;
    ctx.clearRect(0, 0, w, h);
    const clean = values.filter(v => v !== null && v !== undefined && !Number.isNaN(v));
    if (clean.length < 2) {
        ctx.fillStyle = themeColor('--text-dim');
        ctx.font = '11px sans-serif';
        ctx.fillText(t('trend.nodata'), 4, h / 2 + 4);
        return;
    }
    let min = Math.min(...clean), max = Math.max(...clean);
    if (opts && opts.minClamp !== undefined) min = Math.min(min, opts.minClamp);
    if (opts && opts.maxClamp !== undefined) max = Math.max(max, opts.maxClamp);
    const range = (max - min) || 1;
    const pad = 2;
    const stepX = (w - 2 * pad) / Math.max(values.length - 1, 1);
    // Fill under the line for nicer visual weight.
    ctx.beginPath();
    ctx.moveTo(pad, h - pad);
    values.forEach((v, i) => {
        if (v === null || v === undefined || Number.isNaN(v)) return;
        const x = pad + i * stepX;
        const y = h - pad - ((v - min) / range) * (h - 2 * pad);
        ctx.lineTo(x, y);
    });
    ctx.lineTo(w - pad, h - pad);
    ctx.closePath();
    ctx.fillStyle = (opts && opts.fill) || themeColor('--accent') + '22';
    ctx.fill();
    // Stroke on top.
    ctx.beginPath();
    let started = false;
    values.forEach((v, i) => {
        if (v === null || v === undefined || Number.isNaN(v)) return;
        const x = pad + i * stepX;
        const y = h - pad - ((v - min) / range) * (h - 2 * pad);
        if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    });
    ctx.strokeStyle = (opts && opts.stroke) || themeColor('--accent');
    ctx.lineWidth = 1.5;
    ctx.stroke();
}

function fmtBytesPerSec(bps) {
    if (bps == null || Number.isNaN(bps)) return '–';
    if (bps < 1024) return bps.toFixed(0) + ' B/s';
    if (bps < 1024 * 1024) return (bps / 1024).toFixed(1) + ' KB/s';
    return (bps / (1024 * 1024)).toFixed(2) + ' MB/s';
}

function drawAllTrends() {
    const samples = TRENDS.samples || [];
    const signals = samples.map(s => s.signal);
    const bitrates = samples.map(s => s.bitrate);
    // Throughput is the per-sample delta in rx_bytes / dt seconds.
    const throughputs = samples.map((s, i) => {
        if (i === 0) return null;
        const dt = s.t - samples[i - 1].t;
        if (dt <= 0) return null;
        return (s.rx_bytes - samples[i - 1].rx_bytes) / dt;
    });
    const errorDeltas = samples.map((s, i) => {
        if (i === 0) return 0;
        return Math.max(0, s.errors - samples[i - 1].errors);
    });

    drawSparkline(document.getElementById('trend-signal'), signals, {});
    drawSparkline(document.getElementById('trend-bitrate'), bitrates, {minClamp: 0});
    drawSparkline(document.getElementById('trend-throughput'), throughputs, {minClamp: 0});
    drawSparkline(document.getElementById('trend-errors'), errorDeltas,
                  {minClamp: 0, stroke: '#dc2626', fill: '#dc262633'});

    const last = samples[samples.length - 1] || {};
    document.getElementById('trend-signal-val').textContent =
        last.signal != null ? last.signal + ' dBm' : '–';
    document.getElementById('trend-bitrate-val').textContent =
        last.bitrate != null ? last.bitrate.toFixed(0) + ' Mbps' : '–';
    const lastTp = throughputs[throughputs.length - 1];
    document.getElementById('trend-throughput-val').textContent = fmtBytesPerSec(lastTp);
    const recentErrors = errorDeltas.slice(-12).reduce((a, b) => a + b, 0);
    document.getElementById('trend-errors-val').textContent = String(recentErrors);
}

async function refreshTrends() {
    try {
        const r = await fetch('/api/history');
        const d = await r.json();
        TRENDS = d;
        drawAllTrends();
    } catch (e) {
        console.error('History fetch failed:', e);
    }
}
window.addEventListener('resize', () => drawAllTrends());

function formatBytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
    if (b < 1073741824) return (b/1048576).toFixed(1) + ' MB';
    return (b/1073741824).toFixed(2) + ' GB';
}

function signalColor(dbm) {
    if (dbm >= -50) return '#22c55e';
    if (dbm >= -60) return '#84cc16';
    if (dbm >= -70) return '#eab308';
    if (dbm >= -80) return '#f97316';
    return '#ef4444';
}

function signalPercent(dbm) {
    return Math.max(0, Math.min(100, (dbm + 100) * 2));
}

function showToast(msg, ok) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (ok ? 'toast-ok' : 'toast-err');
    t.style.opacity = '1';
    setTimeout(() => t.style.opacity = '0', 3000);
}

function switchTab(name) {
    document.querySelectorAll('.tab').forEach(el => {
        el.classList.toggle('active', el.dataset.tab === name);
    });
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    if (name === 'advanced' && !advLoaded) loadAdvanced();
}

let prevStats = null;

async function refreshStatus() {
    try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const badge = document.getElementById('status-badge');

        if (!d.driver_loaded) {
            badge.textContent = t('status.driver_off');
            badge.className = 'status-badge badge-err';
            return;
        }

        badge.textContent = d.operstate === 'up' || d.operstate === 'dormant'
            ? t('status.connected') : t('status.disconnected');
        badge.className = 'status-badge ' + (d.connection.ssid ? 'badge-ok' : 'badge-err');

        document.getElementById('adapter-info').innerHTML = `
            <div class="info-row"><span class="info-label">${t('label.interface')}</span><span class="info-value">${d.interface}</span></div>
            <div class="info-row"><span class="info-label">${t('label.mac')}</span><span class="info-value">${d.mac_address}</span></div>
            <div class="info-row"><span class="info-label">${t('label.ip')}</span><span class="info-value">${d.ip_address || t('status.none')}</span></div>
            <div class="info-row"><span class="info-label">${t('label.status')}</span><span class="info-value">${d.operstate}</span></div>
            <div class="info-row"><span class="info-label">${t('label.mtu')}</span><span class="info-value">${d.mtu}</span></div>
            <div class="info-row"><span class="info-label">${t('label.usbspeed')}</span><span class="info-value">${d.usb_speed_mbps} Mbps</span></div>
            <div class="info-row"><span class="info-label">${t('label.usbdev')}</span><span class="info-value">${d.usb_vendor}:${d.usb_product} (${d.usb_product_name})</span></div>
        `;

        const conn = d.connection;
        let connHtml = '';
        if (conn.ssid) {
            const pct = signalPercent(conn.signal_dbm);
            const col = signalColor(conn.signal_dbm);
            connHtml = `
                <div class="info-row"><span class="info-label">${t('th.ssid')}</span><span class="info-value">${conn.ssid}</span></div>
                <div class="info-row"><span class="info-label">${t('label.signal')}</span><span class="info-value">${conn.signal_dbm} dBm</span></div>
                <div class="signal-bar"><div class="signal-fill" style="width:${pct}%;background:${col};"></div></div>
                <div class="info-row"><span class="info-label">${t('label.freq')}</span><span class="info-value">${conn.frequency_mhz} MHz</span></div>
                <div class="info-row"><span class="info-label">${t('label.txbitrate')}</span><span class="info-value">${conn.tx_bitrate || 'N/A'}</span></div>
            `;
        } else {
            connHtml = `<div style="color:#64748b;padding:20px;text-align:center;">${t('conn.notconnected')}</div>`;
        }
        document.getElementById('connection-info').innerHTML = connHtml;

        const s = d.statistics;
        document.getElementById('stats-info').innerHTML = `
            <div class="stat-box"><div class="stat-value">${formatBytes(s.tx_bytes)}</div><div class="stat-label">${t('stat.tx_data')}</div></div>
            <div class="stat-box"><div class="stat-value">${formatBytes(s.rx_bytes)}</div><div class="stat-label">${t('stat.rx_data')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_packets.toLocaleString()}</div><div class="stat-label">${t('stat.tx_pkts')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_packets.toLocaleString()}</div><div class="stat-label">${t('stat.rx_pkts')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_errors}</div><div class="stat-label">${t('stat.tx_err')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_errors}</div><div class="stat-label">${t('stat.rx_err')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_dropped}</div><div class="stat-label">${t('stat.tx_drop')}</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_dropped}</div><div class="stat-label">${t('stat.rx_drop')}</div></div>
        `;

        prevStats = s;
    } catch(e) {
        console.error('Status refresh failed:', e);
    }
}

async function refreshDriverInfo() {
    try {
        const r = await fetch('/api/driver');
        const d = await r.json();
        document.getElementById('driver-info').innerHTML = `
            <div class="info-row"><span class="info-label">${t('label.module')}</span><span class="info-value">${d.module_name}</span></div>
            <div class="info-row"><span class="info-label">${t('label.driver')}</span><span class="info-value">${d.driver_name}</span></div>
            <div class="info-row"><span class="info-label">${t('label.kernel')}</span><span class="info-value">${d.kernel_version}</span></div>
            <div class="info-row"><span class="info-label">${t('label.srcversion')}</span><span class="info-value" style="font-size:0.75rem;">${d.srcversion}</span></div>
            <div class="info-row"><span class="info-label">${t('label.version')}</span><span class="info-value">${d.modinfo?.version || 'N/A'}</span></div>
        `;
    } catch(e) {}
}

async function doScan() {
    document.getElementById('scan-status').innerHTML = '<span class="spinner"></span> ' + t('scan.scanning');
    document.getElementById('network-list').innerHTML = '';
    try {
        const r = await fetch('/api/scan');
        const d = await r.json();
        if (d.error) {
            document.getElementById('scan-status').textContent = t('scan.errorfmt') + d.error;
            return;
        }
        document.getElementById('scan-status').textContent = d.count + ' ' + t('scan.found');
        let html = '';
        for (const n of d.networks) {
            const pct = signalPercent(n.signal);
            const col = signalColor(n.signal);
            html += `<tr>
                <td><strong>${n.ssid || t('opt.hidden')}</strong></td>
                <td style="font-family:monospace;font-size:0.8rem;">${n.bssid}</td>
                <td>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <div style="width:60px;height:6px;background:#334155;border-radius:3px;">
                            <div style="width:${pct}%;height:100%;background:${col};border-radius:3px;"></div>
                        </div>
                        <span style="font-size:0.8rem;">${n.signal !== null ? n.signal + ' dBm' : '?'}</span>
                    </div>
                </td>
                <td>${n.frequency || '?'} MHz</td>
                <td>${n.security}</td>
                <td><button class="btn btn-success btn-sm" onclick="quickConnect('${n.ssid.replace(/'/g,"\\\\'")}')">${t('btn.quickconnect')}</button></td>
            </tr>`;
        }
        document.getElementById('network-list').innerHTML = html || `<tr><td colspan="6">${t('scan.none')}</td></tr>`;
    } catch(e) {
        document.getElementById('scan-status').textContent = t('scan.error');
    }
}

function quickConnect(ssid) {
    document.getElementById('connect-ssid').value = ssid;
    document.getElementById('connect-pass').focus();
}

async function doConnect() {
    const ssid = document.getElementById('connect-ssid').value;
    const pass = document.getElementById('connect-pass').value;
    if (!ssid) { showToast(t('toast.enterssid'), false); return; }

    try {
        const r = await fetch('/api/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid, password: pass})
        });
        const d = await r.json();
        if (d.success) {
            showToast(t('toast.connected') + ssid, true);
            refreshStatus();
        } else {
            showToast(d.error || d.warning || t('toast.connectfail'), false);
        }
    } catch(e) {
        showToast(t('toast.connecterr'), false);
    }
}

async function doDisconnect() {
    try {
        await fetch('/api/disconnect', {method: 'POST'});
        showToast(t('toast.disconnected'), true);
        refreshStatus();
    } catch(e) {
        showToast(t('toast.disconnerr'), false);
    }
}

async function applySettings() {
    const data = {
        mtu: parseInt(document.getElementById('set-mtu').value),
        txpower: parseInt(document.getElementById('set-txpower').value),
        power_save: document.getElementById('set-powersave').value === '1'
    };
    try {
        const r = await fetch('/api/ifconfig', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        const d = await r.json();
        showToast(t('toast.applied'), true);
        refreshStatus();
    } catch(e) {
        showToast(t('toast.applyerr'), false);
    }
}

async function runTests() {
    const btn = document.getElementById('btn-run-tests');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> ' + t('tests.busy');
    document.getElementById('test-output').textContent = t('tests.running');
    document.getElementById('test-summary').textContent = '';

    try {
        const r = await fetch('/api/tests/run', {method: 'POST'});
        const d = await r.json();

        let html = '';
        if (d.output) {
            html = d.output.replace(/\\.\\.\\.\\s*ok/g, '... <span class="test-pass">OK</span>')
                          .replace(/FAIL/g, '<span class="test-fail">FAIL</span>')
                          .replace(/ERROR/g, '<span class="test-fail">ERROR</span>');
        }
        document.getElementById('test-output').innerHTML = html || d.stderr || t('tests.nooutput');

        if (d.report) {
            const rp = d.report;
            const color = rp.failed === 0 && rp.errors === 0 ? '#6ee7b7' : '#fca5a5';
            document.getElementById('test-summary').innerHTML =
                `<span style="color:${color};font-size:1.1rem;font-weight:600;">` +
                `${rp.passed}/${rp.total} ${t('tests.passed')}</span> | ` +
                `${rp.failed} ${t('tests.failed')} | ${rp.errors} ${t('tests.errors')} | ${rp.skipped} ${t('tests.skipped')}`;
        }
    } catch(e) {
        document.getElementById('test-output').textContent = t('tests.error');
    }

    btn.disabled = false;
    btn.textContent = t('btn.runtests');
}

// ── Advanced Tab Logic ───────────────────────────────────────────────

let advLoaded = false;
let advData = {};
let advChanges = {};
let advSelectedCat = null;
let advSelectedParam = null;

// All labels and descriptions carry both languages. Helper L() / D() pull
// the active language at render time so a language switch immediately
// re-skins the advanced tab without a refetch.
function L(p) { return (p.label && (p.label[LANG] || p.label.en)) || ''; }
function D(p) { return (p.desc  && (p.desc[LANG]  || p.desc.en))  || ''; }

const ADV_SETTINGS = {
    wireless: {
        labelKey: 'adv.cat.wireless',
        params: {
            rtw_ht_enable:     {
                label: { en: '802.11n (HT)', nl: '802.11n (HT)' },
                desc:  { en: 'Enable or disable 802.11n High Throughput. Required for WiFi 4 speeds above 54 Mbps.',
                         nl: 'Schakel 802.11n High Throughput in of uit. Vereist voor WiFi 4 snelheden boven 54 Mbps.' } },
            rtw_vht_enable:    {
                label: { en: '802.11ac (VHT)', nl: '802.11ac (VHT)' },
                desc:  { en: 'Enable or disable 802.11ac Very High Throughput. Required for WiFi 5 speeds up to 866 Mbps on 80 MHz.',
                         nl: 'Schakel 802.11ac Very High Throughput in of uit. Vereist voor WiFi 5 snelheden tot 866 Mbps op 80 MHz.' } },
            rtw_he_enable:     {
                label: { en: '802.11ax (HE)', nl: '802.11ax (HE)' },
                desc:  { en: 'Enable or disable 802.11ax High Efficiency. This is WiFi 6 \u2014 the newest standard with higher speeds and better behaviour in crowded environments.',
                         nl: 'Schakel 802.11ax High Efficiency in of uit. Dit is WiFi 6 \u2014 de nieuwste standaard met hogere snelheden en betere prestaties in drukke omgevingen.' } },
            rtw_wireless_mode: {
                label: { en: 'Wireless mode (bitmask)', nl: 'Draadloze Modus (bitmask)' },
                desc:  { en: 'Bitmask of supported wireless modes. 0 = automatic (all modes). Change only if you want to force specific modes.',
                         nl: 'Bitmask voor ondersteunde draadloze modi. 0 = automatisch (alle modi). Wijzig alleen als u specifieke modi wilt forceren.' } },
            rtw_band_type:     {
                label: { en: 'Frequency band', nl: 'Frequentieband' },
                desc:  { en: 'Pick which frequency bands the adapter may use. Dual-band (default) gives the best compatibility.',
                         nl: 'Kies welke frequentiebanden de adapter mag gebruiken. Dual-band (standaard) biedt de beste compatibiliteit.' } },
        }
    },
    channel: {
        labelKey: 'adv.cat.channel',
        params: {
            rtw_channel:       {
                label: { en: 'Default channel', nl: 'Standaard Kanaal' },
                desc:  { en: 'Default channel at startup. 0 = automatic. For 2.4 GHz: 1\u201313. For 5 GHz: 36, 40, 44, 48, 52, \u2026',
                         nl: 'Het standaardkanaal bij opstarten. 0 = automatisch. Voor 2.4 GHz: 1\u201313. Voor 5 GHz: 36, 40, 44, 48, 52, etc.' } },
            rtw_bw_mode:       {
                label: { en: 'Channel width (bitmask)', nl: 'Kanaal Breedte (bitmask)' },
                desc:  { en: 'Bitmask of channel width per band. Bits 0\u20133: 2.4 GHz (0x01=20MHz, 0x03=40MHz). Bits 4\u20137: 5 GHz (0x10=20MHz, 0x30=40MHz, 0x70=80MHz). Default 0x31 (40 MHz 2.4G + 80 MHz 5G).',
                         nl: 'Bitmask voor kanaalbreedte per band. Bits 0\u20133: 2.4 GHz (0x01=20MHz, 0x03=40MHz). Bits 4\u20137: 5 GHz (0x10=20MHz, 0x30=40MHz, 0x70=80MHz). Standaard 0x31 (40 MHz 2.4G + 80 MHz 5G).' } },
            rtw_channel_plan:  {
                label: { en: 'Channel plan', nl: 'Kanaalplan' },
                desc:  { en: 'Regulatory channel plan (0x00\u20130xFF). Decides which channels are available per region. 0xFF = automatic.',
                         nl: 'Reguleringskanaalplan (0x00\u20130xFF). Bepaalt welke kanalen beschikbaar zijn op basis van regio. 0xFF = automatisch.' } },
            rtw_country_code:  {
                label: { en: 'Country code', nl: 'Landcode' },
                desc:  { en: 'ISO 3166-1 alpha-2 country code (e.g. NL, US, DE, GB). Decides regulatory domain and available channels / TX power.',
                         nl: 'ISO 3166-1 alpha-2 landcode (bijv. NL, US, DE, GB). Bepaalt reguleringsdomein en beschikbare kanalen/vermogen.' } },
        }
    },
    power: {
        labelKey: 'adv.cat.power',
        params: {
            rtw_power_mgnt:    {
                label: { en: 'Power management mode', nl: 'Power Management Modus' },
                desc:  { en: 'Power management level. Off = maximum performance but higher consumption. Maximum = longest battery life but possibly lower throughput.',
                         nl: 'Stel het energiebeheerniveau in. Uit = maximale prestaties maar hoger verbruik. Maximaal = langste batterijduur maar mogelijk lagere throughput.' } },
            rtw_ips_mode:      {
                label: { en: 'Idle Power Save (IPS)', nl: 'Idle Power Save (IPS)' },
                desc:  { en: 'Power saving when the adapter is idle. Normal turns the radio off when idle. Level 2 is more aggressive.',
                         nl: 'Energiebesparing wanneer de adapter inactief is. Normaal schakelt de radio uit bij inactiviteit. Level 2 is agressiever.' } },
            rtw_lps_level:     {
                label: { en: 'Low Power Save level', nl: 'Low Power Save Niveau' },
                desc:  { en: 'Power saving level while connected. Clock Gating saves moderately. Power Gating saves the most but can increase latency.',
                         nl: 'Energiebesparingsniveau tijdens verbinding. Clock Gating bespaart matig. Power Gating bespaart maximaal maar kan latentie verhogen.' } },
        }
    },
    performance: {
        labelKey: 'adv.cat.performance',
        params: {
            rtw_ampdu_enable:  {
                label: { en: 'AMPDU', nl: 'AMPDU' },
                desc:  { en: 'Aggregate MAC Protocol Data Unit. Bundles multiple frames into one transmission for higher throughput. Recommended: On.',
                         nl: 'Aggregate MAC Protocol Data Unit. Bundelt meerdere frames in \u00e9\u00e9n transmissie voor hogere throughput. Aanbevolen: Aan.' } },
            rtw_en_napi:       {
                label: { en: 'NAPI', nl: 'NAPI' },
                desc:  { en: 'New API for network-interrupt handling. Reduces CPU load at high packet rates. Recommended: On.',
                         nl: 'New API voor netwerkinterruptverwerking. Vermindert CPU-belasting bij hoge pakketsnelheden. Aanbevolen: Aan.' } },
            rtw_en_gro:        {
                label: { en: 'GRO', nl: 'GRO' },
                desc:  { en: 'Generic Receive Offload. Coalesces small received packets into larger ones for more efficient processing. Recommended: On.',
                         nl: 'Generic Receive Offload. Combineert kleine ontvangen pakketten tot grotere voor effici\u00ebntere verwerking. Aanbevolen: Aan.' } },
            rtw_switch_usb_mode: {
                label: { en: 'USB mode', nl: 'USB Modus' },
                desc:  { en: 'Force USB 2.0 or 3.0 mode. USB 3.0 gives higher speeds but can cause interference on 2.4 GHz. No change = automatic.',
                         nl: 'Forceer USB 2.0 of 3.0 modus. USB 3.0 biedt hogere snelheden maar kan interferentie op 2.4 GHz veroorzaken. Geen wijziging = automatisch.' } },
            rtw_wmm_enable:    {
                label: { en: 'WMM / QoS', nl: 'WMM / QoS' },
                desc:  { en: 'WiFi Multimedia / Quality of Service. Prioritises voice and video traffic over bulk data. Recommended: On.',
                         nl: 'WiFi Multimedia / Quality of Service. Prioriteert spraak- en videoverkeer boven bulkdata. Aanbevolen: Aan.' } },
        }
    },
    antenna: {
        labelKey: 'adv.cat.antenna',
        params: {
            rtw_beamform_cap:  {
                label: { en: 'Beamforming capability', nl: 'Beamforming Capaciteit' },
                desc:  { en: 'Beamforming bitmask. 0 = Off. Common values: 0x82 = SU Beamformee, 0x8A = SU+MU Beamformee. Beamforming aims the signal at the device for better range.',
                         nl: 'Beamforming bitmask. 0 = Uit. Veelgebruikte waarden: 0x82 = SU Beamformee, 0x8A = SU+MU Beamformee. Beamforming richt het signaal naar het apparaat voor beter bereik.' } },
            rtw_dyn_txbf:      {
                label: { en: 'Dynamic TX Beamforming', nl: 'Dynamische TX Beamforming' },
                desc:  { en: 'Dynamically switch between beamforming modes based on channel conditions. Recommended: On when beamforming is active.',
                         nl: 'Dynamisch schakelen tussen beamforming-modi op basis van kanaalcondities. Aanbevolen: Aan als beamforming actief is.' } },
            rtw_tx_nss:        {
                label: { en: 'TX Spatial Streams', nl: 'TX Spatial Streams' },
                desc:  { en: 'Number of transmit spatial streams. Auto lets the driver choose. 2 streams = maximum speed. 1 stream = lower power.',
                         nl: 'Aantal zend-spatial streams. Auto laat de driver kiezen. 2 streams = maximale snelheid. 1 stream = lager verbruik.' } },
            rtw_rx_nss:        {
                label: { en: 'RX Spatial Streams', nl: 'RX Spatial Streams' },
                desc:  { en: 'Number of receive spatial streams. Auto lets the driver choose. 2 streams = maximum speed.',
                         nl: 'Aantal ontvangst-spatial streams. Auto laat de driver kiezen. 2 streams = maximale snelheid.' } },
            rtw_antdiv_cfg:    {
                label: { en: 'Antenna diversity', nl: 'Antenne Diversiteit' },
                desc:  { en: 'Antenna diversity configuration. On = driver picks the best antenna. Auto (Efuse) = use factory settings.',
                         nl: 'Antenne-diversiteitconfiguratie. Aan = driver kiest beste antenne. Auto (Efuse) = gebruik fabrieksinstellingen.' } },
            rtw_rx_stbc:       {
                label: { en: 'RX STBC', nl: 'RX STBC' },
                desc:  { en: 'Space-Time Block Coding on receive. Improves reliability and range by adding redundancy across antennas. Both bands recommended.',
                         nl: 'Space-Time Block Coding voor ontvangst. Verbetert betrouwbaarheid en bereik door redundantie over antennes. Beide banden aanbevolen.' } },
        }
    },
    roaming: {
        labelKey: 'adv.cat.roaming',
        params: {
            rtw_max_roaming_times: {
                label: { en: 'Max roaming attempts', nl: 'Max Roaming Pogingen' },
                desc:  { en: 'Maximum number of times the adapter tries to roam to a better access point. 0 = roaming disabled. Higher values = more aggressive roaming.',
                         nl: 'Maximum aantal keren dat de adapter probeert te roamen naar een beter access point. 0 = roaming uitgeschakeld. Hogere waarden = agressiever roaming.' } },
            rtw_btcoex_enable: {
                label: { en: 'Bluetooth coexistence', nl: 'Bluetooth Coexistentie' },
                desc:  { en: 'Enable WiFi/Bluetooth coexistence. Prevents interference when Bluetooth is active. Auto = use factory settings.',
                         nl: 'Schakel WiFi/Bluetooth coexistentie in. Voorkomt interferentie wanneer Bluetooth tegelijk actief is. Auto = gebruik fabrieksinstellingen.' } },
        }
    },
    debug: {
        labelKey: 'adv.cat.debug',
        params: {
            rtw_drv_log_level: {
                label: { en: 'Log level', nl: 'Log Niveau' },
                desc:  { en: 'Driver log level in dmesg / kernel log. None = critical errors only. Debug = full diagnostics (slows the driver).',
                         nl: 'Driver log-niveau in dmesg/kernel log. Geen = alleen kritieke fouten. Debug = volledige diagnostiek (vertraagt de driver).' } },
            rtw_tx_pwr_by_rate: {
                label: { en: 'TX Power by Rate', nl: 'TX Power by Rate' },
                desc:  { en: 'Adjust TX power per data rate. On = follow the power-by-rate table. Auto = use factory settings from efuse.',
                         nl: 'Pas zendvermogen aan per datasnelheid. Aan = volg de power-by-rate tabel. Auto = gebruik fabrieksinstellingen uit efuse.' } },
            rtw_tx_pwr_lmt_enable: {
                label: { en: 'TX Power Limit', nl: 'TX Power Limiet' },
                desc:  { en: 'Cap TX power according to regulatory limits. Recommended: On or Auto to comply with local law.',
                         nl: 'Beperk zendvermogen volgens reguleringslimieten. Aanbevolen: Aan of Auto om te voldoen aan lokale wetgeving.' } },
        }
    }
};

async function loadAdvanced() {
    try {
        const r = await fetch('/api/advanced');
        const d = await r.json();
        advData = d.parameters || {};
        advChanges = {};
        advLoaded = true;
        renderAdvCategories();
        if (!advSelectedCat) {
            advSelectedCat = 'wireless';
            renderAdvCategories();
            renderAdvProperties('wireless');
        }
        updatePendingBanner(d.has_pending_changes);
    } catch(e) {
        console.error('Failed to load advanced settings:', e);
    }
}

function renderAdvCategories() {
    const el = document.getElementById('adv-categories');
    let html = '';
    for (const [key, cat] of Object.entries(ADV_SETTINGS)) {
        html += '<div class="adv-cat' + (advSelectedCat === key ? ' active' : '') +
                '" onclick="selectAdvCategory(\\''+key+'\\')">'+t(cat.labelKey)+'</div>';
    }
    el.innerHTML = html;
}

function selectAdvCategory(key) {
    advSelectedCat = key;
    advSelectedParam = null;
    renderAdvCategories();
    renderAdvProperties(key);
    document.getElementById('adv-editor').innerHTML = `<div class="adv-empty">${t('adv.pickprop')}</div>`;
}

function renderAdvProperties(catKey) {
    const el = document.getElementById('adv-proplist');
    const cat = ADV_SETTINGS[catKey];
    if (!cat) { el.innerHTML = ''; return; }
    let html = '';
    for (const [pname, pdef] of Object.entries(cat.params)) {
        const modified = pname in advChanges;
        html += '<div class="adv-prop' + (advSelectedParam === pname ? ' active' : '') +
                '" onclick="selectAdvParam(\\''+catKey+'\\',\\''+pname+'\\')">' +
                '<span>'+L(pdef)+'</span>' +
                (modified ? '<span class="adv-modified-dot"></span>' : '') +
                '</div>';
    }
    el.innerHTML = html;
}

function selectAdvParam(catKey, pname) {
    advSelectedParam = pname;
    renderAdvProperties(catKey);
    renderAdvEditor(catKey, pname);
}

function renderAdvEditor(catKey, pname) {
    const el = document.getElementById('adv-editor');
    const pdef = ADV_SETTINGS[catKey].params[pname];
    const paramData = advData[pname] || {};
    const currentVal = pname in advChanges ? advChanges[pname] : paramData.current;
    const isAvailable = paramData.current !== null && paramData.current !== undefined;

    if (!isAvailable) {
        el.innerHTML = '<div class="adv-editor-label">'+t('label.property')+'</div>' +
            '<div class="adv-editor-name">'+L(pdef)+'</div>' +
            '<div style="color:#fca5a5;padding:12px;background:#7f1d1d;border-radius:8px;">'+t('adv.unavailable')+'</div>' +
            '<div class="adv-desc" style="margin-top:auto;">'+D(pdef)+'</div>';
        return;
    }

    let inputHtml = '';
    const serverOpts = getParamOptions(pname);
    if (serverOpts) {
        inputHtml = '<select onchange="advValueChanged(\\''+pname+'\\', this.value)">';
        for (const [val, optKey] of Object.entries(serverOpts)) {
            inputHtml += '<option value="'+val+'"'+(String(currentVal)===val?' selected':'')+'>'+t(optKey)+' ('+val+')</option>';
        }
        inputHtml += '</select>';
    } else {
        inputHtml = '<input type="text" value="'+(currentVal!==null?currentVal:'')+'" onchange="advValueChanged(\\''+pname+'\\', this.value)">';
    }

    const pendingVal = paramData.pending;
    const statusHtml = '<span class="badge-module">'+t('adv.modulerestart')+'</span>';
    let pendingHtml = '';
    if (pendingVal !== undefined && pendingVal !== null && String(pendingVal) !== String(paramData.current)) {
        pendingHtml = '<div class="adv-current" style="color:#fbbf24;">'+t('label.pending')+': '+pendingVal+'</div>';
    }

    el.innerHTML =
        '<div class="adv-editor-label">'+t('label.property')+'</div>' +
        '<div class="adv-editor-name">'+L(pdef)+' '+statusHtml+'</div>' +
        '<div class="adv-editor-input">'+inputHtml+'</div>' +
        '<div class="adv-current">'+t('label.current')+': '+paramData.current+'</div>' +
        pendingHtml +
        '<div class="adv-desc">'+D(pdef)+'</div>';
}

function getParamOptions(pname) {
    // Each option value maps to an i18n key resolved at render time.
    const opts = {
        rtw_ht_enable:     {'0':'opt.off','1':'opt.on'},
        rtw_vht_enable:    {'0':'opt.off','1':'opt.on','2':'opt.auto'},
        rtw_he_enable:     {'0':'opt.off','1':'opt.on','2':'opt.auto'},
        rtw_band_type:     {'1':'opt.only24','2':'opt.only5','3':'opt.dualband'},
        rtw_power_mgnt:    {'0':'opt.off','1':'opt.minimal','2':'opt.maximal'},
        rtw_ips_mode:      {'0':'opt.none','1':'opt.normal','2':'opt.level2'},
        rtw_lps_level:     {'0':'opt.normal','1':'opt.clockgating','2':'opt.powergating'},
        rtw_ampdu_enable:  {'0':'opt.off','1':'opt.on'},
        rtw_en_napi:       {'0':'opt.off','1':'opt.on'},
        rtw_en_gro:        {'0':'opt.off','1':'opt.on'},
        rtw_switch_usb_mode: {'0':'opt.nochange','1':'opt.usb3','2':'opt.usb2'},
        rtw_wmm_enable:    {'0':'opt.off','1':'opt.on'},
        rtw_dyn_txbf:      {'0':'opt.off','1':'opt.on'},
        rtw_tx_nss:        {'0':'opt.auto','1':'opt.1stream','2':'opt.2streams'},
        rtw_rx_nss:        {'0':'opt.auto','1':'opt.1stream','2':'opt.2streams'},
        rtw_antdiv_cfg:    {'0':'opt.off','1':'opt.on','2':'opt.auto_efuse'},
        rtw_rx_stbc:       {'0':'opt.off','1':'opt.only24','2':'opt.only5','3':'opt.both_bands'},
        rtw_btcoex_enable: {'0':'opt.off','1':'opt.on','2':'opt.auto_efuse'},
        rtw_drv_log_level: {'0':'opt.none','1':'opt.error','2':'opt.warning','3':'opt.notice','4':'opt.info','5':'opt.debug'},
        rtw_tx_pwr_by_rate: {'0':'opt.off','1':'opt.on','2':'opt.auto_efuse'},
        rtw_tx_pwr_lmt_enable: {'0':'opt.off','1':'opt.on','2':'opt.auto_efuse'},
    };
    return opts[pname] || null;
}

function advValueChanged(pname, value) {
    const paramData = advData[pname] || {};
    if (String(value) === String(paramData.current)) {
        delete advChanges[pname];
    } else {
        advChanges[pname] = value;
    }
    if (advSelectedCat) renderAdvProperties(advSelectedCat);
    updatePendingBanner(Object.keys(advChanges).length > 0);
}

async function saveAdvanced() {
    if (Object.keys(advChanges).length === 0) {
        showToast(t('toast.nochanges'), false);
        return;
    }
    const moduleParams = {};
    for (const [k, v] of Object.entries(advChanges)) {
        moduleParams[k] = v;
    }
    try {
        const r = await fetch('/api/advanced', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: moduleParams})
        });
        const d = await r.json();
        showToast(d.reload_needed ? t('toast.savedrestart') : t('toast.saved'), true);
        advChanges = {};
        await loadAdvanced();
        if (advSelectedCat && advSelectedParam) {
            renderAdvProperties(advSelectedCat);
            renderAdvEditor(advSelectedCat, advSelectedParam);
        }
    } catch(e) {
        showToast(t('toast.saveerr'), false);
    }
}

function resetAdvanced() {
    advChanges = {};
    if (advSelectedCat) renderAdvProperties(advSelectedCat);
    if (advSelectedCat && advSelectedParam) renderAdvEditor(advSelectedCat, advSelectedParam);
    updatePendingBanner(false);
    showToast(t('toast.resetlocal'), true);
}

async function reloadModule() {
    if (!confirm(t('adv.reloadconfirm'))) return;
    showToast(t('toast.reloading'), true);
    try {
        const r = await fetch('/api/advanced/reload', {method: 'POST'});
        const d = await r.json();
        if (d.success) {
            showToast(d.message || t('toast.reloaded'), true);
            advLoaded = false;
            setTimeout(() => { loadAdvanced(); refreshStatus(); }, 2000);
        } else {
            showToast(d.error || t('toast.reloadfail'), false);
        }
    } catch(e) {
        showToast(t('toast.reloaderr'), false);
    }
}

function updatePendingBanner(show) {
    const el = document.getElementById('adv-pending-banner');
    if (show) {
        const n = Object.keys(advChanges).length;
        let txt;
        if (n > 0) {
            txt = n + (n === 1 ? t('adv.pending_1') : t('adv.pending_n'));
        } else {
            txt = t('adv.pending_saved');
        }
        el.textContent = '\u26A0 ' + txt;
        el.style.display = 'block';
    } else {
        el.style.display = 'none';
    }
}

// ── Initial load and auto-refresh ───────────────────────────────────
document.documentElement.setAttribute('data-theme', THEME);
applyTranslations();
refreshStatus();
refreshDriverInfo();
refreshTrends();
setInterval(() => { refreshStatus(); refreshTrends(); }, 5000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RTL8852AU WiFi Dashboard")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1, loopback only). "
             "Pass 0.0.0.0 to expose to the LAN — the auth token is then "
             "the only thing preventing remote root operations.",
    )
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("WARNING: Dashboard should run as root for full functionality")

    # Populate the Host-header whitelist used by before_request. Loopback
    # names are always allowed; if the user bound to a non-loopback
    # address we also accept that literal address and the machine's
    # hostname (best-effort).
    ALLOWED_HOSTS.update({"127.0.0.1", "localhost", "::1"})
    if args.host not in ("127.0.0.1", "localhost"):
        ALLOWED_HOSTS.add(args.host.lower())
        try:
            ALLOWED_HOSTS.add(socket.gethostname().lower())
        except OSError:
            pass
        print()
        print("=" * 64)
        print(" WARNING: dashboard is bound to a non-loopback address.")
        print(" Anyone reaching this host on the network needs the token")
        print(" below to interact with /api/* endpoints. Keep it private.")
        print("=" * 64)

    print()
    print(f" RTL8852AU Dashboard:  http://{args.host}:{args.port}/")
    print(f" Auth token         :  {AUTH_TOKEN}")
    print(f" Token file         :  {TOKEN_PATH}")
    print( " Login              :  any username, password = the token above")
    print()

    app.run(host=args.host, port=args.port, debug=False)
