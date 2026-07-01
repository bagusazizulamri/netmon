import json
import urllib.request
import threading
import subprocess
import platform
from datetime import datetime

def _ping_device(ip):
    if not ip:
        return False
    is_win = platform.system().lower() == 'windows'
    param = '-n' if is_win else '-c'
    timeout_param = '-w' if is_win else '-W'
    timeout_val = '1000' if is_win else '1'
    cmd = ['ping', param, '1', timeout_param, timeout_val, ip]
    try:
        startupinfo = None
        if is_win:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        res = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            startupinfo=startupinfo, 
            timeout=1.5
        )
        return res.returncode == 0
    except Exception:
        return False

def analyze_alert(db, socketio, alert_id):
    # Run analysis in a background thread to prevent blocking Flask
    def _run():
        try:
            _analyze(db, socketio, alert_id)
        except Exception as e:
            print(f"[AI Detector] Analysis failed for alert {alert_id}: {e}")
            
    threading.Thread(target=_run, daemon=True).start()

def _analyze(db, socketio, alert_id):
    with db.conn() as c:
        alert = c.execute('SELECT * FROM alerts WHERE id = ?', (alert_id,)).fetchone()
        if not alert:
            return
        alert = dict(alert)
        device = c.execute('SELECT * FROM devices WHERE id = ?', (alert['device_id'],)).fetchone()
        if device:
            device = dict(device)
            
    is_false = 0
    explanation = "Valid Alert"
    
    if not device:
        return

    # Proactive Live Ping Verification
    currently_pingable = _ping_device(device.get('ip'))

    # Check for concurrent alerts in the last 15 seconds (detects WSL socket collisions)
    concurrent_alerts = 0
    with db.conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM alerts WHERE created_at >= datetime('now', '-15 seconds') AND id != ?", 
            (alert_id,)
        ).fetchone()
        if row:
            concurrent_alerts = row[0]

    # Check alert flapping history for this device in the last 15 minutes
    alert_history_count = 0
    with db.conn() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM alerts WHERE device_id = ? AND created_at >= datetime('now', '-15 minutes') AND id != ?", 
            (device['id'], alert_id)
        ).fetchone()
        if row:
            alert_history_count = row[0]

    # 1. Run advanced local heuristic rules
    alert_msg_lower = alert['message'].lower()
    is_offline_alert = "offline" in alert_msg_lower or "unreachable" in alert_msg_lower or "down" in alert_msg_lower

    if is_offline_alert:
        # Rule A: Device is responsive via ping right now
        if currently_pingable:
            is_false = 1
            if "snmp" in alert_msg_lower:
                explanation = "False Warning: Perangkat aktif via Ping, query SNMP mengalami timeout (kemungkinan beban CPU atau WSL socket drops)."
            else:
                explanation = "False Warning: Perangkat merespon Ping saat dites ulang. Gangguan sebelumnya bersifat sementara (transient packet loss)."
        
        # Rule B: High concurrent failures indicating network interface / WSL congestion
        if not currently_pingable and concurrent_alerts >= 2:
            is_false = 1
            explanation = f"False Warning: Potensi kendala WSL network congestion ({concurrent_alerts} perangkat drop serentak). Perangkat mungkin tidak benar-benar mati."

        # Rule C: Flapping detection
        if alert_history_count >= 2:
            is_false = 1
            explanation = f"False Warning: Terdeteksi Flapping ({alert_history_count} kali alert dalam 15 menit). Konektivitas tidak stabil/jitter."

    # 2. Try Groq API if key is configured
    settings = db.get_settings()
    api_key = settings.get('groq_api_key', '')
    
    if api_key:
        try:
            other_devs = []
            with db.conn() as c:
                rows = c.execute('SELECT name, status, type FROM devices WHERE zone_id = ? AND id != ?', 
                                 (device['zone_id'], device['id'])).fetchall()
                other_devs = [dict(r) for r in rows]
                
            prompt = (
                f"Analisa apakah alert jaringan berikut merupakan peringatan palsu (false warning/alarm).\n"
                f"Detail Perangkat:\n"
                f"- Nama: {device.get('name')}\n"
                f"- Tipe: {device.get('type')}\n"
                f"- IP: {device.get('ip')}\n"
                f"- SNMP Aktif: {'Ya' if device.get('snmp_enabled') else 'Tidak'}\n"
                f"- Status Terakhir: {device.get('status')}\n"
                f"- Uptime: {device.get('uptime')}\n"
                f"Detail Alert:\n"
                f"- Pesan: {alert['message']}\n"
                f"Telemetri Detektor Tambahan:\n"
                f"- Perangkat Merespon Ping Saat Ini: {'Ya' if currently_pingable else 'Tidak'}\n"
                f"- Jumlah Alert Lain dalam 15 Detik Terakhir: {concurrent_alerts} (Indikasi WSL/soket overload jika > 0)\n"
                f"- Jumlah Alert Perangkat Ini dalam 15 Menit Terakhir: {alert_history_count} (Indikasi flapping jika >= 2)\n"
                f"Konteks Sekitar (Zona yang Sama):\n"
                f"{json.dumps(other_devs, indent=2)}\n\n"
                f"Tentukan apakah alert ini adalah False Warning. Kembalikan respon JSON dalam format persis seperti ini: "
                f'{{"is_false_alarm": 0 atau 1, "explanation": "Penjelasan singkat maks 2 kalimat dalam bahasa Indonesia"}}'
            )
            
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a network analysis assistant. Respond ONLY with a raw JSON object containing \"is_false_alarm\" (0 or 1) and \"explanation\" (string in Indonesian, max 2 sentences)."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.2
            }
            
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                text_resp = res_data['choices'][0]['message']['content'].strip()
                ai_res = json.loads(text_resp)
                
                is_false = int(ai_res.get('is_false_alarm', is_false))
                explanation = ai_res.get('explanation', explanation)
        except Exception as e:
            print(f"[AI Detector] Groq API call failed, fallback to advanced local heuristics: {e}")
            
    # 3. Update database
    with db.conn() as c:
        c.execute('UPDATE alerts SET is_false_alarm = ?, ai_analysis = ? WHERE id = ?',
                  (is_false, explanation, alert_id))
        
        # If it was marked as a false offline alarm (because the device is currently pingable),
        # set the device status back to 'up' in the database!
        if is_false == 1 and is_offline_alert:
            c.execute("UPDATE devices SET status='up', last_seen=? WHERE id=?", 
                      (datetime.now().isoformat(), device['id']))
        
    # 4. Broadcast live update to UI via Socket.IO
    if socketio:
        socketio.emit('alert_update', {
            'id': alert_id,
            'is_false_alarm': is_false,
            'ai_analysis': explanation
        })
        
        if is_false == 1 and is_offline_alert:
            # Emit updated device and stats to refresh the frontend state immediately
            with db.conn() as c:
                updated = c.execute('SELECT * FROM devices WHERE id = ?', (device['id'],)).fetchone()
            if updated:
                socketio.emit('device_status_update', dict(updated))
            socketio.emit('stats_update', db.get_dashboard_stats())
