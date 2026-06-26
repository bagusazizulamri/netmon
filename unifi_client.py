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

    def get_clients(self):
        data = self._api(f'/api/s/{self.site}/stat/sta')
        if data:
            return data.get('data', [])
        return []


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
        }
