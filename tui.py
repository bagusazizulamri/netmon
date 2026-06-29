#!/usr/bin/env python3
"""
NetMon - Text User Interface (TUI)
Fallback console interface to manage devices, alerts, and scans when Web UI is offline.
"""

import os
import sys
import time
import threading
from datetime import datetime

# Add current dir to path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from database import Database
    from snmp_worker import SNMPWorker
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please run this script from the NetMon root directory.")
    sys.exit(1)

# Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_RED = "\033[31m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_BLUE = "\033[34m"
C_MAGENTA = "\033[35m"
C_CYAN = "\033[36m"
C_WHITE = "\033[37m"
C_BG_CARD = "\033[48;5;235m"

# Dummy Socket.IO class to satisfy SNMPWorker
class DummySocketIO:
    def emit(self, event, data=None, *args, **kwargs):
        # Silence events in CLI
        pass


def format_bandwidth(bps):
    if bps is None or str(bps).strip() == '' or float(bps) < 0:
        return '—'
    val = float(bps)
    if val == 0:
        return '0 bps'
        
    comma_formatted = f"{int(val):,}".replace(',', '.')
    
    if val >= 1000000000:
        num_str = f"{val / 1000000000:.2f}".replace('.', ',')
        return f"{num_str} Gbps ({comma_formatted} bps)"
    if val >= 1000000:
        num_str = f"{val / 1000000:.2f}".replace('.', ',')
        return f"{num_str} Mbps ({comma_formatted} bps)"
    if val >= 1000:
        num_str = f"{val / 1000:.2f}".replace('.', ',')
        return f"{num_str} Kbps ({comma_formatted} bps)"
    return f"{int(val)} bps"


def format_percent(val):
    if val is None or str(val).strip() == '':
        return '—'
    try:
        num = float(val)
        return f"{num:.1f}%".replace('.', ',')
    except (ValueError, TypeError):
        return str(val)


def format_temp(val):
    if val is None or str(val).strip() == '':
        return '—'
    try:
        num = float(val)
        return f"{num:.1f}°C".replace('.', ',')
    except (ValueError, TypeError):
        return str(val)


