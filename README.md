# 🌐 NetMon — Network Monitoring Application

Real-time network monitoring with SNMP auto-discovery, interactive floor plan alerting, zone management, and a live dashboard.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **SNMP Auto-Polling** | Automatically polls all SNMP-enabled devices at a configurable interval |
| **Network Discovery** | Scans a CIDR range and discovers SNMP-responsive devices |
| **Interactive Floor Plan** | Drag devices onto a custom background image with real-time status glow |
| **Visual Alerting** | Devices pulse red when down, glow yellow on warnings |
| **Zone Management** | Group devices by area/VLAN/floor, color-coded on the floor plan |
| **UniFi Integration** | One-click sync of devices from a UniFi controller |
| **Alert Log** | Timestamped alert history with severity, acknowledgement, and filtering |
| **Access Log** | Full audit trail of who accessed the dashboard and what actions ran |
| **Real-time Dashboard** | WebSocket-powered live stats, device table, and alert feed |
| **Bandwidth Reports** | Monthly reports on backbone & uplink throughput with AI anomaly filtering and PDF export |
| **Per-Device Muting** | Mute/unmute alerts from individual devices with a single click to prevent alert spam |
| **Double-Check Offline** | Two-step offline validation (SNMP re-poll + ping) to ensure high-accuracy alerts |

---

## 📦 Requirements

- Python **3.9+**
- Linux (Ubuntu 20.04+, Debian 11+, CentOS 8+), macOS 12+, or Windows (manual)
- Network access to SNMP-enabled devices (UDP port 161)
- (Optional) UniFi controller for automatic device import

---

## 🚀 Quick Install (Linux / macOS)

```bash
# 1. Clone or extract the NetMon package
git clone https://github.com/yourorg/netmon.git
cd netmon

# 2. Run the install script (Linux: requires sudo)
sudo bash install.sh

# 3. Open the dashboard
http://<server-ip>:5000
```

The installer will:
- Install system dependencies
- Create a Python virtual environment
- Install all Python packages
- Initialise the SQLite database
- Create a systemd service (Linux) that auto-starts on boot
- Open the firewall port

---

## 🪟 Windows Install (Manual)

```powershell
# 1. Install Python 3.9+ from https://python.org

# 2. Open PowerShell in the netmon directory
cd C:\netmon

# 3. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt

# 5. Start the app
python app.py

# 6. Open http://localhost:5000
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT`   | `5000`  | Web server port |
| `HOST`   | `0.0.0.0` | Bind address |
| `DB_PATH`| `netmon.db` | SQLite database path |
| `SECRET_KEY` | (random) | Flask session key |

### In-app Settings (Settings page)

- **Poll Interval**: How often SNMP devices are queried (default 30s)
- **Default Community**: SNMP community string (default `public`)
- **UniFi Credentials**: Host, port, username, password, site
- **Alert Rules**: Toggle alerts on device down/recovery

---

## 📡 SNMP Setup

### On Cisco IOS / IOS-XE

```
snmp-server community public RO
snmp-server location "Server Room"
snmp-server contact "admin@company.com"
```

### On MikroTik RouterOS

```
/snmp set enabled=yes contact="admin" location="MDF"
/snmp community set name=public
```

### On Linux (net-snmp)

```bash
sudo apt install snmpd
# Edit /etc/snmp/snmpd.conf:
#   rocommunity public 192.168.0.0/16
sudo systemctl restart snmpd
```

### On UniFi Devices

Enable SNMP in Settings → System → SNMP.

---

## 🗺️ Using the Floor Plan

1. Go to **Floor Plan** → click **Background** → upload a PNG/JPG/SVG floor plan image
2. Click **Edit Mode**
3. Drag devices from the right panel to their physical locations on the map
4. Click **Save** — positions are stored persistently
5. Return to **View Mode** — devices will pulse/glow based on live status

---

## 🔍 Network Discovery

1. Go to **Devices** → **Network Scan**
2. Enter your network CIDR (e.g. `192.168.1.0/24`)
3. Enter the SNMP community string (e.g. `public`)
4. Click **Start Scan**
5. Discovered devices are automatically added to the device list

---

## ☁️ UniFi Sync

1. Go to **Settings** → enter UniFi controller host/credentials
2. Or go to **Devices** → **Sync UniFi** and enter credentials inline
3. Click **Sync Now** — all UniFi devices are imported with correct types and MAC addresses

---

## 🗂️ Zone Management

1. Go to **Settings** → **Zone Management** → **Add Zone**
2. Name the zone (e.g. "Server Room", "Office Floor 1", "DMZ")
3. Assign a color for visual identification on the floor plan
4. Assign devices to zones via **Devices** → Edit → Zone

