#!/usr/bin/env python3
"""
NetMon - SNMP Worker (puresnmp 2.x, Python 3.9+)
"""

import threading, socket, time, ipaddress
from datetime import datetime

try:
    from puresnmp import PyWrapper, Client, V1, V2C
    from puresnmp.exc import SnmpError, Timeout as SnmpTimeout
    SNMP_OK = True
except ImportError:
    SNMP_OK = False
    print("[SNMP] puresnmp not installed — run: pip install puresnmp")

OID = {
    'sysDescr':     '1.3.6.1.2.1.1.1.0',
    'sysUpTime':    '1.3.6.1.2.1.1.3.0',
    'sysName':      '1.3.6.1.2.1.1.5.0',
    'sysLocation':  '1.3.6.1.2.1.1.6.0',
    'ifOperStatus': '1.3.6.1.2.1.2.2.1.8',
    'ifDescr':      '1.3.6.1.2.1.2.2.1.2',
}


def _creds(version, community):
    return V1(community) if version == '1' else V2C(community)


def _client(ip, version, community, port, timeout):
    return PyWrapper(Client(ip, _creds(version, community), port=port, timeout=timeout))


class SNMPWorker:
    def __init__(self, db, socketio):
        self.db = db
        self.socketio = socketio
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {'running':False,'progress':0,'total':0,'found':0,
                        'current_ip':'','message':'Idle','percent':0}

    def get_scan_status(self): return dict(self._status)
    def stop_scan(self):       self._stop.set()

    # ─── low-level helpers ───────────────────────────────────────────

    def _get(self, ip, community, oids, port=161, version='2c', timeout=2):
        if not SNMP_OK: return None
        try:
            c  = _client(ip, version, community, port, timeout)
            return {oid: str(c.get(oid)) for oid in oids}
        except Exception:
            return None

    def _walk(self, ip, community, base_oid, port=161, version='2c', timeout=2):
        if not SNMP_OK: return {}
        try:
            c = _client(ip, version, community, port, timeout)
            return {str(oid): str(val) for oid, val in c.walk(base_oid)}
        except Exception:
            return {}

    # ─── poll a single device ────────────────────────────────────────

    def poll_device(self, device):
        did, ip   = device['id'], device['ip']
        community = device.get('snmp_community', 'public')
        port      = device.get('snmp_port', 161)
        version   = device.get('snmp_version', '2c')
        old_st    = device.get('status', 'unknown')
        now       = datetime.now().isoformat()

        result = self._get(ip, community,
                           [OID['sysDescr'], OID['sysName'], OID['sysUpTime']], port, version)

        if result:
            upd = {'status':'up', 'last_polled': now}
            if result.get(OID['sysName']):   upd['sys_name']    = result[OID['sysName']]
            if result.get(OID['sysDescr']):  upd['description'] = result[OID['sysDescr']][:500]
            if result.get(OID['sysUpTime']): upd['uptime']      = result[OID['sysUpTime']]

            if old_st == 'down':
                upd['last_seen'] = now
                self._alert(device, 'info', f"{device.get('name',ip)} ({ip}) is back ONLINE")
            elif old_st == 'unknown':
                upd['last_seen'] = now

            self.db.update_device(did, upd)
            if upd.get('uptime'):
                self.db.save_metric(did, 'uptime', upd['uptime'])

            if self._check_ifaces(device, ip, community, port, version) == 'warning':
                self.db.update_device(did, {'status': 'warning'})
        else:
            self.db.update_device(did, {'status':'down','last_polled':now})
            if old_st != 'down':
                s = self.db.get_settings()
                if s.get('alert_on_down','true') == 'true':
                    self._alert(device, 'critical',
                                f"DEVICE DOWN: {device.get('name',ip)} ({ip}) — SNMP unreachable")

        updated = self.db.get_device(did)
        if updated:
            self.socketio.emit('device_status_update', updated)
            self.socketio.emit('stats_update', self.db.get_dashboard_stats())
        return updated.get('status') if updated else 'unknown'

    def _check_ifaces(self, device, ip, community, port, version):
        if_st   = self._walk(ip, community, OID['ifOperStatus'], port, version)
        if_desc = self._walk(ip, community, OID['ifDescr'],      port, version)
        down = []
        for oid, st in if_st.items():
            if str(st) in ('2', 'down'):
                idx  = oid.split('.')[-1]
                name = if_desc.get(f"{OID['ifDescr']}.{idx}", f'if{idx}')
                lo   = name.lower()
                if 'loopback' in lo or lo in ('lo','lo0'): continue
                down.append(name)
        if down:
            self._alert(device, 'warning',
                        f"Interface(s) DOWN on {device.get('name',ip)}: {', '.join(down[:5])}")
            return 'warning'
        return 'ok'

    def _alert(self, device, severity, message):
        aid = self.db.add_alert({'device_id':device['id'],
                                  'device_name':device.get('name',device.get('ip','')),
                                  'device_ip':device.get('ip',''),
                                  'severity':severity, 'message':message})
        self.socketio.emit('new_alert', {
            'id':aid,'device_id':device['id'],
            'device_name':device.get('name',''), 'device_ip':device.get('ip',''),
            'severity':severity, 'message':message, 'acknowledged':0,
            'created_at':datetime.now().isoformat()
        })
        self.socketio.emit('stats_update', self.db.get_dashboard_stats())

    # ─── network scan ────────────────────────────────────────────────

    def scan_network(self, cidr, community='public', version='2c'):
        if not SNMP_OK:
            self.socketio.emit('scan_error', {'error':'puresnmp not installed. Run: pip install puresnmp'})
            return

        with self._lock:
            self._stop.clear()
            self._status.update({'running':True,'found':0,'progress':0,'message':f'Scanning {cidr}…'})

        try:
            net   = ipaddress.ip_network(cidr, strict=False)
            hosts = list(net.hosts())
            total = len(hosts)
            self._status['total'] = total
            self.socketio.emit('scan_started', {'network':str(net),'total':total})

            found = []
            for i, host in enumerate(hosts):
                if self._stop.is_set(): break
                ip  = str(host)
                pct = round((i+1)/total*100)
                self._status.update({'progress':i+1,'current_ip':ip,'percent':pct,
                                     'message':f'Scanning {ip}…'})
                self.socketio.emit('scan_progress',
                                   {'progress':i+1,'total':total,'percent':pct,'current_ip':ip})

                result = self._get(ip, community, [OID['sysName'], OID['sysDescr']],
                                   version=version, timeout=1)
                if result:
                    name  = result.get(OID['sysName'],'').strip() or ip
                    descr = result.get(OID['sysDescr'],'').strip()
                    dev   = {'name':name,'ip':ip,'type':self._guess_type(descr),
                             'icon':self._guess_icon(descr),'description':descr[:200],
                             'sys_name':name,'snmp_enabled':True,
                             'snmp_community':community,'snmp_version':version,
                             'status':'up','zone_id':1}
                    existing = self.db.get_device_by_ip(ip)
                    if existing:
                        self.db.update_device(existing['id'],
                                              {'sys_name':name,'description':descr[:200],
                                               'snmp_enabled':1,'status':'up'})
                        dev['id'] = existing['id']
                    else:
                        try: dev['id'] = self.db.add_device(dev)
                        except Exception: pass
                    found.append(dev)
                    self._status['found'] += 1
                    self.socketio.emit('device_found', dev)

                time.sleep(0.03)

            self._status.update({'running':False,'percent':100,
                                 'message':f'Done — {len(found)} device(s) found'})
            self.socketio.emit('scan_complete', {'found':len(found),'devices':found})
            self.db.add_access_log({'source':'Scanner',
                                    'message':f'Scan {cidr}: {len(found)} found','type':'scan'})
        except Exception as e:
            self._status.update({'running':False,'message':f'Error: {e}'})
            self.socketio.emit('scan_error', {'error':str(e)})
        finally:
            self._status['running'] = False

    def _guess_type(self, d):
        if not d: return 'unknown'
        d = d.lower()
        if any(x in d for x in ('switch','catalyst','nexus')): return 'switch'
        if any(x in d for x in ('router','routeros','mikrotik')): return 'router'
        if any(x in d for x in ('linux','ubuntu','debian','centos')): return 'server'
        if any(x in d for x in ('windows','win32')): return 'server'
        if any(x in d for x in ('access point','aironet','unifi')): return 'access_point'
        if any(x in d for x in ('firewall','pfsense','fortigate','checkpoint')): return 'firewall'
        if any(x in d for x in ('printer','laserjet')): return 'printer'
        return 'unknown'

    def _guess_icon(self, d):
        t = self._guess_type(d)
        return {'switch':'switch','router':'router','server':'server',
                'access_point':'wifi','firewall':'shield','printer':'printer'}.get(t,'device')
