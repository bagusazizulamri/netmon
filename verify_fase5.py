import os
os.environ['DB_PATH'] = '/tmp/verify_fase5.db'
from database import Database
from datetime import datetime, timedelta

db = Database()

print("### TEST 1: Real peak tidak boleh digelembungkan (multi-router, view 1 jam) ###")
didX = db.add_device({'name':'r-A','ip':'10.0.5.1','type':'router','uplink_speed_mbps': 10000})
didY = db.add_device({'name':'r-B','ip':'10.0.5.2','type':'router','uplink_speed_mbps': 10000})
now = datetime.now()
base = (now - timedelta(hours=1, minutes=30)).replace(second=0, microsecond=0)
with db.conn() as c:
    t = base
    while t < now:
        elapsed_min = int((t - base).total_seconds() // 60)
        valA = 500e6 if elapsed_min == 40 else 100e6
        valB = 90e6
        c.execute("INSERT INTO snmp_metrics (device_id, metric_name, metric_value, timestamp) VALUES (?,?,?,?)",
                   (didX, 'wan_in', str(valA), t.strftime('%Y-%m-%d %H:%M:%S')))
        c.execute("INSERT INTO snmp_metrics (device_id, metric_name, metric_value, timestamp) VALUES (?,?,?,?)",
                   (didY, 'wan_in', str(valB), t.strftime('%Y-%m-%d %H:%M:%S')))
        t += timedelta(seconds=30)

points = db.get_backbone_traffic_history(1.0)
peak = max(p['in'] for p in points)
print(f"Real peak seharusnya: 590 Mbps | Hasil aktual: {peak} Mbps")
assert abs(peak - 590.0) < 0.01, f"GAGAL: peak={peak} (kalau masih ~1180, fix belum kepasang/masih SUM lama)"
print(">>> LULUS\n")

print("### TEST 2: View 7 hari tidak boleh kehilangan data terbaru ###")
did7 = db.add_device({'name':'r-7d','ip':'10.0.5.3','type':'router','uplink_speed_mbps': 10000})
with db.conn() as c:
    t = now - timedelta(hours=168)
    while t < now:
        c.execute("INSERT INTO snmp_metrics (device_id, metric_name, metric_value, timestamp) VALUES (?,?,?,?)",
                   (did7, 'wan_in', '100000000', t.strftime('%Y-%m-%d %H:%M:%S')))
        t += timedelta(minutes=15)
points7 = db.get_backbone_traffic_history(168.0)
print(f"Jumlah titik chart 7 hari: {len(points7)} (idealnya mendekati 168)")
print(f"Titik pertama: {points7[0]['t']} | Titik terakhir: {points7[-1]['t']}")
assert len(points7) >= 150, f"GAGAL: cuma {len(points7)} bucket, kemungkinan masih terpotong"
print(">>> LULUS\n")

print("### TEST 3 (REGRESI): view 24 jam masih jalan normal ###")
points24 = db.get_backbone_traffic_history(24.0)
print(f"Jumlah titik chart 24 jam: {len(points24)}")
assert len(points24) > 0
print(">>> LULUS\n")

print("SEMUA TEST LULUS")

# Clean up tmp DB
try:
    os.remove('/tmp/verify_fase5.db')
except:
    pass
