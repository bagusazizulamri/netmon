import os
import sys
import time
import ipaddress
import threading
from datetime import datetime

# Configure DB to use an in-memory SQLite database for testing
os.environ['DB_PATH'] = ':memory:'

from database import Database
from snmp_worker import SNMPWorker

class MockSocketIO:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def emit(self, event, data):
        with self.lock:
            self.events.append((event, data))

def run_simulation(host_count):
    print(f"\n==================================================")
    print(f" Simulating Scan Workload: {host_count} Hosts")
    print(f"==================================================")
    
    db = Database()
    sio = MockSocketIO()
    worker = SNMPWorker(db, sio)
    
    # Generate CIDR based on host_count
    # 10 hosts -> /28 (14 hosts)
    # 50 hosts -> /26 (62 hosts)
    # 100 hosts -> /25 (126 hosts)
    # 254 hosts -> /24 (254 hosts)
    # 500 hosts -> /23 (510 hosts)
    # 1000 hosts -> /22 (1022 hosts)
    if host_count <= 14:
        cidr = "192.168.1.0/28"
    elif host_count <= 62:
        cidr = "192.168.1.0/26"
    elif host_count <= 126:
        cidr = "192.168.1.0/25"
    elif host_count <= 254:
        cidr = "192.168.1.0/24"
    elif host_count <= 510:
        cidr = "192.168.1.0/23"
    else:
        cidr = "192.168.0.0/22"

    # Mocks to simulate ping & SNMP requests with minor latency
    def mock_ping(ip, timeout=1.5):
        # Pretend every 3rd host is alive
        last_octet = int(ip.split('.')[-1])
        return (last_octet % 3) == 0

    def mock_get(ip, community, oids, port=161, version='2c', timeout=2.0, retries=1):
        # Simulate small network latency (e.g., 5ms)
        time.sleep(0.005)
        last_octet = int(ip.split('.')[-1])
        # Return SNMP response for even octets
        if last_octet % 2 == 0:
            return {
                '1.3.6.1.2.1.1.5.0': f'device-{ip}',
                '1.3.6.1.2.1.1.1.0': f'Simulated Device {ip} (Vendor: RouterOS)',
                '1.3.6.1.2.1.1.2.0': '1.3.6.1.4.1.14988.1.1.3' # MikroTik sysObjectID
            }
        return None

    # Apply mocks to worker
    worker._ping = mock_ping
    worker._get = mock_get
    
    start_time = time.time()
    
    # Run network scan
    # Note: We run it synchronously on this main thread, which tests its ThreadPoolExecutor
    worker.scan_network(cidr, method='snmp')
    
    duration = time.time() - start_time
    
    # Validate final state
    status = worker.get_scan_status()
    print(f" Completed in {duration:.2f} seconds.")
    print(f" Status running: {status.get('running')}")
    print(f" Progress: {status.get('progress')}/{status.get('total')}")
    print(f" Devices found: {status.get('found')}")
    print(f" Message: {status.get('message')}")
    
    # Collect emitted events metrics
    events_count = {}
    for ev, data in sio.events:
        events_count[ev] = events_count.get(ev, 0) + 1
        
    print(f" Emitted socket events: {events_count}")
    
    # Check for thread leaks
    active_threads = threading.enumerate()
    print(f" Active threads: {len(active_threads)}")
    for t in active_threads[:10]:
        print(f"  - {t.name} (daemon={t.daemon})")
    if len(active_threads) > 10:
        print(f"  - ... and {len(active_threads) - 10} more")
        
    # Check database content
    devices = db.get_all_devices()
    print(f" Devices in DB: {len(devices)}")
    
    # Clean up worker event loop thread
    worker.shutdown()
    
    # Assertions
    assert status.get('running') is False, "Scan should mark running as False on completion"
    assert status.get('total') > 0, "Total hosts scanned should be greater than 0"
    assert status.get('progress') == status.get('total'), "Progress count should match total hosts"
    print(f" SUCCESS: Scan workload completed correctly!")

def main():
    print("Starting simulated scans for all workloads...")
    workloads = [10, 50, 100, 254, 500, 1000]
    for wl in workloads:
        run_simulation(wl)
    print("\nAll workload simulations passed successfully!")

if __name__ == '__main__':
    main()
