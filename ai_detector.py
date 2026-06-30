import json
import urllib.request
import threading
from datetime import datetime

def analyze_alert(db, socketio, alert_id):
    # Run analysis in a background thread to prevent blocking Flask's main thread
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
    
    # 1. Run local heuristic rules
    if device:
        # Rule A: SNMP vs Ping check
        # If the alert is an offline alert, but the device responds to ping (last_seen within 2 minutes),
        # then the device is physically up, only SNMP polling is failing. Mark as false alert.
        if "offline" in alert['message'].lower() or "unreachable" in alert['message'].lower():
            last_seen_dt = None
            if device.get('last_seen'):
                try:
                    last_seen_dt = datetime.fromisoformat(device['last_seen'])
                except:
                    pass
            
            if last_seen_dt:
                diff_seconds = (datetime.now() - last_seen_dt).total_seconds()
                if diff_seconds < 120 and device.get('snmp_enabled'):
                    is_false = 1
                    explanation = "False Warning: Perangkat aktif via Ping, hanya query SNMP yang timeout/unreachable."

    # 2. Try Google Gemini API if key is configured
    settings = db.get_settings()
    api_key = settings.get('gemini_api_key', '')
    
    if api_key and device:
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
                f"Konteks Sekitar (Zona yang Sama):\n"
                f"{json.dumps(other_devs, indent=2)}\n\n"
                f"Tentukan apakah alert ini adalah False Warning (misal: perangkat sebenarnya hidup karena merespon ping tapi SNMP timeout, atau hanya flapping sementara). "
                f"Kembalikan respon JSON dalam format persis seperti ini: "
                f'{{"is_false_alarm": 0 atau 1, "explanation": "Penjelasan singkat maks 2 kalimat dalam bahasa Indonesia"}}\n'
                f"PENTING: Jangan sertakan markdown wrapper ```json atau teks lain, kembalikan hanya string JSON mentah."
            )
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json"
                }
            }
            
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                text_resp = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
                ai_res = json.loads(text_resp)
                
                is_false = int(ai_res.get('is_false_alarm', is_false))
                explanation = ai_res.get('explanation', explanation)
        except Exception as e:
            print(f"[AI Detector] Gemini API call failed, fallback to local heuristics: {e}")
            
    # 3. Update database
    with db.conn() as c:
        c.execute('UPDATE alerts SET is_false_alarm = ?, ai_analysis = ? WHERE id = ?',
                  (is_false, explanation, alert_id))
        
    # 4. Broadcast live update to UI via Socket.IO
    if socketio:
        socketio.emit('alert_update', {
            'id': alert_id,
            'is_false_alarm': is_false,
            'ai_analysis': explanation
        })
