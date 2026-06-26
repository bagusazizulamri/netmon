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
    if snmp_worker.get_scan_status()['running']:
        return jsonify({'status': 'already_running'}), 409
    threading.Thread(target=snmp_worker.scan_network, args=(network, community, version), daemon=True).start()
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
        added = sum(1 for d in devices if db.add_or_update_unifi_device(d))

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
