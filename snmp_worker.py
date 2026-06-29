#!/usr/bin/env python3
"""
NetMon - SNMP Worker (puresnmp 2.x, Python 3.9+)
"""

import threading, socket, time, ipaddress, os, subprocess, re
from datetime import datetime

try:
    from puresnmp import PyWrapper, Client, V1, V2C
    from puresnmp.exc import SnmpError, Timeout as SnmpTimeout
    try:
        from puresnmp.pdu import NoSuchObject, NoSuchInstance
    except ImportError:
        # Older puresnmp versions may not have these
        NoSuchObject = type(None)
        NoSuchInstance = type(None)
    SNMP_OK = True
except ImportError:
    SNMP_OK = False
    NoSuchObject = type(None)
    NoSuchInstance = type(None)
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


def _client(ip, version, community, port, timeout=2.0, retries=0):
    c = Client(ip, _creds(version, community), port=port)
    try:
        c.configure(timeout=timeout, retries=retries)
    except Exception:
        try:
            c.config.timeout = timeout
            c.config.retries = retries
        except Exception:
            pass
    return PyWrapper(c)


class SNMPWorker:
    def __init__(self, db, socketio):
        self.db = db
        self.socketio = socketio
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {'running':False,'progress':0,'total':0,'found':0,
                        'current_ip':'','message':'Idle','percent':0}
        self._interfaces_cache = {}
        self._if_prev = {}

    def get_scan_status(self): return dict(self._status)
    def stop_scan(self):       self._stop.set()

    # ─── low-level helpers ───────────────────────────────────────────

    async def _async_get(self, ip, community, oids, port, version, timeout):
        c = _client(ip, version, community, port, timeout=timeout, retries=0)
        res = {}
        # Try multiget first (single SNMP request for all OIDs — faster & more reliable)
        try:
            multi_result = await c.multiget(oids)
            if multi_result and isinstance(multi_result, (list, tuple)):
                for i, val in enumerate(multi_result):
                    if i < len(oids):
                        # Filter out NoSuchObject/NoSuchInstance sentinel values
                        if val is None or isinstance(val, (NoSuchObject, NoSuchInstance)):
                            continue
                        if isinstance(val, bytes):
                            try:
                                val = val.decode('utf-8', errors='ignore')
                            except Exception:
                                pass
                        str_val = str(val)
                        # Also filter string representations of sentinel values
                        if str_val.lower() in ('nosuchobject', 'nosuchinstance', 'endofmibview', 'none'):
                            continue
                        res[oids[i]] = str_val
                if res:
                    return res
        except Exception:
            pass
        # Fallback to individual gets if multiget fails
        for oid in oids:
            try:
                val = await c.get(oid)
                # Filter out NoSuchObject/NoSuchInstance sentinel values
                if val is None or isinstance(val, (NoSuchObject, NoSuchInstance)):
                    continue
                # Clean up bytes to string if needed
                if isinstance(val, bytes):
                    try:
                        val = val.decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                str_val = str(val)
                # Also filter string representations of sentinel values
                if str_val.lower() in ('nosuchobject', 'nosuchinstance', 'endofmibview', 'none'):
                    continue
                res[oid] = str_val
            except Exception:
                pass
        return res if res else None

    def _get(self, ip, community, oids, port=161, version='2c', timeout=2):
        if not SNMP_OK: return None
        import asyncio
        # Retry up to 2 times to prevent random NAT UDP packet loss
        for attempt in range(2):
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                coro = self._async_get(ip, community, oids, port, version, timeout)
                res = loop.run_until_complete(coro)
                if res:
                    return res
            except Exception:
                pass
            finally:
                if loop is not None:
                    try:
                        loop.close()
                    except Exception:
                        pass
        return None

    async def _async_walk(self, ip, community, base_oid, port, version, timeout):
        c = _client(ip, version, community, port, timeout=timeout, retries=0)
        res = {}
        try:
            async for oid, val in c.walk(base_oid):
                # Clean up bytes to string if needed
                if isinstance(val, bytes):
                    try:
                        val = val.decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                res[str(oid)] = str(val)
        except Exception:
            pass
        return res

    def _walk(self, ip, community, base_oid, port=161, version='2c', timeout=2):
        if not SNMP_OK: return {}
        import asyncio
        # Retry up to 2 times to prevent random NAT UDP packet loss
        for attempt in range(2):
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                coro = self._async_walk(ip, community, base_oid, port, version, timeout)
                res = loop.run_until_complete(coro)
                if res:
                    return res
            except Exception:
                pass
            finally:
                if loop is not None:
                    try:
                        loop.close()
                    except Exception:
                        pass
        return {}

    # ─── poll a single device ────────────────────────────────────────

    def _ping(self, ip):
        # 1. Try TCP connection check on common ports (works perfectly through NAT)
        import socket
        common_ports = [22, 80, 443, 445]
        for port in common_ports:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.2)  # Fast 200ms timeout
                result = s.connect_ex((ip, port))
                s.close()
                # 0: Connected successfully
                # 111 (Linux) or 10061 (Windows): Connection Refused (means host is active and rejected it)
                if result == 0 or result in (111, 10061):
                    return True
            except Exception:
                pass

        # 2. Fallback to standard OS Ping
        import subprocess
        import platform
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

    def _get_resource_metrics(self, ip, community, port, version, vendor_lower, descr_lower, sys_obj_id=None):
        cpu_usage = None
        memory_usage = None
        temperature = None
        
        sys_obj_id = str(sys_obj_id or '').lower()
        
        is_mikrotik = 'mikrotik' in vendor_lower or 'mikrotik' in descr_lower or 'routeros' in descr_lower or '14988' in sys_obj_id
        is_ruijie = 'ruijie' in vendor_lower or 'ruijie' in descr_lower or 'reyee' in vendor_lower or 'reyee' in descr_lower or '4881' in sys_obj_id or 'rgos' in descr_lower or ('rg-' in descr_lower and 'rap' in descr_lower)
        is_ubiquiti = 'ubiquiti' in vendor_lower or 'ubnt' in vendor_lower or 'ubiquiti' in descr_lower or 'uap' in descr_lower or 'unifi' in descr_lower or '41112' in sys_obj_id
        is_cisco = 'cisco' in vendor_lower or 'cisco' in descr_lower or ('9.1.' in sys_obj_id or '9.9.' in sys_obj_id or '.9.' in sys_obj_id)
        
        # --- VENDOR SPECIFIC QUERIES ---
        # 1. MikroTik
        if is_mikrotik:
            res = self._get(ip, community, [
                '1.3.6.1.4.1.14988.1.1.3.10.0', # CPU Load
                '1.3.6.1.4.1.14988.1.1.3.8.0',  # Temperature
                '1.3.6.1.4.1.14988.1.1.3.14.0', # Total RAM in bytes
                '1.3.6.1.4.1.14988.1.1.3.17.0'  # Free RAM in bytes
            ], port=port, version=version)
            if res:
                if res.get('1.3.6.1.4.1.14988.1.1.3.10.0') is not None:
                    try: cpu_usage = float(res['1.3.6.1.4.1.14988.1.1.3.10.0'])
                    except ValueError: pass
                if res.get('1.3.6.1.4.1.14988.1.1.3.8.0') is not None:
                    try:
                        temperature = float(res['1.3.6.1.4.1.14988.1.1.3.8.0']) / 10.0
                    except ValueError: pass
                if res.get('1.3.6.1.4.1.14988.1.1.3.14.0') and res.get('1.3.6.1.4.1.14988.1.1.3.17.0'):
                    try:
                        tot = float(res['1.3.6.1.4.1.14988.1.1.3.14.0'])
                        fre = float(res['1.3.6.1.4.1.14988.1.1.3.17.0'])
                        if tot > 0:
                            memory_usage = ((tot - fre) / tot) * 100.0
                    except Exception: pass
                    
        # 2. Ruijie / Reyee
        elif is_ruijie:
            res = self._get(ip, community, [
                '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.1.0',   # CPU 1
                '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.2.0',   # CPU 2
                '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.3.0',   # CPU 3
                '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.15.0',  # CPU 4
                '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.3.0', # RAM Util 1
                '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.2.0', # RAM Util 2
                '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.1.0', # RAM Util 3
                '1.3.6.1.4.1.4881.1.1.10.2.1.1.16.0',     # Temp 1
                '1.3.6.1.4.1.4881.1.1.10.2.1.1.20.0'      # Temp 2
            ], port=port, version=version)
            
            cpu_val = None
            mem_val = None
            temp_val = None
            
            if res:
                for k in ['1.3.6.1.4.1.4881.1.1.10.2.36.1.1.1.0', '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.2.0', '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.3.0', '1.3.6.1.4.1.4881.1.1.10.2.36.1.1.15.0']:
                    if res.get(k) is not None:
                        cpu_val = res[k]
                        break
                for k in ['1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.3.0', '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.2.0', '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.1.0']:
                    if res.get(k) is not None:
                        mem_val = res[k]
                        break
                for k in ['1.3.6.1.4.1.4881.1.1.10.2.1.1.16.0', '1.3.6.1.4.1.4881.1.1.10.2.1.1.20.0']:
                    if res.get(k) is not None:
                        temp_val = res[k]
                        break
            
            if cpu_val is None:
                cpu_walk = self._walk(ip, community, '1.3.6.1.4.1.4881.1.1.10.2.36.1.1', port=port, version=version)
                if cpu_walk:
                    for v in cpu_walk.values():
                        try:
                            float(v)
                            cpu_val = v
                            break
                        except ValueError: pass
                        
            if mem_val is None:
                mem_walk = self._walk(ip, community, '1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1', port=port, version=version)
                if mem_walk:
                    for v in mem_walk.values():
                        try:
                            float(v)
                            mem_val = v
                            break
                        except ValueError: pass
                        
            if temp_val is None:
                temp_walk = self._walk(ip, community, '1.3.6.1.4.1.4881.1.1.10.2.1.1', port=port, version=version)
                if temp_walk:
                    for v in temp_walk.values():
                        try:
                            float(v)
                            temp_val = v
                            break
                        except ValueError: pass
                        
            if cpu_val is not None:
                try: cpu_usage = float(cpu_val)
                except ValueError: pass
            if mem_val is not None:
                try: memory_usage = float(mem_val)
                except ValueError: pass
            if temp_val is not None:
                try:
                    val = float(temp_val)
                    if val > 120: val /= 10.0
                    temperature = val
                except ValueError: pass
                
        # 3. Ubiquiti / UniFi SNMP
        elif is_ubiquiti:
            res = self._get(ip, community, [
                '1.3.6.1.4.1.41112.1.4.1.1.4.1', # CPU load percentage
                '1.3.6.1.4.1.41112.1.4.1.1.5.1'  # Memory usage percentage
            ], port=port, version=version)
            if res:
                if res.get('1.3.6.1.4.1.41112.1.4.1.1.4.1') is not None:
                    try: cpu_usage = float(res['1.3.6.1.4.1.41112.1.4.1.1.4.1'])
                    except ValueError: pass
                if res.get('1.3.6.1.4.1.41112.1.4.1.1.5.1') is not None:
                    try: memory_usage = float(res['1.3.6.1.4.1.41112.1.4.1.1.5.1'])
                    except ValueError: pass
                    
        # 4. Cisco
        elif is_cisco:
            res = self._get(ip, community, [
                '1.3.6.1.4.1.9.9.109.1.1.1.1.5.1', # CPU 1-min load %
                '1.3.6.1.4.1.9.9.48.1.1.1.5.1',    # Memory Used
                '1.3.6.1.4.1.9.9.48.1.1.1.6.1',    # Memory Free
                '1.3.6.1.4.1.9.9.13.1.3.1.3.1'     # Cisco Env Temp
            ], port=port, version=version)
            if res:
                if res.get('1.3.6.1.4.1.9.9.109.1.1.1.1.5.1') is not None:
                    try: cpu_usage = float(res['1.3.6.1.4.1.9.9.109.1.1.1.1.5.1'])
                    except ValueError: pass
                if res.get('1.3.6.1.4.1.9.9.48.1.1.1.5.1') is not None and res.get('1.3.6.1.4.1.9.9.48.1.1.1.6.1') is not None:
                    try:
                        used = float(res['1.3.6.1.4.1.9.9.48.1.1.1.5.1'])
                        free = float(res['1.3.6.1.4.1.9.9.48.1.1.1.6.1'])
                        if (used + free) > 0:
                            memory_usage = (used / (used + free)) * 100.0
                    except Exception: pass
                if res.get('1.3.6.1.4.1.9.9.13.1.3.1.3.1') is not None:
                    try: temperature = float(res['1.3.6.1.4.1.9.9.13.1.3.1.3.1'])
                    except ValueError: pass
                    
        # --- GENERIC FALLBACKS FOR ANY VENDOR IF STILL NONE ---
        if cpu_usage is None:
            cpu_walk = self._walk(ip, community, '1.3.6.1.2.1.25.3.3.1.2', port=port, version=version)
            if cpu_walk:
                cpu_vals = [float(v) for v in cpu_walk.values() if str(v).strip().isdigit()]
                if cpu_vals: cpu_usage = sum(cpu_vals) / len(cpu_vals)
            else:
                cpu_res = self._get(ip, community, ['1.3.6.1.2.1.25.3.3.1.2.1'], port=port, version=version)
                if cpu_res and cpu_res.get('1.3.6.1.2.1.25.3.3.1.2.1') is not None:
                    try: cpu_usage = float(cpu_res['1.3.6.1.2.1.25.3.3.1.2.1'])
                    except ValueError: pass
            
            # Try UCD-SNMP-MIB for Linux systems
            if cpu_usage is None:
                cpu_res = self._get(ip, community, [
                    '1.3.6.1.4.1.2021.11.9.0',
                    '1.3.6.1.4.1.2021.11.10.0'
                ], port=port, version=version)
                if cpu_res and cpu_res.get('1.3.6.1.4.1.2021.11.9.0') is not None:
                    try:
                        u = float(cpu_res.get('1.3.6.1.4.1.2021.11.9.0', 0))
                        s = float(cpu_res.get('1.3.6.1.4.1.2021.11.10.0', 0))
                        cpu_usage = u + s
                    except ValueError: pass
                    
        if memory_usage is None:
            # Try UCD-SNMP-MIB for Linux first (memTotalReal .5, memAvailReal .6)
            res_ucd = self._get(ip, community, [
                '1.3.6.1.4.1.2021.4.5.0',
                '1.3.6.1.4.1.2021.4.6.0'
            ], port=port, version=version)
            if res_ucd and res_ucd.get('1.3.6.1.4.1.2021.4.5.0') and res_ucd.get('1.3.6.1.4.1.2021.4.6.0'):
                try:
                    tot = float(res_ucd['1.3.6.1.4.1.2021.4.5.0'])
                    avail = float(res_ucd['1.3.6.1.4.1.2021.4.6.0'])
                    if tot > 0:
                        memory_usage = ((tot - avail) / tot) * 100.0
                except Exception: pass

            if memory_usage is None:
                storage_types = self._walk(ip, community, '1.3.6.1.2.1.25.2.3.1.2', port=port, version=version)
                ram_idx = None
                if storage_types:
                    for k, v in storage_types.items():
                        if v == '1.3.6.1.2.1.25.2.1.2': # Physical RAM type
                            ram_idx = k.split('.')[-1]
                            break
                if ram_idx:
                    res_ram = self._get(ip, community, [
                        f'1.3.6.1.2.1.25.2.3.1.5.{ram_idx}',
                        f'1.3.6.1.2.1.25.2.3.1.6.{ram_idx}'
                    ], port=port, version=version)
                    if res_ram:
                        try:
                            tot = float(res_ram.get(f'1.3.6.1.2.1.25.2.3.1.5.{ram_idx}', 0))
                            used = float(res_ram.get(f'1.3.6.1.2.1.25.2.3.1.6.{ram_idx}', 0))
                            if tot > 0:
                                memory_usage = (used / tot) * 100.0
                        except Exception: pass
                        
            if memory_usage is None:
                common_indices = ['65536', '1', '101', '102', '2', '3']
                oids_to_try = []
                for idx in common_indices:
                    oids_to_try.append(f'1.3.6.1.2.1.25.2.3.1.5.{idx}')
                    oids_to_try.append(f'1.3.6.1.2.1.25.2.3.1.6.{idx}')
                res_ram = self._get(ip, community, oids_to_try, port=port, version=version)
                if res_ram:
                    for idx in common_indices:
                        size_oid = f'1.3.6.1.2.1.25.2.3.1.5.{idx}'
                        used_oid = f'1.3.6.1.2.1.25.2.3.1.6.{idx}'
                        if res_ram.get(size_oid) and res_ram.get(used_oid):
                            try:
                                tot = float(res_ram[size_oid])
                                used = float(res_ram[used_oid])
                                if tot > 0 and used <= tot:
                                    memory_usage = (used / tot) * 100.0
                                    break
                            except Exception: pass
                            
        # Boundary validation & scaling normalization
        if cpu_usage is not None:
            if cpu_usage > 100.0: cpu_usage /= 10.0
            cpu_usage = max(0.0, min(100.0, cpu_usage))
            
        if memory_usage is not None:
            if memory_usage > 100.0: memory_usage /= 10.0
            memory_usage = max(0.0, min(100.0, memory_usage))
            
        if temperature is not None:
            if temperature > 150.0: temperature /= 10.0
            if temperature < -40.0 or temperature > 120.0:
                temperature = None
                
        return {
            'cpu_usage': cpu_usage,
            'memory_usage': memory_usage,
            'temperature': temperature
        }

    def poll_device(self, device):
        did, ip   = device['id'], device['ip']
        community = device.get('snmp_community', 'public')
        port      = device.get('snmp_port', 161)
        version   = device.get('snmp_version', '2c')
        old_st    = device.get('status', 'unknown')
        snmp_en   = bool(device.get('snmp_enabled', 0))
        now       = datetime.now().isoformat()

        # Target OIDs based on vendor detection
        vendor_lower = str(device.get('vendor') or '').lower()
        descr_lower = str(device.get('description') or '').lower()

        result = None
        if snmp_en:
            result = self._get(ip, community, [
                OID['sysDescr'], 
                '1.3.6.1.2.1.1.2.0', # sysObjectID
                OID['sysUpTime'], 
                OID['sysName']
            ], port, version)

        if result:
            # ── SNMP responded: genuine UP with full data ──
            upd = {'status':'up', 'last_polled': now}
            if result.get(OID['sysName']):   upd['sys_name']    = result[OID['sysName']]
            
            sys_obj_id = str(result.get('1.3.6.1.2.1.1.2.0', '')).lower()
            if '14988' in sys_obj_id:
                upd['vendor'] = 'MikroTik'
            elif '4881' in sys_obj_id:
                upd['vendor'] = 'Ruijie'
            elif '41112' in sys_obj_id:
                upd['vendor'] = 'Ubiquiti'
            elif '9.1.' in sys_obj_id or '9.9.' in sys_obj_id or '.9.' in sys_obj_id:
                upd['vendor'] = 'Cisco'
                
            if result.get(OID['sysDescr']):  
                upd['description'] = result[OID['sysDescr']][:500]
                if not upd.get('vendor'):
                    desc_val = result[OID['sysDescr']].lower()
                    if 'ruijie' in desc_val or 'reyee' in desc_val:
                        upd['vendor'] = 'Ruijie'
                    elif 'mikrotik' in desc_val or 'routeros' in desc_val:
                        upd['vendor'] = 'MikroTik'
                    elif 'ubiquiti' in desc_val or 'ubnt' in desc_val or 'unifi' in desc_val:
                        upd['vendor'] = 'Ubiquiti'
                    elif 'cisco' in desc_val:
                        upd['vendor'] = 'Cisco'
            if result.get(OID['sysUpTime']): upd['uptime']      = result[OID['sysUpTime']]

            # Fetch updated vendor name
            current_vendor = upd.get('vendor') or device.get('vendor') or ''
            vendor_lower = str(current_vendor).lower()
            current_desc = upd.get('description') or device.get('description') or ''
            descr_lower = str(current_desc).lower()

            # Dynamic resource usage extraction
            metrics = self._get_resource_metrics(ip, community, port, version, vendor_lower, descr_lower, result.get('1.3.6.1.2.1.1.2.0', ''))
            upd.update(metrics)
            
            # Save metrics to DB timeseries
            if metrics['cpu_usage'] is not None:
                self.db.save_metric(did, 'cpu_usage', metrics['cpu_usage'])
            if metrics['memory_usage'] is not None:
                self.db.save_metric(did, 'memory_usage', metrics['memory_usage'])
            if metrics['temperature'] is not None:
                self.db.save_metric(did, 'temperature', metrics['temperature'])

            # Poll WAN traffic throughput if device type is router
            if device.get('type') == 'router':
                traffic_data = self._poll_router_traffic(did, ip, community, port, version)
                if traffic_data:
                    upd.update(traffic_data)
                    self.db.save_metric(did, 'wan_in', traffic_data['wan_in'])
                    self.db.save_metric(did, 'wan_out', traffic_data['wan_out'])

            if old_st == 'down':
                upd['last_seen'] = now
                self._alert(device, 'info', f"{device.get('name',ip)} ({ip}) is back ONLINE")
            elif old_st == 'unknown':
                upd['last_seen'] = now

            self.db.update_device(did, upd)
            if upd.get('uptime'):
                self.db.save_metric(did, 'uptime', upd['uptime'])

        elif snmp_en:
            # ── SNMP enabled but SNMP FAILED: check ping, mark SNMP as broken ──
            is_alive = self._ping(ip)
            if is_alive:
                # Device reachable via ping but SNMP is not responding
                upd = {'status': 'up', 'last_polled': now,
                        'snmp_enabled': 0,
                        'cpu_usage': None, 'memory_usage': None, 'temperature': None}
                if old_st == 'down':
                    upd['last_seen'] = now
                    self._alert(device, 'info', f"{device.get('name',ip)} ({ip}) is back ONLINE (ping only)")
                elif old_st == 'unknown':
                    upd['last_seen'] = now
                self._alert(device, 'warning',
                            f"SNMP unreachable on {device.get('name',ip)} ({ip}) — SNMP disabled, check community/config")
                print(f"[SNMP] FAILED for {ip} — device alive via ping but SNMP not responding, disabling SNMP")
                self.db.update_device(did, upd)
            else:
                self.db.update_device(did, {'status':'down','last_polled':now,
                                             'cpu_usage': None, 'memory_usage': None, 'temperature': None})
                if old_st != 'down':
                    s = self.db.get_settings()
                    if s.get('alert_on_down','true') == 'true':
                        self._alert(device, 'critical',
                                    f"DEVICE DOWN: {device.get('name',ip)} ({ip}) — unreachable")

        else:
            # ── SNMP not enabled: ping-only check ──
            is_alive = self._ping(ip)
            if is_alive:
                upd = {'status': 'up', 'last_polled': now}
                if old_st == 'down':
                    upd['last_seen'] = now
                    self._alert(device, 'info', f"{device.get('name',ip)} ({ip}) is back ONLINE")
                elif old_st == 'unknown':
                    upd['last_seen'] = now
                self.db.update_device(did, upd)
            else:
                self.db.update_device(did, {'status':'down','last_polled':now})
                if old_st != 'down':
                    s = self.db.get_settings()
                    if s.get('alert_on_down','true') == 'true':
                        self._alert(device, 'critical',
                                    f"DEVICE DOWN: {device.get('name',ip)} ({ip}) — unreachable")

        updated = self.db.get_device(did)
        if updated:
            self.socketio.emit('device_status_update', updated)
            self.socketio.emit('stats_update', self.db.get_dashboard_stats())
        return updated.get('status') if updated else 'unknown'

    def get_detailed_stats(self, device):
        ip = device['ip']
        community = device.get('snmp_community', 'public') or 'public'
        port = device.get('snmp_port', 161) or 161
        version = device.get('snmp_version', '2c') or '2c'
        
        # 1. Fetch system details
        res_sys = self._get(ip, community, [
            '1.3.6.1.2.1.1.1.0', # sysDescr
            '1.3.6.1.2.1.1.2.0', # sysObjectID
            '1.3.6.1.2.1.1.3.0', # sysUpTime
            '1.3.6.1.2.1.1.5.0', # sysName
        ], port=port, version=version)
        
        sys_obj_id = ""
        uptime = ""
        sys_name = ""
        description = ""
        if res_sys:
            uptime = res_sys.get('1.3.6.1.2.1.1.3.0', '')
            sys_name = res_sys.get('1.3.6.1.2.1.1.5.0', '')
            description = res_sys.get('1.3.6.1.2.1.1.1.0', '')
            sys_obj_id = res_sys.get('1.3.6.1.2.1.1.2.0', '')

        # 2. CPU / Memory / Temp based on unified parser
        vendor_lower = str(device.get('vendor') or '').lower()
        descr_lower = str(description or device.get('description') or '').lower()
        
        metrics = self._get_resource_metrics(ip, community, port, version, vendor_lower, descr_lower, sys_obj_id)
        cpu_usage = metrics['cpu_usage']
        memory_usage = metrics['memory_usage']
        temperature = metrics['temperature']

        # 3. Interfaces info (Parallel SNMP Walks) with cache fallback
        cache_key = device['id']
        
        new_desc, new_type, new_speed, new_oper = {}, {}, {}, {}
        new_hc_in, new_hc_out, new_in, new_out, new_high_speed = {}, {}, {}, {}, {}
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def fetch_all_walks():
                tasks = [
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.2', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.3', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.5', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.8', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.31.1.1.1.6', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.31.1.1.1.10', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.10', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.2.2.1.16', port, version, timeout=1.5),
                    self._async_walk(ip, community, '1.3.6.1.2.1.31.1.1.1.15', port, version, timeout=1.5)
                ]
                return await asyncio.gather(*tasks, return_exceptions=True)
                
            results = loop.run_until_complete(fetch_all_walks())
            if results and len(results) == 9:
                def clean_res(val):
                    return val if isinstance(val, dict) else {}
                new_desc = clean_res(results[0])
                new_type = clean_res(results[1])
                new_speed = clean_res(results[2])
                new_oper = clean_res(results[3])
                new_hc_in = clean_res(results[4])
                new_hc_out = clean_res(results[5])
                new_in = clean_res(results[6])
                new_out = clean_res(results[7])
                new_high_speed = clean_res(results[8])
        except Exception as e:
            print(f"[SNMP Detail] Parallel walks failed: {e}")
        finally:
            try:
                loop.close()
            except Exception:
                pass

        cached = self._interfaces_cache.get(cache_key)
        
        # Prevent partial-read cache poisoning (e.g. if device rate limits after 1 min and returns only Loopback)
        # We only consider the new walk valid if it has at least 80% of the interfaces we saw before.
        is_valid = False
        if new_desc:
            if not cached:
                is_valid = True
            else:
                cache_age = time.time() - cached.get('_ts', 0)
                if len(new_desc) >= len(cached['if_desc']):
                    is_valid = True          # sama atau lebih banyak → selalu valid
                elif cache_age > 300:
                    is_valid = True          # cache stale >5 menit → izinkan refresh
                # else: lebih sedikit DAN cache masih fresh → rate-limited, tolak

        if is_valid:
            # Cache the successful SNMP walk. For metrics that failed, retain previous cached values if any.
            self._interfaces_cache[cache_key] = {
                '_ts': time.time(),
                'if_desc': new_desc,
                'if_type': new_type or (cached['if_type'] if cached else {}),
                'if_speed': new_speed or (cached['if_speed'] if cached else {}),
                'if_oper': new_oper or (cached['if_oper'] if cached else {}),
                'if_hc_in': new_hc_in or (cached['if_hc_in'] if cached else {}),
                'if_hc_out': new_hc_out or (cached['if_hc_out'] if cached else {}),
                'if_in': new_in or (cached['if_in'] if cached else {}),
                'if_out': new_out or (cached['if_out'] if cached else {}),
                'if_high_speed': new_high_speed or (cached['if_high_speed'] if cached else {})
            }
            if_desc = new_desc
            if_type = self._interfaces_cache[cache_key]['if_type']
            if_speed = self._interfaces_cache[cache_key]['if_speed']
            if_oper = self._interfaces_cache[cache_key]['if_oper']
            if_hc_in = self._interfaces_cache[cache_key]['if_hc_in']
            if_hc_out = self._interfaces_cache[cache_key]['if_hc_out']
            if_in = self._interfaces_cache[cache_key]['if_in']
            if_out = self._interfaces_cache[cache_key]['if_out']
            if_high_speed = self._interfaces_cache[cache_key]['if_high_speed']
        else:
            # Momentary walk failure or partial read: use cache if available
            cached = self._interfaces_cache.get(cache_key)
            if cached:
                if_desc = cached['if_desc']
                if_type = cached['if_type']
                if_speed = cached['if_speed']
                if_oper = new_oper if new_oper else cached['if_oper']
                if_hc_in = new_hc_in if new_hc_in else cached['if_hc_in']
                if_hc_out = new_hc_out if new_hc_out else cached['if_hc_out']
                if_in = new_in if new_in else cached['if_in']
                if_out = new_out if new_out else cached['if_out']
                if_high_speed = new_high_speed if new_high_speed else cached['if_high_speed']
            else:
                if_desc, if_type, if_speed, if_oper = {}, {}, {}, {}
                if_hc_in, if_hc_out, if_in, if_out, if_high_speed = {}, {}, {}, {}, {}

        interfaces = []
        for oid, name in if_desc.items():
            idx = oid.split('.')[-1]
            t = if_type.get(f"1.3.6.1.2.1.2.2.1.3.{idx}", "6")
            
            if t == '24': continue
            name_lower = str(name).lower()
            if 'loopback' in name_lower or name_lower in ('lo','lo0'): continue
            
            status_val = if_oper.get(f"1.3.6.1.2.1.2.2.1.8.{idx}", "4")
            status = 'up' if str(status_val) == '1' else 'down'
            
            speed_bps = 0
            if f"1.3.6.1.31.1.1.1.15.{idx}" in if_high_speed:
                try:
                    speed_bps = float(if_high_speed[f"1.3.6.1.31.1.1.1.15.{idx}"]) * 1000000
                except ValueError:
                    pass
            
            if speed_bps == 0 and f"1.3.6.1.2.1.31.1.1.1.15.{idx}" in if_high_speed:
                try:
                    speed_bps = float(if_high_speed[f"1.3.6.1.2.1.31.1.1.1.15.{idx}"]) * 1000000
                except ValueError:
                    pass

            if speed_bps == 0:
                try:
                    speed_bps = float(if_speed.get(f"1.3.6.1.2.1.2.2.1.5.{idx}", 0))
                except ValueError:
                    pass
            
            rx_bytes = 0
            tx_bytes = 0
            
            hc_in_val = if_hc_in.get(f"1.3.6.1.2.1.31.1.1.1.6.{idx}") or if_hc_in.get(f"1.3.6.1.31.1.1.1.6.{idx}")
            hc_out_val = if_hc_out.get(f"1.3.6.1.2.1.31.1.1.1.10.{idx}") or if_hc_out.get(f"1.3.6.1.31.1.1.1.10.{idx}")
            
            if hc_in_val is not None:
                try: rx_bytes = int(hc_in_val)
                except ValueError: pass
            else:
                try: rx_bytes = int(if_in.get(f"1.3.6.1.2.1.2.2.1.10.{idx}", 0))
                except ValueError: pass
                
            if hc_out_val is not None:
                try: tx_bytes = int(hc_out_val)
                except ValueError: pass
            else:
                try: tx_bytes = int(if_out.get(f"1.3.6.1.2.1.2.2.1.16.{idx}", 0))
                except ValueError: pass

            interfaces.append({
                'index': int(idx),
                'name': str(name),
                'status': status,
                'speed': speed_bps,
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes
            })
            
        interfaces.sort(key=lambda x: x['index'])
        
        return {
            'uptime': uptime,
            'sys_name': sys_name,
            'description': description,
            'cpu_usage': cpu_usage,
            'memory_usage': memory_usage,
            'temperature': temperature,
            'interfaces': interfaces
        }

    def collect_interface_traffic(self, device):
        """Walk ifHCInOctets/ifHCOutOctets, hitung bps dari delta, simpan ke DB."""
        if not SNMP_OK:
            return
        did       = device['id']
        ip        = device.get('ip', '')
        community = device.get('snmp_community', 'public') or 'public'
        port      = device.get('snmp_port', 161) or 161
        version   = device.get('snmp_version', '2c') or '2c'

        if_desc = self._walk(ip, community, '1.3.6.1.2.1.2.2.1.2', port, version, timeout=2)
        if not if_desc:
            return

        hc_in  = self._walk(ip, community, '1.3.6.1.2.1.31.1.1.1.6',  port, version, timeout=2)
        hc_out = self._walk(ip, community, '1.3.6.1.2.1.31.1.1.1.10', port, version, timeout=2)
        is_64bit = True
        if not hc_in:
            hc_in  = self._walk(ip, community, '1.3.6.1.2.1.2.2.1.10', port, version, timeout=2)
            hc_out = self._walk(ip, community, '1.3.6.1.2.1.2.2.1.16', port, version, timeout=2)
            is_64bit = False

        now_ts = time.time()
        for oid, name in if_desc.items():
            idx = oid.split('.')[-1]
            if str(name).lower() in ('lo', 'lo0') or 'loopback' in str(name).lower():
                continue
            rx = next((int(v) for k in [
                f'1.3.6.1.2.1.31.1.1.1.6.{idx}', f'1.3.6.1.31.1.1.1.6.{idx}',
                f'1.3.6.1.2.1.2.2.1.10.{idx}']
                if (v := (hc_in or {}).get(k)) is not None), None)
            tx = next((int(v) for k in [
                f'1.3.6.1.2.1.31.1.1.1.10.{idx}', f'1.3.6.1.31.1.1.1.10.{idx}',
                f'1.3.6.1.2.1.2.2.1.16.{idx}']
                if (v := (hc_out or {}).get(k)) is not None), None)
            if rx is None or tx is None:
                continue
            key  = (did, idx)
            prev = self._if_prev.get(key)
            self._if_prev[key] = {'rx': rx, 'tx': tx, 'ts': now_ts}
            if prev:
                dt = now_ts - prev['ts']
                if dt <= 0:
                    continue
                d_rx = rx - prev['rx']
                d_tx = tx - prev['tx']
                
                # Rollover / Reboot protection
                if d_rx < 0:
                    if is_64bit:
                        d_rx = 0
                    else:
                        if prev['rx'] > 3000000000:
                            d_rx += 2**32
                        else:
                            d_rx = 0
                            
                if d_tx < 0:
                    if is_64bit:
                        d_tx = 0
                    else:
                        if prev['tx'] > 3000000000:
                            d_tx += 2**32
                        else:
                            d_tx = 0
                            
                rx_bps = (d_rx * 8) / dt
                tx_bps = (d_tx * 8) / dt
                if rx_bps <= 100e9 and tx_bps <= 100e9:
                    self.db.save_interface_traffic(did, str(name), int(idx), rx_bps, tx_bps)

    def _poll_router_traffic(self, did, ip, community, port, version):
        # 1. Walk ifDescr and ifOperStatus to find the best WAN interface
        if_desc = self._walk(ip, community, '1.3.6.1.2.1.2.2.1.2', port, version)
        if_st = self._walk(ip, community, '1.3.6.1.2.1.2.2.1.8', port, version)
        
        target_idx = None
        # Look for active interface (OperStatus 1 = UP) with WAN/ether1/sfp/eth0/pppoe description
        for oid, desc in if_desc.items():
            idx = oid.split('.')[-1]
            status = str(if_st.get(f"1.3.6.1.2.1.2.2.1.8.{idx}", ""))
            if status == '1':
                desc_lower = str(desc).lower()
                if 'wan' in desc_lower or 'pppoe' in desc_lower or desc_lower in ('ether1', 'sfpplus1', 'sfp1', 'eth0', 'ge0/0'):
                    target_idx = idx
                    break
        
        # Fallback to first active non-loopback interface if no 'wan' named interface is found
        if not target_idx:
            for oid, status in if_st.items():
                if str(status) == '1':
                    idx = oid.split('.')[-1]
                    desc = if_desc.get(f"1.3.6.1.2.1.2.2.1.2.{idx}", "")
                    desc_lower = str(desc).lower()
                    if 'loopback' not in desc_lower and desc_lower not in ('lo', 'lo0'):
                        target_idx = idx
                        break
                        
        if not target_idx:
            return None
            
        # 2. Query ifHCInOctets/ifHCOutOctets (64-bit) first, fallback to ifInOctets/ifOutOctets (32-bit)
        traffic = self._get(ip, community, [
            f"1.3.6.1.2.1.31.1.1.1.6.{target_idx}",  # ifHCInOctets
            f"1.3.6.1.2.1.31.1.1.1.10.{target_idx}", # ifHCOutOctets
            f"1.3.6.1.2.1.2.2.1.10.{target_idx}",    # ifInOctets
            f"1.3.6.1.2.1.2.2.1.16.{target_idx}"     # ifOutOctets
        ], port, version)
        
        if not traffic:
            return None
            
        try:
            in_octets = None
            out_octets = None
            is_64bit = False
            
            hc_in_val = traffic.get(f"1.3.6.1.2.1.31.1.1.1.6.{target_idx}")
            hc_out_val = traffic.get(f"1.3.6.1.2.1.31.1.1.1.10.{target_idx}")
            if hc_in_val is not None and hc_out_val is not None:
                in_octets = int(hc_in_val)
                out_octets = int(hc_out_val)
                is_64bit = True
            else:
                in_octets = int(traffic.get(f"1.3.6.1.2.1.2.2.1.10.{target_idx}", 0))
                out_octets = int(traffic.get(f"1.3.6.1.2.1.2.2.1.16.{target_idx}", 0))
            
            now_ts = time.time()
            if not hasattr(self, '_last_traffic'):
                self._last_traffic = {}
                
            last_data = self._last_traffic.get(did)
            self._last_traffic[did] = {"in": in_octets, "out": out_octets, "ts": now_ts}
            
            if last_data:
                delta_t = now_ts - last_data["ts"]
                if delta_t > 0:
                    delta_in = in_octets - last_data["in"]
                    delta_out = out_octets - last_data["out"]
                    
                    # Rollover / Reboot protection
                    if delta_in < 0:
                        if is_64bit:
                            delta_in = 0
                        else:
                            if last_data["in"] > 3000000000:
                                delta_in += 2**32
                            else:
                                delta_in = 0
                                
                    if delta_out < 0:
                        if is_64bit:
                            delta_out = 0
                        else:
                            if last_data["out"] > 3000000000:
                                delta_out += 2**32
                            else:
                                delta_out = 0
                                
                    wan_in_bps = (delta_in * 8) / delta_t
                    wan_out_bps = (delta_out * 8) / delta_t
                    return {"wan_in": wan_in_bps, "wan_out": wan_out_bps}
        except Exception:
            pass
        return None

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

    def scan_network(self, cidr, community='public', version='2c', zone_id=1, method='snmp'):
        if method == 'snmp' and not SNMP_OK:
            self.socketio.emit('scan_error', {'error':'puresnmp not installed. Run: pip install puresnmp'})
            return

        with self._lock:
            self._stop.clear()
            self._status.update({'running':True,'found':0,'progress':0,'message':f'Scanning {cidr}…'})

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            net   = ipaddress.ip_network(cidr, strict=False)
            hosts = list(net.hosts())
            total = len(hosts)
            self._status['total'] = total
            self.socketio.emit('scan_started', {'network':str(net),'total':total})

            found = []
            progress_counter = 0
            progress_lock = threading.Lock()

            def scan_ip(ip):
                if self._stop.is_set(): return None
                
                dev = None
                
                if method == 'snmp':
                    oids = [OID['sysName'], OID['sysDescr'], '1.3.6.1.2.1.1.2.0']
                    
                    # Try with user-provided community string first
                    result = self._get(ip, community, oids, version=version, timeout=2.5)
                    # Fallback to SNMPv1 if v2c failed
                    if not result and version == '2c':
                        result = self._get(ip, community, oids, version='1', timeout=2.5)
                    
                    # Try common community strings if user-provided one failed
                    if not result:
                        for alt_community in ('public', 'private'):
                            if alt_community == community:
                                continue
                            result = self._get(ip, alt_community, oids, version=version, timeout=2.0)
                            if result:
                                # Override community with the one that worked
                                community_used = alt_community
                                break
                        else:
                            community_used = community
                    else:
                        community_used = community
                        
                    if result:
                        name  = result.get(OID['sysName'],'').strip() or ip
                        descr = result.get(OID['sysDescr'],'').strip()
                        sys_obj_id = str(result.get('1.3.6.1.2.1.1.2.0', '')).lower()
                        descr_lower = descr.lower()
                        vendor = 'Unknown'
                        if '4881' in sys_obj_id or 'ruijie' in descr_lower or 'reyee' in descr_lower or 'rgos' in descr_lower:
                            vendor = 'Ruijie'
                        elif '14988' in sys_obj_id or 'mikrotik' in descr_lower or 'routeros' in descr_lower:
                            vendor = 'MikroTik'
                        elif '41112' in sys_obj_id or 'ubiquiti' in descr_lower or 'ubnt' in descr_lower or 'unifi' in descr_lower:
                            vendor = 'Ubiquiti'
                        elif 'cisco' in descr_lower:
                            vendor = 'Cisco'
                        
                        dev = {'name':name,'ip':ip,'type':self._guess_type(descr, vendor=vendor),
                               'vendor':vendor,
                               'icon':self._guess_icon(descr, vendor=vendor),'description':descr[:200],
                               'sys_name':name,'snmp_enabled':True,
                               'snmp_community':community_used,'snmp_version':version,
                               'status':'up','zone_id':zone_id, 'source':'scan'}
                        print(f"[Scan] SNMP detected: {ip} → {name} ({vendor})")
                
                elif method == 'icmp':
                    ping_cmd = ["ping", "-n", "1", "-w", "500", ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", "1", ip]
                    res = subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if res.returncode == 0:
                        dev = {'name':ip,'ip':ip,'type':'unknown','vendor':'Unknown','icon':'unknown',
                               'description':'Discovered via ICMP','snmp_enabled':False,
                               'status':'up','zone_id':zone_id, 'source':'scan'}
                
                elif method == 'arp':
                    ping_cmd = ["ping", "-n", "1", "-w", "500", ip] if os.name == 'nt' else ["ping", "-c", "1", "-W", "1", ip]
                    subprocess.run(ping_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    out = ""
                    try:
                        if os.name == 'nt':
                            res = subprocess.run(["arp", "-a", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
                            out = res.stdout
                        else:
                            res = subprocess.run(["arp", "-n", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1)
                            out = res.stdout
                            if (not out or "No ARP" in out) and os.path.exists("/proc/net/arp"):
                                with open("/proc/net/arp", "r") as f:
                                    out = f.read()
                    except Exception:
                        pass
                    
                    mac = ""
                    mac_re = re.compile(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})')
                    for line in out.splitlines():
                        if ip in line:
                            m = mac_re.search(line)
                            if m:
                                mac = m.group(0).replace('-', ':').lower()
                                break
                    if mac:
                        dev = {'name':ip,'ip':ip,'mac':mac,'type':'unknown','vendor':'Unknown','icon':'unknown',
                               'description':'Discovered via ARP','snmp_enabled':False,
                               'status':'up','zone_id':zone_id, 'source':'scan'}

                if dev:
                    try:
                        existing = self.db.get_device_by_ip(ip)
                        if existing:
                            updates = {'status':'up','zone_id':zone_id}

                            if method == 'snmp':
                                # SNMP scan: update all fields including SNMP config
                                if 'sys_name' in dev: updates['sys_name'] = dev['sys_name']
                                if 'description' in dev: updates['description'] = dev['description']
                                if 'vendor' in dev: updates['vendor'] = dev['vendor']
                                updates['snmp_enabled'] = 1
                                if dev.get('snmp_community'): updates['snmp_community'] = dev['snmp_community']
                                if dev.get('snmp_version'): updates['snmp_version'] = dev['snmp_version']
                            else:
                                # ICMP/ARP scan: NEVER overwrite snmp_enabled, community,
                                # version, description, or vendor on existing devices
                                # to protect data from prior SNMP detection
                                if dev.get('mac'): updates['mac'] = dev['mac']

                            self.db.update_device(existing['id'], updates)
                            dev['id'] = existing['id']
                        else:
                            dev['id'] = self.db.add_device(dev)
                        return dev
                    except Exception:
                        pass
                return None

            max_workers = 30
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(scan_ip, str(host)): str(host) for host in hosts}
                for future in as_completed(futures):
                    if self._stop.is_set():
                        break
                    ip = futures[future]
                    with progress_lock:
                        progress_counter += 1
                        pct = round((progress_counter)/total*100)
                        self._status.update({'progress':progress_counter,'current_ip':ip,'percent':pct,
                                             'message':f'Scanning {ip}…'})
                        self.socketio.emit('scan_progress',
                                           {'progress':progress_counter,'total':total,'percent':pct,'current_ip':ip})
                    try:
                        dev = future.result()
                        if dev:
                            found.append(dev)
                            with progress_lock:
                                self._status['found'] += 1
                            self.socketio.emit('device_found', dev)
                    except Exception as e:
                        print(f"[Scan] Error scanning {ip}: {e}")

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

    def _guess_type(self, d, vendor=''):
        if not d: return 'unknown'
        d = d.lower()
        vendor = vendor.lower()
        if any(x in d for x in ('switch','catalyst','nexus')): return 'switch'
        if any(x in d for x in ('router','routeros','mikrotik')): return 'router'
        if any(x in d for x in ('linux','ubuntu','debian','centos')): return 'server'
        if any(x in d for x in ('windows','win32')): return 'server'
        if any(x in d for x in ('access point','aironet','unifi','rap','rg-rap','wlan ap','wireless ap','reyee ap')): return 'access_point'
        if vendor == 'ruijie' and ('rgos' in d or 'rg-' in d) and not any(x in d for x in ('nbs','nps','s29','s37','s57')): return 'access_point'
        if any(x in d for x in ('firewall','pfsense','fortigate','checkpoint')): return 'firewall'
        if any(x in d for x in ('printer','laserjet')): return 'printer'
        return 'unknown'

    def _guess_icon(self, d, vendor=''):
        t = self._guess_type(d, vendor=vendor)
        return {'switch':'switch','router':'router','server':'server',
                'access_point':'wifi','firewall':'shield','printer':'printer'}.get(t,'device')
