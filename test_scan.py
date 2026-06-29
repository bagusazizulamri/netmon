import sys
import os
import ipaddress
import time

from database import Database
from snmp_worker import SNMPWorker

class DummySocketIO:
    def emit(self, event, data):
        print(f"[Socket.IO] {event}: {data}")

def main():
    db = Database()
    sio = DummySocketIO()
    worker = SNMPWorker(db, sio)
    
    # Run scan on local subnet
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = '127.0.0.1'
    finally:
        s.close()
        
    print(f"Local IP detected: {local_ip}")
    net_str = str(ipaddress.ip_network(f"{local_ip}/24", strict=False))
    
    print("\nStarting ICMP scan...")
    worker.scan_network(net_str, method='icmp')

if __name__ == '__main__':
    main()