---

## 📊 SNMP OIDs Polled

| OID | Description |
|-----|-------------|
| `1.3.6.1.2.1.1.1.0` | sysDescr — system description |
| `1.3.6.1.2.1.1.5.0` | sysName — hostname |
| `1.3.6.1.2.1.1.3.0` | sysUpTime — uptime |
| `1.3.6.1.2.1.1.6.0` | sysLocation — physical location |
| `1.3.6.1.2.1.2.2.1.8.*` | ifOperStatus — interface state |
| `1.3.6.1.2.1.2.2.1.2.*` | ifDescr — interface names |

---

## 🛠️ Service Management (Linux)

```bash
# Start
sudo systemctl start netmon

# Stop
sudo systemctl stop netmon

# Restart
sudo systemctl restart netmon

# Check status
sudo systemctl status netmon

# View logs
sudo journalctl -u netmon -f

# View last 100 lines
sudo journalctl -u netmon -n 100
```

---

## 📁 File Structure

```
netmon/
├── app.py            ← Flask app + SocketIO + API routes
├── database.py       ← SQLite database manager
├── snmp_worker.py    ← SNMP polling + network discovery
├── unifi_client.py   ← UniFi controller API client
├── requirements.txt  ← Python dependencies
├── install.sh        ← Installation script
├── start.sh          ← Start script (created by installer)
├── netmon.db         ← SQLite database (auto-created)
├── templates/
│   ├── base.html     ← Sidebar layout
│   ├── dashboard.html← Main dashboard
│   ├── floorplan.html← Interactive floor plan
│   ├── devices.html  ← Device management
│   ├── logs.html     ← Alert + access logs
│   └── settings.html ← Configuration
└── static/
    ├── css/style.css ← Dark theme CSS
    ├── js/main.js    ← Shared JS + Socket.IO
    └── img/          ← Floor plan uploads
```

---

## 🔒 Security Notes

- The app binds to `0.0.0.0` by default — restrict with `HOST=127.0.0.1` behind a reverse proxy
- No built-in authentication — place behind nginx/Caddy with Basic Auth or OAuth for production
- SNMP v1/v2c use cleartext community strings — restrict SNMP access via ACL on devices

### Nginx reverse proxy example

```nginx
server {
    listen 80;
    server_name netmon.company.internal;
    auth_basic "NetMon";
    auth_basic_user_file /etc/nginx/.htpasswd;
    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_http_version 1.1;
    }
}
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| SNMP scan finds nothing | Check firewall allows UDP 161 from NetMon server; verify community string |
| Device always "Unknown" | SNMP not enabled on device, or wrong community string |
| UniFi sync fails | Verify host, port (8443), credentials; check SSL — the app skips cert verification |
| Floor plan image not showing | Upload PNG/JPG under 10MB via the Background button |
| High CPU | Increase poll interval in Settings |
| Port 5000 in use | Set `PORT=5001 ./start.sh` |

---

## 📝 System Prompt for AI-assisted Development

```
You are building a network monitoring application called NetMon with the following architecture:

Backend: Python 3.9+ with Flask + Flask-SocketIO (threading mode), APScheduler
Database: SQLite (via custom Database class in database.py)
SNMP: pysnmp library, polling sysDescr/sysName/sysUpTime/ifOperStatus
Real-time: Socket.IO WebSockets for device status updates and alert notifications
Frontend: Bootstrap 5 dark theme, vanilla JS, HTML5 Canvas for floor plan

Core entities: Device (id, name, ip, mac, type, zone_id, snmp_enabled, status, pos_x, pos_y, icon)
               Zone (id, name, color, description)
               Alert (id, device_id, severity, message, acknowledged)
               AccessLog (id, source, message, type)
               Floorplan (id, background_url, canvas_data)

Socket events emitted by server: init_data, device_status_update, new_alert, stats_update,
  scan_progress, scan_complete, device_found, unifi_sync_complete

API endpoints: GET/POST /api/devices, PUT/DELETE /api/devices/<id>,
  GET/POST /api/zones, GET /api/alerts, POST /api/alerts/<id>/ack,
  GET /api/floorplan, POST /api/floorplan, POST /api/scan, GET /api/stats,
  GET/POST /api/settings, POST /api/unifi/sync

Frontend conventions: All status colors via CSS vars (--green, --red, --yellow, --accent=#00d4ff)
  statusBadge(), iconClass(), relTime(), esc(), showToast() are global helpers in main.js
  Page handlers are registered as window.onInitData, window.onDeviceStatusUpdate, etc.
```

---

## 📄 License

MIT License — free for personal and commercial use.
