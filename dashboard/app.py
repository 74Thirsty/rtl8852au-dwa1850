#!/usr/bin/env python3
"""
RTL8852AU WiFi Adapter Dashboard
Flask-based web interface for monitoring and configuring the WiFi adapter.

Usage: sudo python3 dashboard/app.py [--port 8080]
"""

import subprocess
import os
import re
import json
import time
import glob
import argparse
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

DRIVER_NAME = "rtl8852au"
MODULE_NAME = "8852au"


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


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
        with open(path) as f:
            return f.read().strip()
    except (IOError, OSError):
        return None


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
    rc, iw_out, _ = run(f"iw dev {iface} link")
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
    rc, ip_out, _ = run(f"ip -4 addr show {iface}")
    ip_addr = None
    if rc == 0:
        m = re.search(r'inet (\S+)', ip_out)
        if m:
            ip_addr = m.group(1)

    return jsonify({
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
    })


@app.route("/api/scan")
def api_scan():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    run(f"ip link set {iface} up")
    run(f"iw dev {iface} scan trigger")
    time.sleep(4)
    rc, out, err = run(f"iw dev {iface} scan dump", timeout=20)
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

    data = request.get_json()
    ssid = data.get("ssid", "")
    password = data.get("password", "")

    if not ssid:
        return jsonify({"error": "SSID is required"}), 400

    # Create wpa_supplicant config
    conf = f'network={{\n    ssid="{ssid}"\n'
    if password:
        conf += f'    psk="{password}"\n'
    else:
        conf += '    key_mgmt=NONE\n'
    conf += '}\n'

    conf_path = f"/tmp/wpa_{iface}.conf"
    with open(conf_path, "w") as f:
        f.write(f'ctrl_interface=/var/run/wpa_supplicant\nupdate_config=1\n\n{conf}')

    # Kill existing wpa_supplicant for this interface
    run(f"killall -9 wpa_supplicant 2>/dev/null; sleep 1")
    run(f"ip link set {iface} up")

    # Start wpa_supplicant
    rc, _, err = run(f"wpa_supplicant -B -i {iface} -c {conf_path}", timeout=10)
    if rc != 0:
        return jsonify({"error": f"wpa_supplicant failed: {err}"}), 500

    # Request DHCP
    run(f"dhclient -r {iface} 2>/dev/null")
    rc, _, err = run(f"dhclient {iface}", timeout=30)
    if rc != 0:
        return jsonify({"warning": "Connected but DHCP failed", "ssid": ssid})

    time.sleep(2)
    return jsonify({"success": True, "ssid": ssid})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    iface = get_wlan_interface()
    if not iface:
        return jsonify({"error": "No interface found"}), 404

    run(f"iw dev {iface} disconnect")
    run(f"killall wpa_supplicant 2>/dev/null")
    run(f"dhclient -r {iface} 2>/dev/null")
    return jsonify({"success": True})


@app.route("/api/driver")
def api_driver():
    rc, modinfo, _ = run(f"modinfo {MODULE_NAME}")
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
            rc, _, err = run(f"ip link set {iface} mtu {mtu}")
            results.append({"mtu": "ok" if rc == 0 else err})

    if "txpower" in data:
        txp = int(data["txpower"])
        if 0 <= txp <= 30:
            rc, _, err = run(f"iw dev {iface} set txpower fixed {txp * 100}")
            results.append({"txpower": "ok" if rc == 0 else err})

    if "power_save" in data:
        ps = "on" if data["power_save"] else "off"
        rc, _, err = run(f"iw dev {iface} set power_save {ps}")
        results.append({"power_save": "ok" if rc == 0 else err})

    return jsonify({"results": results})


@app.route("/api/tests/run", methods=["POST"])
def api_run_tests():
    """Run the driver test suite and return results."""
    test_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tests", "test_driver.py")
    if not os.path.exists(test_script):
        return jsonify({"error": "Test script not found"}), 404

    rc, out, err = run(f"python3 {test_script}", timeout=120)
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


