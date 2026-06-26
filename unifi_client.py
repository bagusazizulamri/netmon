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
            return None
        # Try direct path (Classic) and proxy path (UniFi OS)
        for prefix in ['', '/proxy/network']:
            try:
                url = f'{self.base}{prefix}{path}'
                r = self.session.get(url, timeout=10)
                if r.status_code == 200:
                    return r.json()
            except Exception as e:
                print(f"[UniFi] API error with prefix '{prefix}' on {path}: {e}")
        return None

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


    # --------------------------------------------------------
    # Parsers
    # --------------------------------------------------------

    def _parse_device(self, d):
        utype = d.get('type', 'unknown').lower()
        return {
            'name':      d.get('name') or d.get('hostname') or d.get('ip', 'Unknown'),
            'ip':        d.get('ip', ''),
            'mac':       d.get('mac', ''),
            'model':     d.get('model', ''),
            'vendor':    'Ubiquiti',
            'type':      TYPE_MAP.get(utype, 'unknown'),
            'unifi_id':  d.get('_id', ''),
            'status':    'up' if d.get('state') == 1 else 'down',
            'uptime':    str(d.get('uptime', '')),
            'icon':      TYPE_MAP.get(utype, 'device'),
        }