class NetMonTUI:
    def __init__(self):
        # Enable ANSI colors on Windows Console
        if sys.platform == 'win32':
            os.system('')
        self.db = Database()
        self.socketio = DummySocketIO()
        self.worker = SNMPWorker(self.db, self.socketio)
        self.running = True
        # Start background polling thread to monitor devices in real-time
        self.poll_thread = threading.Thread(target=self._background_poll_loop, daemon=True)
        self.poll_thread.start()

    def _is_web_ui_active(self):
        import socket
        port = int(os.environ.get('PORT', 5000))
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except Exception:
            return False

    def _background_poll_loop(self):
        while self.running:
            try:
                # If Web UI is active, let Web UI do the polling.
                # TUI will run passively to avoid SQLite locks and double polling.
                if self._is_web_ui_active():
                    time.sleep(5)
                    continue

                settings = self.db.get_settings()
                interval = max(10, int(settings.get('poll_interval', 30)))

                # UniFi telemetry poller fallback if web UI is offline
                host = settings.get('unifi_host', '')
                username = settings.get('unifi_user', '')
                password = settings.get('unifi_pass', '')
                port = int(settings.get('unifi_port', 8443) or 8443)
                site = settings.get('unifi_site', 'default') or 'default'

                if host and username and password:
                    try:
                        from unifi_client import UniFiClient
                        unifi = UniFiClient(host=host, username=username, password=password, port=port, site=site)
                        unifi_devs = unifi.get_devices()
                        for ud in unifi_devs:
                            self.db.add_or_update_unifi_device(ud)
                    except Exception:
                        pass

                devices = self.db.get_all_devices()
                for device in devices:
                    if not self.running or self._is_web_ui_active():
                        break
                    try:
                        self.worker.poll_device(device)
                    except Exception:
                        pass
                # Sleep in small increments to respond quickly to shutdown
                for _ in range(interval):
                    if not self.running or self._is_web_ui_active():
                        break
                    time.sleep(1)
            except Exception:
                time.sleep(10)

    def clear_screen(self):
        print("\033[H\033[2J", end="")

    def print_header(self, title):
        self.clear_screen()
        print(f"{C_BOLD}{C_CYAN}======================================================================{C_RESET}")
        print(f"{C_BOLD}{C_CYAN}  🌐 NETMON TUI CONSOLE — {title.upper()}{C_RESET}")
        print(f"{C_BOLD}{C_CYAN}======================================================================{C_RESET}")
        print(f" Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | DB Path: {self.db.db_path}\n")

    def get_status_color(self, status):
        status = (status or "").lower()
        if status == "up":
            return C_GREEN
        elif status == "down":
            return C_RED
        elif status == "warning":
            return C_YELLOW
        return C_WHITE

    def run(self):
        while self.running:
            try:
                self.show_dashboard()
            except KeyboardInterrupt:
                self.quit()
            except Exception as e:
                input(f"\n{C_RED}Error: {e}{C_RESET}\nTekan Enter untuk melanjutkan...")

    def show_dashboard(self):
        self.print_header("Dashboard")
        
        # Load stats
        stats = self.db.get_dashboard_stats()
        
        # Print summary cards
        print(f" STATUS PERANGKAT:")
        print(f" ┌──────────────┬──────────────┬──────────────┬──────────────┐")
        print(f" │ {C_GREEN}ONLINE (Up){C_RESET}  │ {C_RED}OFFLINE (Dn){C_RESET} │ {C_YELLOW}WARNING (Wg){C_RESET} │ {C_WHITE}UNKNOWN (Un){C_RESET} │")
        print(f" ├──────────────┼──────────────┼──────────────┼──────────────┤")
        print(f" │      {stats.get('up', 0):<8}│      {stats.get('down', 0):<8}│      {stats.get('warning', 0):<8}│      {stats.get('unknown', 0):<8}│")
        print(f" └──────────────┴──────────────┴──────────────┴──────────────┘")
        
        # Alert Summary
        unacked = stats.get('unacked_alerts', 0)
        alert_color = C_RED if unacked > 0 else C_GREEN
        print(f" Peringatan Aktif: {alert_color}{C_BOLD}{unacked} belum di-acknowledge{C_RESET}\n")

        # Top menu options
        print(f" {C_BOLD}MENU UTAMA:{C_RESET}")
        print(f" {C_CYAN}[1]{C_RESET} Lihat & Poll Perangkat")
        print(f" {C_CYAN}[2]{C_RESET} Lihat & Acknowledge Peringatan (Alerts)")
        print(f" {C_CYAN}[3]{C_RESET} Mulai Pemindaian Jaringan (Network Scan)")
        print(f" {C_CYAN}[4]{C_RESET} Lihat Log Aktivitas Pengguna (Access Logs)")
        print(f" {C_CYAN}[5]{C_RESET} Pengaturan Dasar (Settings)")
        print(f" {C_CYAN}[r]{C_RESET} Refresh Tampilan")
        print(f" {C_CYAN}[q]{C_RESET} Keluar (Quit)")
        
        choice = input(f"\n{C_BOLD}Pilih opsi (1-5/r/q): {C_RESET}").strip().lower()
        
        if choice == '1':
            self.manage_devices()
        elif choice == '2':
            self.manage_alerts()
        elif choice == '3':
            self.run_network_scan()
        elif choice == '4':
            self.view_access_logs()
        elif choice == '5':
            self.view_settings()
        elif choice == 'r':
            pass
        elif choice == 'q':
            self.quit()

    def manage_devices(self):
        while True:
            self.print_header("Daftar Perangkat")
            devices = self.db.get_all_devices()
            
            if not devices:
                print(" Tidak ada perangkat yang terdaftar.")
            else:
                # Table header
                print(f" {C_BOLD}{'No':<3} | {'Status':<7} | {'Nama Perangkat':<22} | {'IP Address':<15} | {'SNMP':<4} | {'Uptime':<15}{C_RESET}")
                print(" " + "-" * 75)
                
                for idx, d in enumerate(devices, 1):
                    color = self.get_status_color(d.get('status'))
                    snmp_lbl = "ON" if d.get('snmp_enabled') else "OFF"
                    uptime = d.get('uptime') or '—'
                    if len(uptime) > 15:
                        uptime = uptime[:12] + "..."
                    
                    status_lbl = d.get('status', 'unknown').upper()
                    print(f" {idx:<3} | {color}{status_lbl:<7}{C_RESET} | {d.get('name') or 'Unknown':<22} | {d.get('ip'):<15} | {snmp_lbl:<4} | {uptime:<15}")
            
            print("\n OPSI:")
            print(f" {C_CYAN}[no]{C_RESET} Ketik nomor perangkat untuk detail & kueri SNMP (Poll)")
            print(f" {C_CYAN}[a]{C_RESET}  Tambah perangkat baru")
            print(f" {C_CYAN}[b]{C_RESET}  Kembali ke Menu Utama")
            
            act = input(f"\n{C_BOLD}Masukkan opsi: {C_RESET}").strip().lower()
            if act == 'b':
                break
            elif act == 'a':
                self.add_new_device()
            elif act.isdigit():
                val = int(act)
                if 1 <= val <= len(devices):
                    self.device_detail(devices[val-1])
                else:
                    input("Nomor tidak valid. Tekan Enter...")

    def device_detail(self, dev):
        while True:
            self.print_header(f"Detail: {dev.get('name')}")
            color = self.get_status_color(dev.get('status'))
            
            print(f" ID Database:  {dev.get('id')}")
            print(f" Nama:         {dev.get('name')}")
            print(f" Alamat IP:    {dev.get('ip')}")
            print(f" Alamat MAC:   {dev.get('mac') or '—'}")
            print(f" Tipe Perangkat: {dev.get('type')}")
            print(f" Vendor/Model: {dev.get('vendor') or '—'} / {dev.get('model') or '—'}")
            print(f" Status:       {color}{C_BOLD}{dev.get('status', 'unknown').upper()}{C_RESET}")
            print(f" Uptime:       {dev.get('uptime') or '—'}")
            print(f" Deskripsi:    {dev.get('description') or '—'}")
            print(f" Terakhir Poll:{dev.get('last_polled') or '—'}")
            # Print metrics
            cpu_usage = dev.get('cpu_usage')
            mem_usage = dev.get('memory_usage')
            temperature = dev.get('temperature')
            wan_in = dev.get('wan_in')
            wan_out = dev.get('wan_out')
            
            print("-" * 50)
            print(f" {C_BOLD}METRIK REAL-TIME:{C_RESET}")
            print(f" CPU Usage:    {C_CYAN}{format_percent(cpu_usage)}{C_RESET}")
            print(f" RAM Usage:    {C_CYAN}{format_percent(mem_usage)}{C_RESET}")
            print(f" Temperature:  {C_RED}{format_temp(temperature)}{C_RESET}")
            print(f" WAN Traffic In:  {C_GREEN}{format_bandwidth(wan_in)}{C_RESET}")
            print(f" WAN Traffic Out: {C_GREEN}{format_bandwidth(wan_out)}{C_RESET}")
            print("-" * 50)
            print(f" SNMP Status:  {'AKTIF' if dev.get('snmp_enabled') else 'MATI'}")
            if dev.get('snmp_enabled'):
                print(f" Community:    {dev.get('snmp_community')}")
                print(f" SNMP Port:    {dev.get('snmp_port')}")
                print(f" SNMP Version: {dev.get('snmp_version')}")

            print("\n OPSI:")
            print(f" {C_CYAN}[p]{C_RESET} Poll SNMP Sekarang (Force Poll)")
            print(f" {C_CYAN}[d]{C_RESET} Hapus Perangkat")
            print(f" {C_CYAN}[b]{C_RESET} Kembali ke daftar perangkat")
            
            act = input(f"\n{C_BOLD}Masukkan opsi: {C_RESET}").strip().lower()
            if act == 'b':
                break
            elif act == 'p':
                print(f"\n Melakukan kueri SNMP ke {dev.get('ip')}...")
                # Run polling in foreground
                self.worker.poll_device(dev)
                # Reload dev from DB
                updated_dev = self.db.get_device(dev['id'])
                if updated_dev:
                    dev = updated_dev
                input("\n Polling selesai. Tekan Enter untuk melihat pembaruan...")
            elif act == 'd':
                confirm = input(f" Apakah Anda yakin ingin menghapus {dev.get('name')}? (y/N): ").strip().lower()
                if confirm == 'y':
                    self.db.delete_device(dev['id'])
                    input(" Perangkat berhasil dihapus. Tekan Enter...")
                    break

    def add_new_device(self):
        self.print_header("Tambah Perangkat Baru")
        ip = input(" Masukkan Alamat IP (Wajib): ").strip()
        if not ip:
            input(" IP tidak boleh kosong! Tekan Enter...")
            return
        
        name = input(" Masukkan Nama Perangkat: ").strip() or ip
        mac = input(" Masukkan Alamat MAC (Opsional): ").strip()
        dtype = input(" Tipe (router/switch/access_point/server/unknown): ").strip() or "unknown"
        
        snmp_en = input(" Aktifkan SNMP? (y/N): ").strip().lower() == 'y'
        community = 'public'
        version = '2c'
        port = 161
        
        if snmp_en:
            community = input(" SNMP Community String (Default 'public'): ").strip() or 'public'
            version = input(" SNMP Version (1/2c, Default '2c'): ").strip() or '2c'
            port_in = input(" SNMP Port (Default 161): ").strip()
            port = int(port_in) if port_in.isdigit() else 161

        data = {
            'name': name,
            'ip': ip,
            'mac': mac,
            'type': dtype,
            'snmp_enabled': snmp_en,
            'snmp_community': community,
            'snmp_version': version,
            'snmp_port': port,
            'status': 'unknown'
        }
        
        try:
            dev_id = self.db.add_device(data)
            input(f" Perangkat berhasil ditambahkan (ID: {dev_id}). Tekan Enter...")
        except Exception as e:
            if "UNIQUE" in str(e):
                input(f" Gagal: Alamat IP '{ip}' sudah terdaftar! Tekan Enter...")
            else:
                input(f" Gagal menambahkan perangkat: {e}. Tekan Enter...")

    def manage_alerts(self):
        while True:
            self.print_header("Log Peringatan (Alerts)")
            alerts = self.db.get_alerts(limit=30)
            
            if not alerts:
                print(" Tidak ada peringatan terekam.")
            else:
                print(f" {C_BOLD}{'No':<3} | {'Severity':<8} | {'Perangkat':<15} | {'Pesan':<35} | {'Status':<6}{C_RESET}")
                print(" " + "-" * 75)
                for idx, a in enumerate(alerts, 1):
                    sev = (a.get('severity') or 'info').upper()
                    sev_color = C_RED if sev == 'CRITICAL' else (C_YELLOW if sev == 'WARNING' else C_WHITE)
                    status_lbl = "ACK" if a.get('acknowledged') else "OPEN"
                    status_color = C_GREEN if a.get('acknowledged') else C_RED
                    
                    print(f" {idx:<3} | {sev_color}{sev:<8}{C_RESET} | {a.get('device_name') or a.get('device_ip', '—'):<15} | {a.get('message')[:33]:<35} | {status_color}{status_lbl:<6}{C_RESET}")

            print("\n OPSI:")
            print(f" {C_CYAN}[ack all]{C_RESET} Acknowledge semua peringatan aktif")
            print(f" {C_CYAN}[no]{C_RESET}      Ketik nomor baris untuk Acknowledge spesifik")
            print(f" {C_CYAN}[b]{C_RESET}       Kembali ke Menu Utama")
            
            act = input(f"\n{C_BOLD}Masukkan opsi: {C_RESET}").strip().lower()
            if act == 'b':
                break
            elif act == 'ack all':
                self.db.acknowledge_all_alerts()
                input(" Semua peringatan berhasil di-acknowledge. Tekan Enter...")
            elif act.isdigit():
                val = int(act)
                if 1 <= val <= len(alerts):
                    a = alerts[val-1]
                    if a.get('acknowledged'):
                        input(" Peringatan ini sudah di-acknowledge sebelumnya. Tekan Enter...")
                    else:
                        self.db.acknowledge_alert(a['id'], 'admin-cli')
                        input(" Peringatan berhasil di-acknowledge. Tekan Enter...")
                else:
                    input(" Nomor tidak valid. Tekan Enter...")

    def run_network_scan(self):
        self.print_header("Network Discovery Scan")
        net = input(" Masukkan subnet CIDR (contoh: 192.168.1.0/24): ").strip()
        if not net:
            input(" Subnet tidak boleh kosong! Tekan Enter...")
            return
        
        community = input(" SNMP Community String (Default 'public'): ").strip() or 'public'
        version = input(" SNMP Version (1/2c, Default '2c'): ").strip() or '2c'
        
        print(f"\n Memulai pemindaian pada {net}...")
        print(" Mohon tunggu, proses ini memakan waktu tergantung ukuran subnet...")
        
        # Show simple loading in background
        stop_loader = threading.Event()
        def loader():
            while not stop_loader.is_set():
                status = self.worker.get_scan_status()
                if status.get('running'):
                    print(f"\r Progress: {status.get('progress')}/{status.get('total')} IP ({status.get('percent')}%) | Ditemukan: {status.get('found')} perangkat | IP Aktif: {status.get('current_ip')}", end="", flush=True)
                time.sleep(0.5)
            print()
            
        t = threading.Thread(target=self.worker.scan_network, args=(net, community, version))
        self.worker._scan_future = t
        t.start()
        
        lt = threading.Thread(target=loader)
        lt.start()
        
        try:
            while t.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n Membatalkan pemindaian...")
            self.worker.stop_scan()
        
        stop_loader.set()
        lt.join()
        t.join()
        
        input("\n Pemindaian selesai. Tekan Enter untuk melanjutkan...")

    def view_access_logs(self):
        self.print_header("Log Audit Aktivitas")
        logs = self.db.get_access_logs(limit=30)
        
        if not logs:
            print(" Tidak ada log akses terekam.")
        else:
            print(f" {C_BOLD}{'Waktu':<19} | {'Sumber':<15} | {'Jenis':<6} | {'Pesan':<30}{C_RESET}")
            print(" " + "-" * 75)
            for l in logs:
                t_str = l.get('created_at', '')
                t_formatted = t_str.split('.')[0] if '.' in t_str else t_str
                print(f" {t_formatted:<19} | {l.get('source'):<15} | {l.get('type','info').upper():<6} | {l.get('message')}")
        
        input("\n Tekan Enter untuk kembali ke Menu Utama...")

    def view_settings(self):
        self.print_header("Pengaturan Aplikasi")
        s = self.db.get_settings()
        
        print(f" Interval Polling:          {s.get('poll_interval')} detik")
        print(f" Aksi Peringatan Down:      {s.get('alert_on_down')}")
        print(f" Aksi Peringatan Pemulihan:  {s.get('alert_on_up')}")
        print(f" Default SNMP Community:    {s.get('default_community')}")
        print(f" Default SNMP Version:      {s.get('default_snmp_version')}")
        print("-" * 50)
        print(f" UniFi Host Controller:     {s.get('unifi_host') or '(Tidak Diatur)'}")
        print(f" UniFi Port / Site:         {s.get('unifi_port')} / {s.get('unifi_site')}")
        print(f" UniFi User:                {s.get('unifi_user') or '(Tidak Diatur)'}")
        print(f" Retensi Log Audit:         {s.get('log_retention_days')} hari")
        print(f" Retensi Data Alert:        {s.get('alert_retention_days')} hari")
        
        input("\n Tekan Enter untuk kembali ke Menu Utama...")

    def quit(self):
        self.running = False
        self.clear_screen()
        print("\n Keluar dari NetMon TUI. Terima kasih!\n")
        sys.exit(0)

if __name__ == "__main__":
    # Ensure terminal is reset when exiting
    tui = NetMonTUI()
    tui.run()