# ── HTML Dashboard ────────────────────────────────────────────────────

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RTL8852AU WiFi Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0f172a; color: #e2e8f0; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1e293b, #334155);
           padding: 20px 30px; border-bottom: 1px solid #475569; display: flex;
           justify-content: space-between; align-items: center; }
.header h1 { font-size: 1.5rem; color: #38bdf8; }
.header .status-badge { padding: 6px 16px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
.badge-ok { background: #065f46; color: #6ee7b7; }
.badge-err { background: #7f1d1d; color: #fca5a5; }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 20px; margin-bottom: 20px; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
.card h2 { font-size: 1.1rem; color: #94a3b8; margin-bottom: 16px; text-transform: uppercase;
            letter-spacing: 0.05em; font-weight: 600; }
.info-row { display: flex; justify-content: space-between; padding: 8px 0;
            border-bottom: 1px solid #1e293b; }
.info-row:last-child { border-bottom: none; }
.info-label { color: #64748b; font-size: 0.9rem; }
.info-value { color: #e2e8f0; font-weight: 500; font-size: 0.9rem; }
.stat-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.stat-box { background: #0f172a; border-radius: 8px; padding: 14px; text-align: center; }
.stat-value { font-size: 1.5rem; font-weight: 700; color: #38bdf8; }
.stat-label { font-size: 0.75rem; color: #64748b; margin-top: 4px; text-transform: uppercase; }
.signal-bar { height: 8px; background: #334155; border-radius: 4px; overflow: hidden; margin-top: 8px; }
.signal-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
table { width: 100%; border-collapse: collapse; }
table th { text-align: left; padding: 10px 12px; background: #0f172a; color: #64748b;
           font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
table td { padding: 10px 12px; border-bottom: 1px solid #1e293b; font-size: 0.9rem; }
table tr:hover td { background: #0f172a; }
.btn { padding: 8px 20px; border: none; border-radius: 8px; cursor: pointer;
       font-size: 0.9rem; font-weight: 600; transition: all 0.2s; }
.btn-primary { background: #2563eb; color: white; }
.btn-primary:hover { background: #1d4ed8; }
.btn-danger { background: #dc2626; color: white; }
.btn-danger:hover { background: #b91c1c; }
.btn-success { background: #059669; color: white; }
.btn-success:hover { background: #047857; }
.btn-sm { padding: 5px 12px; font-size: 0.8rem; }
.form-group { margin-bottom: 12px; }
.form-group label { display: block; color: #94a3b8; font-size: 0.85rem; margin-bottom: 4px; }
.form-group input, .form-group select { width: 100%; padding: 8px 12px; background: #0f172a;
    border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; font-size: 0.9rem; }
.form-group input:focus { outline: none; border-color: #2563eb; }
.toast { position: fixed; bottom: 20px; right: 20px; padding: 12px 24px; border-radius: 8px;
         color: white; font-weight: 500; z-index: 100; transition: opacity 0.3s; }
.toast-ok { background: #059669; }
.toast-err { background: #dc2626; }
.actions { display: flex; gap: 10px; margin-top: 16px; }
.tab-bar { display: flex; gap: 4px; margin-bottom: 20px; }
.tab { padding: 10px 20px; background: #1e293b; border: 1px solid #334155; border-radius: 8px 8px 0 0;
       cursor: pointer; color: #64748b; font-weight: 500; }
.tab.active { background: #334155; color: #38bdf8; border-bottom-color: #334155; }
.tab-content { display: none; }
.tab-content.active { display: block; }
#test-output { background: #0f172a; padding: 16px; border-radius: 8px; font-family: monospace;
               font-size: 0.85rem; white-space: pre-wrap; max-height: 500px; overflow-y: auto;
               line-height: 1.6; }
.test-pass { color: #6ee7b7; }
.test-fail { color: #fca5a5; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #475569;
           border-top-color: #38bdf8; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<div class="header">
    <h1>RTL8852AU WiFi Dashboard</h1>
    <span id="status-badge" class="status-badge badge-ok">Laden...</span>
</div>

<div class="container">
    <div class="tab-bar">
        <div class="tab active" onclick="switchTab('overview')">Overzicht</div>
        <div class="tab" onclick="switchTab('networks')">Netwerken</div>
        <div class="tab" onclick="switchTab('settings')">Instellingen</div>
        <div class="tab" onclick="switchTab('tests')">Tests</div>
    </div>

    <!-- Overview Tab -->
    <div id="tab-overview" class="tab-content active">
        <div class="grid">
            <div class="card">
                <h2>Adapter Info</h2>
                <div id="adapter-info">Laden...</div>
            </div>
            <div class="card">
                <h2>Verbinding</h2>
                <div id="connection-info">Laden...</div>
            </div>
            <div class="card">
                <h2>Statistieken</h2>
                <div id="stats-info" class="stat-grid"></div>
            </div>
            <div class="card">
                <h2>Driver Info</h2>
                <div id="driver-info">Laden...</div>
            </div>
        </div>
    </div>

    <!-- Networks Tab -->
    <div id="tab-networks" class="tab-content">
        <div class="card">
            <h2>Beschikbare Netwerken
                <button class="btn btn-primary btn-sm" onclick="doScan()" style="float:right;">
                    Scannen
                </button>
            </h2>
            <div id="scan-status" style="margin: 10px 0; color: #64748b;"></div>
            <table>
                <thead>
                    <tr><th>SSID</th><th>BSSID</th><th>Signaal</th><th>Freq</th><th>Beveiliging</th><th></th></tr>
                </thead>
                <tbody id="network-list"><tr><td colspan="6">Klik op Scannen...</td></tr></tbody>
            </table>
        </div>
        <div class="card" style="margin-top: 20px;">
            <h2>Handmatig Verbinden</h2>
            <div class="form-group">
                <label>SSID</label>
                <input type="text" id="connect-ssid" placeholder="Netwerknaam">
            </div>
            <div class="form-group">
                <label>Wachtwoord</label>
                <input type="password" id="connect-pass" placeholder="Wachtwoord (leeg voor open)">
            </div>
            <div class="actions">
                <button class="btn btn-success" onclick="doConnect()">Verbinden</button>
                <button class="btn btn-danger" onclick="doDisconnect()">Verbreken</button>
            </div>
        </div>
    </div>

    <!-- Settings Tab -->
    <div id="tab-settings" class="tab-content">
        <div class="grid">
            <div class="card">
                <h2>Interface Instellingen</h2>
                <div class="form-group">
                    <label>MTU</label>
                    <input type="number" id="set-mtu" value="1500" min="576" max="9000">
                </div>
                <div class="form-group">
                    <label>TX Power (dBm)</label>
                    <input type="number" id="set-txpower" value="20" min="0" max="30">
                </div>
                <div class="form-group">
                    <label>Power Save</label>
                    <select id="set-powersave">
                        <option value="0">Uit</option>
                        <option value="1">Aan</option>
                    </select>
                </div>
                <div class="actions">
                    <button class="btn btn-primary" onclick="applySettings()">Toepassen</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Tests Tab -->
    <div id="tab-tests" class="tab-content">
        <div class="card">
            <h2>Driver Test Suite
                <button class="btn btn-primary btn-sm" onclick="runTests()" style="float:right;" id="btn-run-tests">
                    Tests Draaien
                </button>
            </h2>
            <div id="test-summary" style="margin: 16px 0; color: #94a3b8;"></div>
            <div id="test-output">Klik op "Tests Draaien" om de testsuite te starten...</div>
        </div>
    </div>
</div>

<div id="toast" class="toast" style="opacity: 0;"></div>

<script>
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
    document.querySelectorAll('.tab').forEach((t, i) => {
        t.classList.toggle('active', t.textContent.toLowerCase().includes(
            name === 'overview' ? 'overzicht' : name === 'networks' ? 'netwerk' :
            name === 'settings' ? 'instelling' : 'test'));
    });
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
}

let prevStats = null;

async function refreshStatus() {
    try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const badge = document.getElementById('status-badge');

        if (!d.driver_loaded) {
            badge.textContent = 'Driver niet geladen';
            badge.className = 'status-badge badge-err';
            return;
        }

        badge.textContent = d.operstate === 'up' || d.operstate === 'dormant'
            ? 'Verbonden' : 'Niet verbonden';
        badge.className = 'status-badge ' + (d.connection.ssid ? 'badge-ok' : 'badge-err');

        // Adapter info
        document.getElementById('adapter-info').innerHTML = `
            <div class="info-row"><span class="info-label">Interface</span><span class="info-value">${d.interface}</span></div>
            <div class="info-row"><span class="info-label">MAC Adres</span><span class="info-value">${d.mac_address}</span></div>
            <div class="info-row"><span class="info-label">IP Adres</span><span class="info-value">${d.ip_address || 'Geen'}</span></div>
            <div class="info-row"><span class="info-label">Status</span><span class="info-value">${d.operstate}</span></div>
            <div class="info-row"><span class="info-label">MTU</span><span class="info-value">${d.mtu}</span></div>
            <div class="info-row"><span class="info-label">USB Snelheid</span><span class="info-value">${d.usb_speed_mbps} Mbps</span></div>
            <div class="info-row"><span class="info-label">USB Apparaat</span><span class="info-value">${d.usb_vendor}:${d.usb_product} (${d.usb_product_name})</span></div>
        `;

        // Connection
        const conn = d.connection;
        let connHtml = '';
        if (conn.ssid) {
            const pct = signalPercent(conn.signal_dbm);
            const col = signalColor(conn.signal_dbm);
            connHtml = `
                <div class="info-row"><span class="info-label">SSID</span><span class="info-value">${conn.ssid}</span></div>
                <div class="info-row"><span class="info-label">Signaal</span><span class="info-value">${conn.signal_dbm} dBm</span></div>
                <div class="signal-bar"><div class="signal-fill" style="width:${pct}%;background:${col};"></div></div>
                <div class="info-row"><span class="info-label">Frequentie</span><span class="info-value">${conn.frequency_mhz} MHz</span></div>
                <div class="info-row"><span class="info-label">TX Bitrate</span><span class="info-value">${conn.tx_bitrate || 'N/A'}</span></div>
            `;
        } else {
            connHtml = '<div style="color:#64748b;padding:20px;text-align:center;">Niet verbonden met een netwerk</div>';
        }
        document.getElementById('connection-info').innerHTML = connHtml;

        // Stats
        const s = d.statistics;
        document.getElementById('stats-info').innerHTML = `
            <div class="stat-box"><div class="stat-value">${formatBytes(s.tx_bytes)}</div><div class="stat-label">TX Data</div></div>
            <div class="stat-box"><div class="stat-value">${formatBytes(s.rx_bytes)}</div><div class="stat-label">RX Data</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_packets.toLocaleString()}</div><div class="stat-label">TX Pakketten</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_packets.toLocaleString()}</div><div class="stat-label">RX Pakketten</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_errors}</div><div class="stat-label">TX Fouten</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_errors}</div><div class="stat-label">RX Fouten</div></div>
            <div class="stat-box"><div class="stat-value">${s.tx_dropped}</div><div class="stat-label">TX Dropped</div></div>
            <div class="stat-box"><div class="stat-value">${s.rx_dropped}</div><div class="stat-label">RX Dropped</div></div>
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
            <div class="info-row"><span class="info-label">Module</span><span class="info-value">${d.module_name}</span></div>
            <div class="info-row"><span class="info-label">Driver</span><span class="info-value">${d.driver_name}</span></div>
            <div class="info-row"><span class="info-label">Kernel</span><span class="info-value">${d.kernel_version}</span></div>
            <div class="info-row"><span class="info-label">Srcversion</span><span class="info-value" style="font-size:0.75rem;">${d.srcversion}</span></div>
            <div class="info-row"><span class="info-label">Versie</span><span class="info-value">${d.modinfo?.version || 'N/A'}</span></div>
        `;
    } catch(e) {}
}

async function doScan() {
    document.getElementById('scan-status').innerHTML = '<span class="spinner"></span> Scannen...';
    document.getElementById('network-list').innerHTML = '';
    try {
        const r = await fetch('/api/scan');
        const d = await r.json();
        if (d.error) {
            document.getElementById('scan-status').textContent = 'Fout: ' + d.error;
            return;
        }
        document.getElementById('scan-status').textContent = d.count + ' netwerken gevonden';
        let html = '';
        for (const n of d.networks) {
            const pct = signalPercent(n.signal);
            const col = signalColor(n.signal);
            html += `<tr>
                <td><strong>${n.ssid || '(Verborgen)'}</strong></td>
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
                <td><button class="btn btn-success btn-sm" onclick="quickConnect('${n.ssid.replace(/'/g,"\\\\'")}')">Verbind</button></td>
            </tr>`;
        }
        document.getElementById('network-list').innerHTML = html || '<tr><td colspan="6">Geen netwerken gevonden</td></tr>';
    } catch(e) {
        document.getElementById('scan-status').textContent = 'Fout bij scannen';
    }
}

function quickConnect(ssid) {
    document.getElementById('connect-ssid').value = ssid;
    document.getElementById('connect-pass').focus();
}

async function doConnect() {
    const ssid = document.getElementById('connect-ssid').value;
    const pass = document.getElementById('connect-pass').value;
    if (!ssid) { showToast('Voer een SSID in', false); return; }

    try {
        const r = await fetch('/api/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ssid, password: pass})
        });
        const d = await r.json();
        if (d.success) {
            showToast('Verbonden met ' + ssid, true);
            refreshStatus();
        } else {
            showToast(d.error || d.warning || 'Verbinden mislukt', false);
        }
    } catch(e) {
        showToast('Fout bij verbinden', false);
    }
}

async function doDisconnect() {
    try {
        await fetch('/api/disconnect', {method: 'POST'});
        showToast('Verbinding verbroken', true);
        refreshStatus();
    } catch(e) {
        showToast('Fout bij verbreken', false);
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
        showToast('Instellingen toegepast', true);
        refreshStatus();
    } catch(e) {
        showToast('Fout bij toepassen', false);
    }
}

async function runTests() {
    const btn = document.getElementById('btn-run-tests');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Bezig...';
    document.getElementById('test-output').textContent = 'Tests worden uitgevoerd...';
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
        document.getElementById('test-output').innerHTML = html || d.stderr || 'Geen output';

        if (d.report) {
            const rp = d.report;
            const color = rp.failed === 0 && rp.errors === 0 ? '#6ee7b7' : '#fca5a5';
            document.getElementById('test-summary').innerHTML =
                `<span style="color:${color};font-size:1.1rem;font-weight:600;">` +
                `${rp.passed}/${rp.total} geslaagd</span> | ` +
                `${rp.failed} gefaald | ${rp.errors} fouten | ${rp.skipped} overgeslagen`;
        }
    } catch(e) {
        document.getElementById('test-output').textContent = 'Fout bij uitvoeren tests';
    }

    btn.disabled = false;
    btn.textContent = 'Tests Draaien';
}

// Initial load and auto-refresh
refreshStatus();
refreshDriverInfo();
setInterval(refreshStatus, 5000);
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
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("WARNING: Dashboard should run as root for full functionality")

    print(f"Starting RTL8852AU WiFi Dashboard on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)
