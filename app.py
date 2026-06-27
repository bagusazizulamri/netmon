#!/usr/bin/env python3
"""
NetMon - Network Monitoring Application
Automatic SNMP capture, floor plan alerting, zone management, real-time dashboard
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from apscheduler.schedulers.background import BackgroundScheduler
import threading
import json
import os
from datetime import datetime
from database import Database
from snmp_worker import SNMPWorker
from unifi_client import UniFiClient

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'netmon-secret-2024-change-me')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)

db = Database()
snmp_worker = SNMPWorker(db, socketio)
scheduler = BackgroundScheduler(daemon=True)

# ============================================================
# PAGE ROUTES
# ============================================================

@app.route('/')
def dashboard():
    db.add_access_log({'source': request.remote_addr, 'message': 'Accessed Dashboard', 'type': 'access'})
    return render_template('dashboard.html')

@app.route('/floorplan')
def floorplan():
    db.add_access_log({'source': request.remote_addr, 'message': 'Accessed Floor Plan', 'type': 'access'})
    return render_template('floorplan.html')

@app.route('/devices')
def devices_page():
    db.add_access_log({'source': request.remote_addr, 'message': 'Accessed Devices', 'type': 'access'})
    return render_template('devices.html')

@app.route('/logs')
def logs_page():
    db.add_access_log({'source': request.remote_addr, 'message': 'Accessed Logs', 'type': 'access'})
    return render_template('logs.html')

@app.route('/settings')
def settings_page():
    db.add_access_log({'source': request.remote_addr, 'message': 'Accessed Settings', 'type': 'access'})
    return render_template('settings.html')

# ============================================================
# API – DEVICES
# ============================================================

@app.route('/api/devices', methods=['GET'])
def get_devices():
    return jsonify(db.get_all_devices())

@app.route('/api/devices', methods=['POST'])
def add_device():
    import sqlite3
    data = request.json
    try:
        device_id = db.add_device(data)
        dev = db.get_device(device_id)
        socketio.emit('device_added', dev)
        return jsonify({'id': device_id, 'status': 'success'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'Alamat IP sudah terdaftar atau terdapat kesalahan integritas data.'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/devices/<int:device_id>', methods=['GET'])
def get_device(device_id):
    return jsonify(db.get_device(device_id) or {})

@app.route('/api/devices/<int:device_id>', methods=['PUT'])
def update_device(device_id):
    import sqlite3
    try:
        db.update_device(device_id, request.json)
        dev = db.get_device(device_id)
        socketio.emit('device_updated', dev)
        return jsonify({'status': 'success'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'Alamat IP sudah terdaftar atau terdapat kesalahan integritas data.'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
def delete_device(device_id):
    db.delete_device(device_id)
    socketio.emit('device_deleted', {'id': device_id})
    return jsonify({'status': 'success'})

@app.route('/api/devices/<int:device_id>/poll', methods=['POST'])
def poll_device_now(device_id):
    device = db.get_device(device_id)
    if device:
        threading.Thread(target=snmp_worker.poll_device, args=(device,), daemon=True).start()
        return jsonify({'status': 'polling'})
    return jsonify({'status': 'error', 'message': 'Device not found'}), 404

@app.route('/api/devices/detect', methods=['POST'])
def detect_device_info():
    import subprocess
    import re
    
    data = request.get_json() or {}
    ip = data.get('ip', '').strip()
    if not ip:
        return jsonify({'status': 'error', 'message': 'IP Address is required'}), 400
        
    snmp_community = data.get('snmp_community', 'public') or 'public'
    snmp_version = data.get('snmp_version', '2c') or '2c'
    snmp_port = int(data.get('snmp_port', 161) or 161)
    
    # 1. Resolve MAC address via ARP
    mac = ""
    try:
        # Send a quick ping to populate ARP cache
        ping_cmd = ["ping", "-n", "1", "-w", "500", ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", "1", ip]
        subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Read ARP output
        if os.name == 'nt':
            res = subprocess.run(["arp", "-a", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
            out = res.stdout
        else:
            res = subprocess.run(["arp", "-n", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
            out = res.stdout
            if (not out or "No ARP" in out) and os.path.exists("/proc/net/arp"):
                with open("/proc/net/arp", "r") as f:
                    out = f.read()
                    
        mac_re = re.compile(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})')
        for line in out.splitlines():
            if ip in line:
                match = mac_re.search(line)
                if match:
                    mac = match.group(0).upper().replace('-', ':')
                    break
    except Exception as e:
        print(f"[Detect] ARP MAC fetch failed: {e}")

    # 2. Try SNMP Query
    if snmp_worker:
        res = snmp_worker._get(ip, snmp_community, [
            '1.3.6.1.2.1.1.1.0', # sysDescr
            '1.3.6.1.2.1.1.2.0', # sysObjectID
            '1.3.6.1.2.1.1.5.0'  # sysName
        ], port=snmp_port, version=snmp_version, timeout=1.5)
        
        if res:
            descr = res.get('1.3.6.1.2.1.1.1.0', '')
            sys_obj_id = str(res.get('1.3.6.1.2.1.1.2.0', '')).lower()
            name = res.get('1.3.6.1.2.1.1.5.0', '').strip() or ip
            
            # Vendor detection
            vendor = 'Unknown'
            if '14988' in sys_obj_id or 'mikrotik' in descr.lower() or 'routeros' in descr.lower():
                vendor = 'MikroTik'
            elif '4881' in sys_obj_id or 'ruijie' in descr.lower() or 'reyee' in descr.lower():
                vendor = 'Ruijie'
            elif '41112' in sys_obj_id or 'ubiquiti' in descr.lower() or 'unifi' in descr.lower():
                vendor = 'Ubiquiti'
            elif '9.1.' in sys_obj_id or '9.9.' in sys_obj_id or '.9.' in sys_obj_id or 'cisco' in descr.lower():
                vendor = 'Cisco'
                
            # Guess Type & Icon
            device_type = snmp_worker._guess_type(descr)
            
            # Guess Model from description
            model = ""
            if descr:
                words = descr.split()
                if vendor == 'MikroTik' and len(words) > 1:
                    model = words[1]
                elif vendor == 'Ruijie' and len(words) > 1:
                    model = words[0]
                else:
                    model = descr.split('\n')[0][:30].strip()
            
            return jsonify({
                'status': 'success',
                'snmp_enabled': True,
                'name': name,
                'mac': mac,
                'vendor': vendor,
                'model': model,
                'type': device_type
            })
            
    # 3. Fallback to Ping to verify if host is reachable
    is_alive = False
    try:
        ping_cmd = ["ping", "-n", "1", "-w", "800", ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", "1", ip]
        res = subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        is_alive = (res.returncode == 0)
    except Exception:
        pass
        
    if is_alive:
        return jsonify({
            'status': 'success',
            'snmp_enabled': False,
            'name': ip,
            'mac': mac,
            'vendor': 'Generic',
            'model': 'Ping Only',
            'type': 'unknown'
        })
        
    return jsonify({'status': 'error', 'message': 'Device is unreachable or offline'}), 404

@app.route('/api/devices/<int:device_id>/realtime_stats', methods=['GET'])
def get_device_realtime_stats(device_id):
    device = db.get_device(device_id)
    if not device:
        return jsonify({'status': 'error', 'message': 'Device not found'}), 404
        
    is_unifi = (device.get('type') == 'unifi') or (device.get('unifi_id') != '') or ('ubiquiti' in str(device.get('vendor')).lower())
    
    if is_unifi:
        try:
            settings = db.get_settings()
            host = settings.get('unifi_host', '')
            username = settings.get('unifi_user', '')
            password = settings.get('unifi_pass', '')
            port = int(settings.get('unifi_port', 8443) or 8443)
            site = settings.get('unifi_site', 'default') or 'default'
            
            if host and username and password:
                unifi = UniFiClient(host=host, username=username, password=password, port=port, site=site)
                details = unifi.get_device_details(device.get('ip') or device.get('mac') or device.get('unifi_id'))
                if details:
                    return jsonify({
                        'status': 'success',
                        'source': 'unifi',
                        'sys_name': details.get('name'),
                        'description': f"UniFi {details.get('model')} Device",
                        'uptime': details.get('uptime'),
                        'cpu_usage': details.get('cpu_usage'),
                        'memory_usage': details.get('memory_usage'),
                        'temperature': details.get('temperature'),
                        'interfaces': details.get('interfaces', [])
                    })
        except Exception as e:
            print(f"[Realtime] UniFi fetch failed: {e}")
            
    if device.get('snmp_enabled'):
        try:
            stats = snmp_worker.get_detailed_stats(device)
            return jsonify({
                'status': 'success',
                'source': 'snmp',
                'sys_name': stats.get('sys_name') or device.get('sys_name') or device.get('name'),
                'description': stats.get('description') or device.get('description'),
                'uptime': stats.get('uptime') or device.get('uptime'),
                'cpu_usage': stats.get('cpu_usage') if stats.get('cpu_usage') is not None else device.get('cpu_usage'),
                'memory_usage': stats.get('memory_usage') if stats.get('memory_usage') is not None else device.get('memory_usage'),
                'temperature': stats.get('temperature') if stats.get('temperature') is not None else device.get('temperature'),
                'interfaces': stats.get('interfaces', [])
            })
        except Exception as e:
            return jsonify({'status': 'error', 'message': f"SNMP Error: {str(e)}"}), 500
            
    return jsonify({
        'status': 'success',
        'source': 'ping',
        'sys_name': device.get('name'),
        'description': device.get('description') or 'No SNMP enabled',
        'uptime': device.get('uptime'),
        'cpu_usage': device.get('cpu_usage'),
        'memory_usage': device.get('memory_usage'),
        'temperature': device.get('temperature'),
        'interfaces': []
    })

# ============================================================
# API – ZONES
# ============================================================

@app.route('/api/zones', methods=['GET'])
def get_zones():
    return jsonify(db.get_all_zones())

@app.route('/api/zones', methods=['POST'])
def add_zone():
    zone_id = db.add_zone(request.json)
    return jsonify({'id': zone_id, 'status': 'success'})

@app.route('/api/zones/<int:zone_id>', methods=['PUT'])
def update_zone(zone_id):
    db.update_zone(zone_id, request.json)
    return jsonify({'status': 'success'})

@app.route('/api/zones/<int:zone_id>', methods=['DELETE'])
def delete_zone(zone_id):
    db.delete_zone(zone_id)
    return jsonify({'status': 'success'})

# ============================================================
# API – ALERTS & LOGS
# ============================================================

@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))
    severity = request.args.get('severity')
    return jsonify(db.get_alerts(limit=limit, offset=offset, severity=severity))

@app.route('/api/alerts/<int:alert_id>/ack', methods=['POST'])
def ack_alert(alert_id):
    user = request.json.get('user', 'admin') if request.json else 'admin'
    db.acknowledge_alert(alert_id, user)
    socketio.emit('alert_acked', {'id': alert_id})
    return jsonify({'status': 'success'})

@app.route('/api/alerts/ack_all', methods=['POST'])
def ack_all_alerts():
    db.acknowledge_all_alerts()
    socketio.emit('all_alerts_acked', {})
    return jsonify({'status': 'success'})

@app.route('/api/access_logs', methods=['GET'])
def get_access_logs():
    limit = int(request.args.get('limit', 100))
    return jsonify(db.get_access_logs(limit=limit))

# ============================================================
# API – FLOOR PLAN
# ============================================================

@app.route('/api/floorplan', methods=['GET'])
def get_floorplan():
    return jsonify(db.get_floorplan())

@app.route('/api/floorplan', methods=['POST'])
def save_floorplan():
    db.save_floorplan(request.json)
    return jsonify({'status': 'success'})

@app.route('/api/floorplan/upload', methods=['POST'])
def upload_floorplan():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'svg'):
        return jsonify({'error': 'Invalid file type'}), 400
    path = os.path.join('static', 'img', f'floorplan.{ext}')
    f.save(path)
    return jsonify({'status': 'success', 'url': f'/static/img/floorplan.{ext}'})

# ============================================================
# API – NETWORK SCAN
# ============================================================

@app.route('/api/scan', methods=['POST'])
def scan_network():
    data = request.json or {}
    network = data.get('network', '192.168.1.0/24')
    community = data.get('community', 'public')
    version = data.get('version', '2c')
    zone_id = int(data.get('zone_id', 1))
    if snmp_worker.get_scan_status()['running']:
        return jsonify({'status': 'already_running'}), 409
    threading.Thread(target=snmp_worker.scan_network, args=(network, community, version, zone_id), daemon=True).start()
    db.add_access_log({'source': request.remote_addr, 'message': f'Network scan started: {network}', 'type': 'scan'})
    return jsonify({'status': 'started', 'network': network})

@app.route('/api/scan/status', methods=['GET'])
def scan_status():
    return jsonify(snmp_worker.get_scan_status())

@app.route('/api/scan/stop', methods=['POST'])
def scan_stop():
    snmp_worker.stop_scan()
    return jsonify({'status': 'stopped'})

# ============================================================
# API – UNIFI
# ============================================================

@app.route('/api/unifi/sync', methods=['POST'])
def sync_unifi():
    data = request.json or {}
    try:
        settings = db.get_settings()
        host = data.get('host') or settings.get('unifi_host', '')
        username = data.get('username') or settings.get('unifi_user', '')
        password = data.get('password') or settings.get('unifi_pass', '')
        port = int(data.get('port') or settings.get('unifi_port', 8443))
        site = data.get('site') or settings.get('unifi_site', 'default')

        if not host or not username or not password:
            return jsonify({'status': 'error', 'message': 'UniFi credentials not configured'}), 400

        unifi = UniFiClient(host=host, username=username, password=password, port=port, site=site)
        devices = unifi.get_devices()
        clients = unifi.get_clients()
        zone_id = int(data.get('zone_id', 1))
        added = sum(1 for d in devices if db.add_or_update_unifi_device(d, zone_id=zone_id))

        db.add_access_log({
            'source': request.remote_addr,
            'message': f'UniFi sync: {len(devices)} devices, {len(clients)} clients synced',
            'type': 'sync'
        })
        socketio.emit('unifi_sync_complete', {'devices': len(devices), 'clients': len(clients), 'added': added})
        return jsonify({'status': 'success', 'devices': len(devices), 'clients': len(clients), 'added': added})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============================================================
# API – SETTINGS & STATS
# ============================================================

@app.route('/api/settings', methods=['GET'])
def get_settings():
    s = db.get_settings()
    # Never return password in plaintext
    if 'unifi_pass' in s:
        s['unifi_pass'] = '***' if s['unifi_pass'] else ''
    return jsonify(s)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json or {}
    # Don't save masked password
    if data.get('unifi_pass') == '***':
        data.pop('unifi_pass')
    db.save_settings(data)
    if 'poll_interval' in data:
        try:
            scheduler.reschedule_job('snmp_poll', trigger='interval', seconds=max(10, int(data['poll_interval'])))
        except Exception:
            pass
    return jsonify({'status': 'success'})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify(db.get_dashboard_stats())

# ============================================================
# WEBSOCKET EVENTS
# ============================================================

@socketio.on('connect')
def handle_connect():
    emit('init_data', {
        'devices': db.get_all_devices(),
        'zones': db.get_all_zones(),
        'stats': db.get_dashboard_stats(),
        'alerts': db.get_alerts(limit=25),
        'floorplan': db.get_floorplan()
    })

# ============================================================
# BACKGROUND POLLING
# ============================================================

def background_poll():
    # 1. Sync UniFi telemetries if configured
    try:
        settings = db.get_settings()
        host = settings.get('unifi_host', '')
        username = settings.get('unifi_user', '')
        password = settings.get('unifi_pass', '')
        port = int(settings.get('unifi_port', 8443) or 8443)
        site = settings.get('unifi_site', 'default') or 'default'
        
        if host and username and password:
            from unifi_client import UniFiClient
            unifi = UniFiClient(host=host, username=username, password=password, port=port, site=site)
            unifi_devs = unifi.get_devices()
            for ud in unifi_devs:
                db.add_or_update_unifi_device(ud)
    except Exception as e:
        print(f"[Poll] UniFi auto-poll failed: {e}")

    # 2. Poll SNMP/Ping devices
    devices = db.get_all_devices()
    for device in devices:
        try:
            snmp_worker.poll_device(device)
        except Exception as e:
            print(f"[Poll] Error polling {device.get('ip')}: {e}")

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    settings = db.get_settings()
    poll_interval = max(10, int(settings.get('poll_interval', 30)))
    scheduler.add_job(background_poll, 'interval', seconds=poll_interval, id='snmp_poll', max_instances=1)
    scheduler.start()
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    print(f"\n{'='*50}")
    print(f"  NetMon starting → http://{host}:{port}")
    print(f"  SNMP poll every {poll_interval}s")
    print(f"{'='*50}\n")
    socketio.run(app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
