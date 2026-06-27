#!/usr/bin/env python3
"""
NetMon - UniFi Controller Client
Supports classic controller (port 8443) and UniFi OS
"""

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TYPE_MAP = {
    'ugw': 'router',    'uxg': 'router',  'udm': 'router',  'usg': 'router',
    'usw': 'switch',    'uss': 'switch',
    'uap': 'access_point',
    'upd': 'server',
}


def format_uptime(seconds):
    if seconds is None or str(seconds).strip() == '':
        return ''
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return str(seconds)
    
    days = seconds // 86400
    seconds %= 86400
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
        
    return " ".join(parts)


class UniFiClient:
    def __init__(self, host, username, password, port=8443, site='default'):
        self.base    = f'https://{host}:{port}'
        self.user    = username
        self.pw      = password
        self.site    = site
        self.session = requests.Session()
        self.session.verify = False
        self.logged_in = False

    # --------------------------------------------------------
    # Auth
    # --------------------------------------------------------

    def login(self):
        # Try classic controller API
        for path in ['/api/login', '/api/auth/login']:
            try:
                r = self.session.post(
                    f'{self.base}{path}',
                    json={'username': self.user, 'password': self.pw},
                    timeout=10
                )
                if r.status_code == 200:
                    body = r.json()
                    # Classic: meta.rc == 'ok'  |  UniFiOS: no meta key
                    if body.get('meta', {}).get('rc') == 'ok' or 'data' in body or r.status_code == 200:
                        # Extract x-csrf-token for UniFi OS compatibility
                        csrf_token = r.headers.get('x-csrf-token')
                        if csrf_token:
                            self.session.headers.update({'x-csrf-token': csrf_token})
                        self.logged_in = True
                        return True
            except Exception as e:
                print(f"[UniFi] Login attempt {path} failed: {e}")
        return False

    def _api(self, path):
        if not self.logged_in and not self.login():
            raise RuntimeError("Login ke UniFi Controller gagal. Periksa Username/Password.")
        
        errors = []
        # Try direct path (Classic) and proxy path (UniFi OS)
        for prefix in ['', '/proxy/network']:
            try:
                url = f'{self.base}{prefix}{path}'
                r = self.session.get(url, timeout=10)
                if r.status_code == 200:
                    body = r.json()
                    # Check if UniFi returned an internal API error payload
                    if body.get('meta', {}).get('rc') == 'error':
                        err_msg = body.get('meta', {}).get('msg', 'Unknown error')
                        if 'InvalidSite' in err_msg or 'NotFound' in err_msg or 'site' in err_msg.lower():
                            err_msg = f"{err_msg} (Nama Site salah. Gunakan Site ID dari URL UniFi, bukan nama tampilan/display name. Contoh: 'default' atau string acak di URL browser)"
                        raise RuntimeError(err_msg)
                    return body
                else:
                    errors.append(f"HTTP {r.status_code} pada {prefix}{path}")
            except Exception as e:
                if isinstance(e, RuntimeError):
                    raise
                errors.append(f"{prefix}{path} gagal: {e}")
        
        raise RuntimeError(f"Gagal memanggil API UniFi: {'; '.join(errors)}")

    # --------------------------------------------------------
    # Data fetchers
    # --------------------------------------------------------

    def get_devices(self):
        data = self._api(f'/api/s/{self.site}/stat/device')
        if data:
            devices = [self._parse_device(d) for d in data.get('data', [])]
            return [d for d in devices if d.get('ip') and str(d.get('ip')).strip()]
        return []

    def get_device_details(self, ip_or_mac):
        data = self._api(f'/api/s/{self.site}/stat/device')
        if not data:
            return None
        
        target = None
        for d in data.get('data', []):
            if d.get('ip') == ip_or_mac or d.get('mac') == ip_or_mac or d.get('_id') == ip_or_mac:
                target = d
                break
                
        if not target:
            return None
            
        parsed = self._parse_device(target)
        
        interfaces = []
        port_table = target.get('port_table', [])
        for p in port_table:
            idx = p.get('port_idx', 1)
            name = p.get('name') or f"Port {idx}"
            speed_mbps = p.get('speed', 0)
            status = 'up' if p.get('up') else 'down'
            rx_bytes = p.get('rx_bytes', 0) or p.get('rx_bytes-r', 0)
            tx_bytes = p.get('tx_bytes', 0) or p.get('tx_bytes-r', 0)
            
            interfaces.append({
                'index': idx,
                'name': name,
                'status': status,
                'speed': float(speed_mbps) * 1000000,
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes
            })
            
        # Fallback for devices without a port table (like APs) to show active bandwidth
        if not interfaces:
            vap_rx = 0
            vap_tx = 0
            for vap in target.get('vap_table', []):
                vap_rx += vap.get('rx_bytes', 0)
                vap_tx += vap.get('tx_bytes', 0)
                
            uplink = target.get('uplink', {})
            rx_val = uplink.get('rx_bytes') or target.get('rx_bytes', 0)
            tx_val = uplink.get('tx_bytes') or target.get('tx_bytes', 0)
            
            final_rx = max(vap_rx, rx_val)
            final_tx = max(vap_tx, tx_val)
            
            interfaces.append({
                'index': 1,
                'name': 'Global Traffic',
                'status': 'up',
                'speed': 1000000000.0, # 1 Gbps virtual
                'rx_bytes': final_rx,
                'tx_bytes': final_tx
            })
            
        parsed['interfaces'] = interfaces
        return parsed

    def get_clients(self):
        data = self._api(f'/api/s/{self.site}/stat/sta')
        if data:
            return data.get('data', [])
        return []



    # --------------------------------------------------------
    # Parsers
    # --------------------------------------------------------

    def _parse_device(self, d):
        utype = d.get('type', 'unknown').lower()
        
        # Parse CPU, Memory and Temperature from UniFi telemetry
        sys_stats = d.get('sys_stats', {})
        system_status = d.get('system-status', {})
        cpu = sys_stats.get('cpu') or system_status.get('cpu')
        mem = sys_stats.get('mem') or system_status.get('mem')
        temp = d.get('general_temperature') or d.get('temperatures', [{}])[0].get('value')

        # WAN throughput for UniFi Routers (USG/UDM/UXG)
        wan_in = None
        wan_out = None
        if utype in ('ugw', 'uxg', 'udm', 'usg') or TYPE_MAP.get(utype) == 'router':
            # Throughput is usually bytes per second (r = rate)
            wan_stats = d.get('wan1', {}) or d.get('stat', {}).get('gw', {})
            wan_tx = wan_stats.get('tx_bytes-r') or d.get('uplink', {}).get('tx_bytes-r')
            wan_rx = wan_stats.get('rx_bytes-r') or d.get('uplink', {}).get('rx_bytes-r')
            if wan_rx is not None:
                try:
                    wan_in = float(wan_rx) * 8 # Convert bytes/sec to bps
                except ValueError:
                    pass
            if wan_tx is not None:
                try:
                    wan_out = float(wan_tx) * 8 # Convert bytes/sec to bps
                except ValueError:
                    pass

        return {
            'name':         d.get('name') or d.get('hostname') or d.get('ip', 'Unknown'),
            'ip':           d.get('ip', ''),
            'mac':          d.get('mac', ''),
            'model':        d.get('model', ''),
            'vendor':       'Ubiquiti',
            'type':         TYPE_MAP.get(utype, 'unknown'),
            'unifi_id':     d.get('_id', ''),
            'status':       'up' if d.get('state') == 1 else 'down',
            'uptime':       format_uptime(d.get('uptime', '')),
            'icon':         TYPE_MAP.get(utype, 'device'),
            'cpu_usage':    float(cpu) if cpu is not None else None,
            'memory_usage': float(mem) if mem is not None else None,
            'temperature':  float(temp) if temp is not None else None,
            'wan_in':       wan_in,
            'wan_out':      wan_out,
        }
