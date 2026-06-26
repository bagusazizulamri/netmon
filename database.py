#!/usr/bin/env python3
"""
NetMon - Database Manager
SQLite-based persistent storage
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.environ.get('DB_PATH', 'netmon.db')


class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _init_db(self):
        with self.conn() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS devices (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT NOT NULL,
                    ip            TEXT NOT NULL UNIQUE,
                    mac           TEXT DEFAULT '',
                    type          TEXT DEFAULT 'unknown',
                    vendor        TEXT DEFAULT '',
                    model         TEXT DEFAULT '',
                    zone_id       INTEGER DEFAULT 1,
                    snmp_enabled  INTEGER DEFAULT 0,
                    snmp_community TEXT DEFAULT 'public',
                    snmp_version  TEXT DEFAULT '2c',
                    snmp_port     INTEGER DEFAULT 161,
                    status        TEXT DEFAULT 'unknown',
                    last_seen     TEXT,
                    last_polled   TEXT,
                    uptime        TEXT DEFAULT '',
                    description   TEXT DEFAULT '',
                    sys_name      TEXT DEFAULT '',
                    pos_x         REAL DEFAULT 100,
                    pos_y         REAL DEFAULT 100,
                    icon          TEXT DEFAULT 'router',
                    unifi_id      TEXT DEFAULT '',
                    created_at    TEXT DEFAULT (datetime('now')),
                    updated_at    TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS zones (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    color       TEXT DEFAULT '#00d4ff',
                    created_at  TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id    INTEGER,
                    device_name  TEXT DEFAULT '',
                    device_ip    TEXT DEFAULT '',
                    severity     TEXT DEFAULT 'info',
                    message      TEXT NOT NULL,
                    details      TEXT DEFAULT '{}',
                    acknowledged INTEGER DEFAULT 0,
                    ack_by       TEXT DEFAULT '',
                    ack_at       TEXT,
                    created_at   TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS access_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    source     TEXT DEFAULT '',
                    message    TEXT DEFAULT '',
                    type       TEXT DEFAULT 'info',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS floorplans (
                    id             INTEGER PRIMARY KEY,
                    name           TEXT DEFAULT 'Main Floor',
                    background_url TEXT DEFAULT '',
                    canvas_data    TEXT DEFAULT NULL,
                    updated_at     TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS snmp_metrics (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id    INTEGER,
                    metric_name  TEXT,
                    metric_value TEXT,
                    timestamp    TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id);
                CREATE INDEX IF NOT EXISTS idx_access_logs_created ON access_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_metrics_device ON snmp_metrics(device_id, metric_name);
            ''')

            # Default settings
            defaults = {
                'poll_interval': '30',
                'alert_on_down': 'true',
                'alert_on_up': 'true',
                'default_community': 'public',
                'default_snmp_version': '2c',
                'unifi_host': '',
                'unifi_user': '',
                'unifi_pass': '',
                'unifi_port': '8443',
                'unifi_site': 'default',
                'app_name': 'NetMon',
                'alert_retention_days': '30',
                'log_retention_days': '90',
            }
            for k, v in defaults.items():
                c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))

            c.execute('INSERT OR IGNORE INTO zones (id, name, color, description) VALUES (1, "Default Zone", "#00d4ff", "Default network zone")')
            c.execute('INSERT OR IGNORE INTO floorplans (id) VALUES (1)')

    # ============================================================
    # DEVICES
    # ============================================================

    def get_all_devices(self):
        with self.conn() as c:
            rows = c.execute('''
                SELECT d.*, z.name AS zone_name, z.color AS zone_color
                FROM devices d
                LEFT JOIN zones z ON d.zone_id = z.id
                ORDER BY d.name COLLATE NOCASE
            ''').fetchall()
            return [dict(r) for r in rows]

    def get_device(self, device_id):
        with self.conn() as c:
            row = c.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
            return dict(row) if row else None

    def get_device_by_ip(self, ip):
        with self.conn() as c:
            row = c.execute('SELECT * FROM devices WHERE ip = ?', (ip,)).fetchone()
            return dict(row) if row else None

    def get_snmp_enabled_devices(self):
        with self.conn() as c:
            rows = c.execute('SELECT * FROM devices WHERE snmp_enabled = 1').fetchall()
            return [dict(r) for r in rows]

    def add_device(self, data):
        with self.conn() as c:
            cur = c.execute('''
                INSERT INTO devices
                    (name, ip, mac, type, vendor, model, zone_id,
                     snmp_enabled, snmp_community, snmp_version, snmp_port,
                     icon, pos_x, pos_y, description, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                data.get('name') or data.get('ip', 'Unknown'),
                data.get('ip', ''),
                data.get('mac', ''),
                data.get('type', 'unknown'),
                data.get('vendor', ''),
                data.get('model', ''),
                data.get('zone_id', 1),
                1 if data.get('snmp_enabled') else 0,
                data.get('snmp_community', 'public'),
                data.get('snmp_version', '2c'),
                data.get('snmp_port', 161),
                data.get('icon', 'router'),
                data.get('pos_x', 100),
                data.get('pos_y', 100),
                data.get('description', ''),
                data.get('status', 'unknown'),
            ))
            return cur.lastrowid

    def update_device(self, device_id, data):
        allowed = ['name', 'ip', 'mac', 'type', 'vendor', 'model', 'zone_id',
                   'snmp_enabled', 'snmp_community', 'snmp_version', 'snmp_port',
                   'icon', 'pos_x', 'pos_y', 'description', 'status',
                   'last_seen', 'last_polled', 'uptime', 'sys_name']
        fields, values = [], []
        for f in allowed:
            if f in data:
                fields.append(f'{f} = ?')
                values.append(data[f])
        if not fields:
            return
        fields.append('updated_at = ?')
        values.extend([datetime.now().isoformat(), device_id])
        with self.conn() as c:
            c.execute(f'UPDATE devices SET {", ".join(fields)} WHERE id = ?', values)

    def delete_device(self, device_id):
        with self.conn() as c:
            c.execute('DELETE FROM devices WHERE id = ?', (device_id,))

    def get_old_status(self, device_id):
        with self.conn() as c:
            row = c.execute('SELECT status FROM devices WHERE id = ?', (device_id,)).fetchone()
            return row['status'] if row else 'unknown'

    def add_or_update_unifi_device(self, data):
        with self.conn() as c:
            existing = c.execute(
                'SELECT id FROM devices WHERE ip = ? OR (unifi_id != "" AND unifi_id = ?)',
                (data.get('ip', ''), data.get('unifi_id', ''))
            ).fetchone()
            if existing:
                c.execute('''
                    UPDATE devices SET name=?, mac=?, vendor=?, model=?, unifi_id=?, updated_at=?
                    WHERE id=?
                ''', (data.get('name',''), data.get('mac',''), data.get('vendor','Ubiquiti'),
                      data.get('model',''), data.get('unifi_id',''),
                      datetime.now().isoformat(), existing['id']))
                return False
            else:
                c.execute('''
                    INSERT INTO devices (name, ip, mac, type, vendor, model, unifi_id, zone_id, snmp_enabled, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                ''', (data.get('name', data.get('ip','Unknown')), data.get('ip',''),
                      data.get('mac',''), data.get('type','unifi'),
                      data.get('vendor','Ubiquiti'), data.get('model',''),
                      data.get('unifi_id',''), data.get('status','unknown')))
                return True

    # ============================================================
    # ZONES
    # ============================================================

    def get_all_zones(self):
        with self.conn() as c:
            rows = c.execute('''
                SELECT z.*, COUNT(d.id) AS device_count
                FROM zones z
                LEFT JOIN devices d ON z.id = d.zone_id
                GROUP BY z.id ORDER BY z.name COLLATE NOCASE
            ''').fetchall()
            return [dict(r) for r in rows]

    def add_zone(self, data):
        with self.conn() as c:
            cur = c.execute(
                'INSERT INTO zones (name, description, color) VALUES (?, ?, ?)',
                (data.get('name','New Zone'), data.get('description',''), data.get('color','#00d4ff'))
            )
            return cur.lastrowid

    def update_zone(self, zone_id, data):
        with self.conn() as c:
            c.execute('UPDATE zones SET name=?, description=?, color=? WHERE id=?',
                      (data.get('name'), data.get('description',''), data.get('color','#00d4ff'), zone_id))

    def delete_zone(self, zone_id):
        with self.conn() as c:
            c.execute('UPDATE devices SET zone_id=1 WHERE zone_id=?', (zone_id,))
            if zone_id != 1:
                c.execute('DELETE FROM zones WHERE id=?', (zone_id,))

    # ============================================================
    # ALERTS
    # ============================================================

    def get_alerts(self, limit=50, offset=0, severity=None):
        with self.conn() as c:
            if severity:
                rows = c.execute(
                    'SELECT * FROM alerts WHERE severity=? ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (severity, limit, offset)
                ).fetchall()
            else:
                rows = c.execute(
                    'SELECT * FROM alerts ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (limit, offset)
                ).fetchall()
            return [dict(r) for r in rows]

    def add_alert(self, data):
        with self.conn() as c:
            details = data.get('details', {})
            if isinstance(details, dict):
                details = json.dumps(details)
            cur = c.execute('''
                INSERT INTO alerts (device_id, device_name, device_ip, severity, message, details)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (data.get('device_id'), data.get('device_name',''), data.get('device_ip',''),
                  data.get('severity','info'), data.get('message',''), details))
            return cur.lastrowid

    def acknowledge_alert(self, alert_id, user='admin'):
        with self.conn() as c:
            c.execute('UPDATE alerts SET acknowledged=1, ack_by=?, ack_at=? WHERE id=?',
                      (user, datetime.now().isoformat(), alert_id))

    def acknowledge_all_alerts(self):
        with self.conn() as c:
            c.execute("UPDATE alerts SET acknowledged=1, ack_by='admin', ack_at=? WHERE acknowledged=0",
                      (datetime.now().isoformat(),))

    def get_unack_count(self):
        with self.conn() as c:
            return c.execute('SELECT COUNT(*) FROM alerts WHERE acknowledged=0').fetchone()[0]

    # ============================================================
    # ACCESS LOGS
    # ============================================================

    def add_access_log(self, data):
        with self.conn() as c:
            c.execute('INSERT INTO access_logs (source, message, type) VALUES (?, ?, ?)',
                      (data.get('source',''), data.get('message',''), data.get('type','info')))

    def get_access_logs(self, limit=100):
        with self.conn() as c:
            rows = c.execute('SELECT * FROM access_logs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ============================================================
    # FLOOR PLAN
    # ============================================================

    def get_floorplan(self, fp_id=1):
        with self.conn() as c:
            row = c.execute('SELECT * FROM floorplans WHERE id=?', (fp_id,)).fetchone()
            if row:
                result = dict(row)
                if result.get('canvas_data'):
                    try:
                        result['canvas_data'] = json.loads(result['canvas_data'])
                    except Exception:
                        pass
                return result
            return {'id': 1, 'name': 'Main Floor', 'background_url': '', 'canvas_data': None}

    def save_floorplan(self, data, fp_id=1):
        canvas_data = data.get('canvas_data')
        if isinstance(canvas_data, (dict, list)):
            canvas_data = json.dumps(canvas_data)
        with self.conn() as c:
            c.execute('''
                UPDATE floorplans SET name=?, background_url=?, canvas_data=?, updated_at=?
                WHERE id=?
            ''', (data.get('name','Main Floor'), data.get('background_url',''),
                  canvas_data, datetime.now().isoformat(), fp_id))

    # ============================================================
    # SETTINGS
    # ============================================================

    def get_settings(self):
        with self.conn() as c:
            rows = c.execute('SELECT key, value FROM settings').fetchall()
            return {r['key']: r['value'] for r in rows}

    def save_settings(self, data):
        with self.conn() as c:
            for k, v in data.items():
                c.execute('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)',
                          (k, str(v), datetime.now().isoformat()))

    # ============================================================
    # SNMP METRICS
    # ============================================================

    def save_metric(self, device_id, name, value):
        with self.conn() as c:
            c.execute('INSERT INTO snmp_metrics (device_id, metric_name, metric_value) VALUES (?, ?, ?)',
                      (device_id, name, str(value)))

    def get_metrics(self, device_id, name, limit=60):
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM snmp_metrics WHERE device_id=? AND metric_name=? ORDER BY timestamp DESC LIMIT ?',
                (device_id, name, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    # ============================================================
    # DASHBOARD STATS
    # ============================================================

    def get_dashboard_stats(self):
        with self.conn() as c:
            total    = c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
            up       = c.execute("SELECT COUNT(*) FROM devices WHERE status='up'").fetchone()[0]
            down     = c.execute("SELECT COUNT(*) FROM devices WHERE status='down'").fetchone()[0]
            warning  = c.execute("SELECT COUNT(*) FROM devices WHERE status='warning'").fetchone()[0]
            unknown  = c.execute("SELECT COUNT(*) FROM devices WHERE status='unknown'").fetchone()[0]
            snmp_en  = c.execute("SELECT COUNT(*) FROM devices WHERE snmp_enabled=1").fetchone()[0]
            unacked  = c.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged=0").fetchone()[0]
            critical = c.execute("SELECT COUNT(*) FROM alerts WHERE acknowledged=0 AND severity='critical'").fetchone()[0]
            zones    = c.execute('SELECT COUNT(*) FROM zones').fetchone()[0]
            return {
                'total': total, 'up': up, 'down': down, 'warning': warning,
                'unknown': unknown, 'snmp_enabled': snmp_en,
                'unacked_alerts': unacked, 'critical_alerts': critical, 'zones': zones
            }
