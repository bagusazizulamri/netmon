#!/usr/bin/env python3
"""
NetMon - Text User Interface (TUI)
btop-inspired interactive console interface with real-time network traffic graphs.
"""

import os
import sys
import time
import threading
import atexit
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

# --- Colors (ANSI 256-color palette) ---
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_UNDERLINE = "\033[4m"

C_HEADER = "\033[38;5;81m"        # Cyan-blue
C_BORDER = "\033[38;5;242m"        # Dark grey
C_BORDER_ACTIVE = "\033[38;5;81m" # Active panel border (bright cyan)
C_GREEN = "\033[38;5;46m"         # Green for UP
C_RED = "\033[38;5;196m"          # Red for DOWN / Alerts
C_YELLOW = "\033[38;5;220m"       # Yellow for Warning / Polling
C_CYAN = "\033[38;5;51m"          # Cyan for RX Graph
C_MAGENTA = "\033[38;5;165m"       # Magenta for TX Graph
C_WHITE = "\033[38;5;15m"         # White
C_GRAY = "\033[38;5;244m"          # Grey
C_BG_SELECT = "\033[48;5;238m"     # Dark grey background for active list item
C_BG_CARD = "\033[48;5;235m"       # Background card

# --- Cross-platform non-blocking keypress reader ---
if sys.platform == 'win32':
    import msvcrt
    def init_terminal():
        os.system('')  # Enable ANSI escape sequences on Windows
        sys.stdout.write("\033[?1049h\033[?25l") # Alt buffer & hide cursor
        sys.stdout.flush()

    def cleanup_terminal():
        sys.stdout.write("\033[?25h\033[?1049l") # Show cursor & restore buffer
        sys.stdout.flush()

    def get_key_non_blocking():
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):  # Arrow key prefix
                ch2 = msvcrt.getch()
                if ch2 == b'H': return 'arrow_up'
                if ch2 == b'P': return 'arrow_down'
                if ch2 == b'M': return 'arrow_right'
                if ch2 == b'K': return 'arrow_left'
                return None
            try:
                return ch.decode('utf-8', errors='ignore')
            except Exception:
                return None
        return None
else:
    import termios
    import tty
    import select
    orig_settings = None

    def init_terminal():
        global orig_settings
        orig_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?1049h\033[?25l") # Alt buffer & hide cursor
        sys.stdout.flush()

    def cleanup_terminal():
        global orig_settings
        if orig_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, orig_settings)
        sys.stdout.write("\033[?25h\033[?1049l") # Show cursor & restore buffer
        sys.stdout.flush()

    def get_key_non_blocking():
        dr, dw, de = select.select([sys.stdin], [], [], 0)
        if dr:
            ch = sys.stdin.read(1)
            if ch == '\x1b':  # Escape sequence (e.g. arrow keys)
                dr2, dw2, de2 = select.select([sys.stdin], [], [], 0.05)
                if dr2:
                    ch2 = sys.stdin.read(2)
                    if ch2 == '[A': return 'arrow_up'
                    elif ch2 == '[B': return 'arrow_down'
                    elif ch2 == '[C': return 'arrow_right'
                    elif ch2 == '[D': return 'arrow_left'
                return 'esc'
            return ch
        return None

# Ensure term cleanup on sudden exit
atexit.register(cleanup_terminal)

# Dummy Socket.IO class to satisfy SNMPWorker
class DummySocketIO:
    def emit(self, event, data=None, *args, **kwargs):
        pass


def format_bandwidth(bps):
    if bps is None or str(bps).strip() == '' or float(bps) < 0:
        return '—'
    val = float(bps)
    if val == 0:
        return '0 bps'
    if val >= 1e9:
        return f"{val / 1e9:.2f} Gbps"
    if val >= 1e6:
        return f"{val / 1e6:.2f} Mbps"
    if val >= 1e3:
        return f"{val / 1e3:.2f} Kbps"
    return f"{int(val)} bps"


def format_percent(val):
    if val is None or str(val).strip() == '':
        return '—'
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return str(val)


def format_temp(val):
    if val is None or str(val).strip() == '':
        return '—'
    try:
        return f"{float(val):.1f}°C"
    except (ValueError, TypeError):
        return str(val)


# --- Draw Helpers ---
def draw_str(x, y, text, color=C_RESET):
    sys.stdout.write(f"\033[{y};{x}H{color}{text}{C_RESET}")


def draw_box(x, y, w, h, title="", color=C_BORDER):
    # Draw borders
    draw_str(x, y, "┌" + ("─" * (w - 2)) + "┐", color)
    for i in range(1, h - 1):
        draw_str(x, y + i, "│" + (" " * (w - 2)) + "│", color)
    draw_str(x, y + h - 1, "└" + ("─" * (w - 2)) + "┘", color)
    
    # Draw title
    if title:
        t = title[:w-6]
        draw_str(x + 3, y, f"┤ {C_BOLD}{t}{C_RESET}{color} ├", color)


def render_bars(history, h, w, max_val):
    data = [0.0] * w
    if history:
        hist_w = history[-w:]
        data[-len(hist_w):] = hist_w
    
    rows = []
    for r in range(h - 1, -1, -1):
        row_chars = []
        for val in data:
            scaled = (val / max_val) * h if max_val > 0 else 0.0
            if scaled >= r + 1:
                row_chars.append("█")
            elif scaled >= r + 0.5:
                row_chars.append("▄")
            else:
                row_chars.append(" ")
        rows.append("".join(row_chars))
    return rows


class NetMonTUI:
    def __init__(self):
        self.db = Database()
        self.socketio = DummySocketIO()
        self.worker = SNMPWorker(self.db, self.socketio)
        self.running = True
        
        self.selected_idx = 0
        self.traffic_histories = {}
        self.polling_status = {}
        
        # Start passive polling background thread
        self.poll_thread = threading.Thread(target=self._background_poll_loop, daemon=True)
        self.poll_thread.start()

    def _is_web_ui_active(self):
        import socket
        port = int(os.environ.get('PORT', 5000))
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.2)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except Exception:
            return False

    def _background_poll_loop(self):
        while self.running:
            try:
                # If Web UI is active, let Web UI do the polling to prevent double poll
                if self._is_web_ui_active():
                    time.sleep(5)
                    continue

                settings = self.db.get_settings()
                interval = max(10, int(settings.get('poll_interval', 30)))

                devices = self.db.get_all_devices()
                for device in devices:
                    if not self.running or self._is_web_ui_active():
                        break
                    # Avoid polling selected device if TUI is currently forcing poll
                    if device['id'] in self.polling_status:
                        continue
                    try:
                        self.worker.poll_device(device)
                    except Exception:
                        pass
                
                for _ in range(interval):
                    if not self.running or self._is_web_ui_active():
                        break
                    time.sleep(1)
            except Exception:
                time.sleep(10)

    def clear_screen(self):
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()

    def run(self):
        init_terminal()
        self.clear_screen()
        
        last_render = 0
        while self.running:
            try:
                now = time.time()
                key = get_key_non_blocking()
                
                if key:
                    if key in ('q', 'Q'):
                        break
                    elif key == 'arrow_up':
                        self.selected_idx = max(0, self.selected_idx - 1)
                        last_render = 0 # Force instant redraw
                    elif key == 'arrow_down':
                        self.selected_idx += 1
                        last_render = 0 # Force instant redraw
                    elif key in ('p', 'P'):
                        # Force poll selected device in background thread
                        devices = self.db.get_all_devices()
                        if devices and 0 <= self.selected_idx < len(devices):
                            dev = devices[self.selected_idx]
                            threading.Thread(target=self._force_poll_bg, args=(dev,), daemon=True).start()
                    elif key in ('a', 'A'):
                        self.add_new_device_tui()
                        last_render = 0
                    elif key in ('d', 'D'):
                        self.delete_device_tui()
                        last_render = 0
                    elif key in ('s', 'S'):
                        self.run_network_scan_tui()
                        last_render = 0
                    elif key in ('c', 'C'):
                        self.db.acknowledge_all_alerts()
                        last_render = 0

                if now - last_render >= 1.0:
                    self.render_frame()
                    last_render = now
                
                time.sleep(0.05)
            except KeyboardInterrupt:
                break
            except Exception as e:
                cleanup_terminal()
                self.clear_screen()
                print(f"TUI error: {e}")
                sys.exit(1)
        
        self.quit()

    def _force_poll_bg(self, dev):
        dev_id = dev['id']
        self.polling_status[dev_id] = True
        try:
            self.worker.poll_device(dev)
        except Exception:
            pass
        finally:
            self.polling_status.pop(dev_id, None)

    def render_frame(self):
        try:
            cols, rows = os.get_terminal_size()
        except Exception:
            cols, rows = 80, 24

        if cols < 80 or rows < 22:
            self.clear_screen()
            draw_str(1, 1, f"{C_RED}Terminal size too small ({cols}x{rows}).{C_RESET}")
            draw_str(1, 2, "Please expand terminal to at least 80x24.")
            sys.stdout.flush()
            return

        header_h = 3
        alert_h = 6
        main_h = rows - header_h - alert_h - 1
        devices_w = 44
        graph_w = cols - devices_w - 1

        # Fetch live database records
        stats = self.db.get_dashboard_stats()
        devices = self.db.get_all_devices()
        alerts = self.db.get_alerts(limit=4)

        # 1. --- HEADER PANEL ---
        draw_box(1, 1, cols, header_h, "NETMON MONITOR (btop-style)", C_BORDER)
        
        # Calculate averages for header progress bars
        active_cpus = [d['cpu_usage'] for d in devices if d.get('cpu_usage') is not None]
        avg_cpu = sum(active_cpus) / len(active_cpus) if active_cpus else 0.0
        active_mems = [d['memory_usage'] for d in devices if d.get('memory_usage') is not None]
        avg_mem = sum(active_mems) / len(active_mems) if active_mems else 0.0

        def make_progress_bar(pct, width=8):
            filled = int((pct / 100.0) * width)
            filled = max(0, min(width, filled))
            return "[" + "█" * filled + "░" * (width - filled) + "]"

        cpu_bar = make_progress_bar(avg_cpu)
        mem_bar = make_progress_bar(avg_mem)

        status_summary = f"HOSTS: {C_GREEN}{stats.get('up', 0)} UP{C_RESET} | {C_RED}{stats.get('down', 0)} DN{C_RESET} | {C_YELLOW}{stats.get('warning', 0)} WG{C_RESET}"
        telemetry_summary = f"Avg CPU: {C_CYAN}{cpu_bar} {avg_cpu:.1f}%{C_RESET}  Avg RAM: {C_CYAN}{mem_bar} {avg_mem:.1f}%{C_RESET}"
        draw_str(3, 2, f"{status_summary}   {telemetry_summary}")

        # Header Right (Alert count & Time)
        clock_str = datetime.now().strftime("%H:%M:%S")
        unacked = stats.get('unacked_alerts', 0)
        alerts_lbl = f"ALERTS: {C_RED}{unacked} OPEN{C_RESET}" if unacked > 0 else f"ALERTS: {C_GREEN}0 OK{C_RESET}"
        draw_str(cols - len(clock_str) - 18, 2, f"{alerts_lbl}  │  {clock_str}")

        # 2. --- DEVICES PANEL ---
        draw_box(1, 4, devices_w, main_h, f"Perangkat ({len(devices)})", C_BORDER)
        draw_str(3, 5, f"{C_BOLD}{'NAMA':<16} {'IP ADDRESS':<15} {'STATUS':<6}{C_RESET}")
        draw_str(2, 6, C_BORDER + "─" * (devices_w - 2))

        list_h = main_h - 4
        if devices:
            if self.selected_idx >= len(devices):
                self.selected_idx = len(devices) - 1
            if self.selected_idx < 0:
                self.selected_idx = 0

            # Scroll bounds calculation
            start_row = 0
            if self.selected_idx >= list_h:
                start_row = self.selected_idx - list_h + 1

            visible_devs = devices[start_row : start_row + list_h]
            for i, d in enumerate(visible_devs):
                row_idx = start_row + i
                y_pos = 7 + i

                is_sel = (row_idx == self.selected_idx)
                row_color = C_BG_SELECT if is_sel else ""

                stat = d.get('status', 'unknown').upper()
                stat_color = C_GREEN if stat == 'UP' else (C_RED if stat == 'DOWN' else C_YELLOW)

                name_lbl = d.get('name') or 'Unknown'
                if len(name_lbl) > 16:
                    name_lbl = name_lbl[:13] + "..."

                prefix = "► " if is_sel else "  "
                line = f"{row_color}{prefix}{name_lbl:<16} {d.get('ip'):<15} {stat_color}{stat:<6}{C_RESET}"
                
                # Expand selection background color to full width of cell
                if is_sel:
                    raw_len = len(f"{prefix}{name_lbl:<16} {d.get('ip'):<15} {stat:<6}")
                    line += C_BG_SELECT + (" " * (devices_w - 2 - raw_len)) + C_RESET

                draw_str(2, y_pos, line)
            
            # Clear remaining rows in list panel
            for empty_row in range(len(visible_devs), list_h):
                draw_str(2, 7 + empty_row, " " * (devices_w - 2))
        else:
            draw_str(3, 7, "Tidak ada perangkat terdaftar.", C_GRAY)
            # Clear list panel
            for empty_row in range(1, list_h):
                draw_str(2, 7 + empty_row, " " * (devices_w - 2))

        # 3. --- DETAIL & TRAFFIC GRAPH PANEL ---
        sel_dev = devices[self.selected_idx] if devices else None
        active_border = C_BORDER_ACTIVE if sel_dev else C_BORDER
        draw_box(devices_w + 1, 4, graph_w, main_h, f"Detail & Trafik: {sel_dev['name'] if sel_dev else 'N/A'}", active_border)

        if sel_dev:
            # Details top row
            status_lbl = sel_dev.get('status', 'unknown').upper()
            status_color = C_GREEN if status_lbl == 'UP' else (C_RED if status_lbl == 'DOWN' else C_YELLOW)
            poll_lbl = f"  {C_YELLOW}{C_BOLD}[POLLING...]{C_RESET}" if sel_dev['id'] in self.polling_status else ""
            uptime = sel_dev.get('uptime') or '—'
            if len(uptime) > 22:
                uptime = uptime[:19] + "..."

            draw_str(devices_w + 3, 5, f"Status: {status_color}{C_BOLD}{status_lbl}{C_RESET} │ IP: {sel_dev.get('ip')} │ Uptime: {C_CYAN}{uptime}{C_RESET}{poll_lbl}")

            # Details second row
            cpu_val = sel_dev.get('cpu_usage')
            mem_val = sel_dev.get('memory_usage')
            temp_val = sel_dev.get('temperature')

            cpu_lbl = f"{cpu_val:.1f}%" if cpu_val is not None else "—"
            mem_lbl = f"{mem_val:.1f}%" if mem_val is not None else "—"
            temp_lbl = f"{temp_val:.1f}°C" if temp_val is not None else "—"

            cpu_bar = make_progress_bar(cpu_val or 0.0)
            mem_bar = make_progress_bar(mem_val or 0.0)

            draw_str(devices_w + 3, 6, f"CPU: {C_YELLOW}{cpu_bar} {cpu_lbl:<6}{C_RESET} RAM: {C_YELLOW}{mem_bar} {mem_lbl:<6}{C_RESET} Temp: {C_RED}{temp_lbl}{C_RESET}")
            draw_str(devices_w + 2, 7, C_BORDER + "─" * (graph_w - 2))

            # Split Real-time Bandwidth Graph
            graph_h = main_h - 6  # Rows remaining for graph layout
            if graph_h >= 6:
                rx_h = graph_h // 2
                tx_h = graph_h - rx_h

                dev_id = sel_dev['id']
                if dev_id not in self.traffic_histories:
                    self.traffic_histories[dev_id] = {'rx': [], 'tx': []}

                rx_val = sel_dev.get('wan_in') or 0.0
                tx_val = sel_dev.get('wan_out') or 0.0

                self.traffic_histories[dev_id]['rx'].append(rx_val)
                self.traffic_histories[dev_id]['tx'].append(tx_val)

                # Keep traffic history bound to graph width
                max_history_len = graph_w - 6
                self.traffic_histories[dev_id]['rx'] = self.traffic_histories[dev_id]['rx'][-max_history_len:]
                self.traffic_histories[dev_id]['tx'] = self.traffic_histories[dev_id]['tx'][-max_history_len:]

                rx_hist = self.traffic_histories[dev_id]['rx']
                tx_hist = self.traffic_histories[dev_id]['tx']

                max_rx = max(rx_hist, default=1.0)
                max_tx = max(tx_hist, default=1.0)
                # Avoid division by zero issues, default floor to 10 Kbps
                max_rx = max(max_rx, 10000.0)
                max_tx = max(max_tx, 10000.0)

                # Build bars
                rx_rows = render_bars(rx_hist, rx_h, graph_w - 4, max_rx)
                tx_rows = render_bars(tx_hist, tx_h, graph_w - 4, max_tx)

                # 3a. RX Inbound Graph (Cyan)
                curr_rx_lbl = format_bandwidth(rx_val)
                max_rx_lbl = format_bandwidth(max_rx)
                draw_str(devices_w + 3, 8, f"{C_CYAN}▲ RX: {C_BOLD}{curr_rx_lbl}{C_RESET} {C_GRAY}(Max: {max_rx_lbl}){C_RESET}")
                
                for r_idx, row_str in enumerate(rx_rows):
                    draw_str(devices_w + 3, 9 + r_idx, C_CYAN + row_str + C_RESET)

                # 3b. TX Outbound Graph (Magenta, grows downwards in btop style)
                curr_tx_lbl = format_bandwidth(tx_val)
                max_tx_lbl = format_bandwidth(max_tx)
                
                tx_start_y = 9 + rx_h
                for r_idx, row_str in enumerate(tx_rows):
                    # Inverted rows logic so it flows down
                    draw_str(devices_w + 3, tx_start_y + r_idx, C_MAGENTA + tx_rows[len(tx_rows) - 1 - r_idx] + C_RESET)
                
                draw_str(devices_w + 3, tx_start_y + tx_h, f"{C_MAGENTA}▼ TX: {C_BOLD}{curr_tx_lbl}{C_RESET} {C_GRAY}(Max: {max_tx_lbl}){C_RESET}")
            else:
                # Graph area is too short
                draw_str(devices_w + 3, 8, "Graph area is too compressed.", C_GRAY)
                for empty_row in range(9, main_h + 3):
                    draw_str(devices_w + 3, empty_row, " " * (graph_w - 4))
        else:
            # No device selected
            draw_str(devices_w + 3, 8, "Perangkat tidak terdaftar.", C_GRAY)
            for empty_row in range(9, main_h + 3):
                draw_str(devices_w + 3, empty_row, " " * (graph_w - 4))

        # 4. --- ALERTS LOG PANEL ---
        alert_y = 4 + main_h
        draw_box(1, alert_y, cols, alert_h, "Peringatan Terbaru (Alerts)", C_BORDER)
        
        if alerts:
            for idx, a in enumerate(alerts[:alert_h - 2]):
                sev = (a.get('severity') or 'info').upper()
                sev_color = C_RED if sev == 'CRITICAL' else (C_YELLOW if sev == 'WARNING' else C_WHITE)

                time_part = a.get('created_at', '').split('.')[0]
                if 'T' in time_part:
                    time_part = time_part.split('T')[1]

                status_lbl = "ACK" if a.get('acknowledged') else "OPEN"
                status_color = C_GREEN if a.get('acknowledged') else C_RED

                # Clip alert messages to terminal width
                msg_len = cols - 48
                msg_str = a.get('message', '')
                if len(msg_str) > msg_len:
                    msg_str = msg_str[:msg_len - 3] + "..."

                line = f" {sev_color}[{sev:<8}]{C_RESET} {time_part} │ {a.get('device_name') or a.get('device_ip',''):<14} │ {msg_str:<{msg_len}} │ {status_color}{status_lbl}{C_RESET}"
                draw_str(2, alert_y + 1 + idx, line)
            
            # Clear remaining alert rows
            for empty_idx in range(len(alerts), alert_h - 2):
                draw_str(2, alert_y + 1 + empty_idx, " " * (cols - 2))
        else:
            draw_str(3, alert_y + 2, "Tidak ada peringatan aktif.", C_GRAY)
            for empty_idx in range(1, alert_h - 2):
                draw_str(2, alert_y + 1 + empty_idx, " " * (cols - 2))

        # 5. --- KEY COMMANDS BAR / FOOTER ---
        footer_y = rows
        footer_lbls = " [▲▼] Pilih  [P] Poll  [A] Tambah  [D] Hapus  [S] Scan  [C] Ack Alerts  [Q] Keluar"
        footer_text = f"{C_BOLD}{C_BG_CARD}{footer_lbls}"
        padding_len = cols - len(footer_lbls)
        if padding_len > 0:
            footer_text += " " * padding_len
        footer_text += C_RESET
        draw_str(1, footer_y, footer_text)

        sys.stdout.flush()

    def add_new_device_tui(self):
        sys.stdout.write("\033[?25h") # Show cursor
        sys.stdout.flush()
        cleanup_terminal()
        self.clear_screen()

        print(f"{C_BOLD}{C_CYAN}=== TAMBAH PERANGKAT BARU ==={C_RESET}\n")
        ip = input(" Masukkan Alamat IP (Wajib): ").strip()
        if ip:
            name = input(" Masukkan Nama Perangkat (Default = IP): ").strip() or ip
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
                self.db.add_device(data)
                print(f"\n{C_GREEN}Perangkat berhasil ditambahkan!{C_RESET}")
            except Exception as e:
                print(f"\n{C_RED}Gagal menambahkan perangkat: {e}{C_RESET}")
        else:
            print(f"\n{C_RED}IP tidak boleh kosong!{C_RESET}")

        time.sleep(1.5)
        sys.stdout.write("\033[?25l") # Hide cursor
        sys.stdout.flush()
        init_terminal()
        self.clear_screen()

    def delete_device_tui(self):
        devices = self.db.get_all_devices()
        if not devices or self.selected_idx >= len(devices):
            return
        dev = devices[self.selected_idx]

        sys.stdout.write("\033[?25h") # Show cursor
        sys.stdout.flush()
        cleanup_terminal()
        self.clear_screen()

        print(f"{C_BOLD}{C_RED}=== HAPUS PERANGKAT ==={C_RESET}\n")
        confirm = input(f" Apakah Anda yakin ingin menghapus {C_BOLD}{dev['name']}{C_RESET} ({dev['ip']})? (y/N): ").strip().lower()
        if confirm == 'y':
            try:
                self.db.delete_device(dev['id'])
                print(f"\n{C_GREEN}Perangkat berhasil dihapus!{C_RESET}")
                self.selected_idx = max(0, self.selected_idx - 1)
            except Exception as e:
                print(f"\n{C_RED}Gagal menghapus perangkat: {e}{C_RESET}")
        else:
            print("\nHapus dibatalkan.")

        time.sleep(1.5)
        sys.stdout.write("\033[?25l") # Hide cursor
        sys.stdout.flush()
        init_terminal()
        self.clear_screen()

    def run_network_scan_tui(self):
        sys.stdout.write("\033[?25h") # Show cursor
        sys.stdout.flush()
        cleanup_terminal()
        self.clear_screen()

        print(f"{C_BOLD}{C_CYAN}=== NETMON NETWORK SCAN & DISCOVERY ==={C_RESET}\n")
        net = input(" Masukkan subnet CIDR (contoh: 172.17.17.0/24): ").strip()
        if net:
            community = input(" SNMP Community String (Default 'public'): ").strip() or 'public'
            version = input(" SNMP Version (1/2c, Default '2c'): ").strip() or '2c'

            print(f"\nMemulai pemindaian pada {net}...")
            print("Mohon tunggu, proses ini berjalan di latar belakang...\n")

            # Spawn scan in separate background thread
            t = threading.Thread(target=self.worker.scan_network, args=(net, community, version), daemon=True)
            t.start()

            # Dynamic progress feedback loop
            try:
                while t.is_alive():
                    status = self.worker.get_scan_status()
                    if status.get('running'):
                        print(f"\r Progress: {status.get('progress')}/{status.get('total')} IP ({status.get('percent')}%) │ Ditemukan: {status.get('found')} perangkat │ IP Aktif: {status.get('current_ip')}", end="", flush=True)
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nMembatalkan pemindaian...")
                self.worker.stop_scan()
                t.join()

            t.join()
            print(f"\n\n{C_GREEN}Pemindaian selesai!{C_RESET}")
        else:
            print(f"\n{C_RED}Subnet CIDR tidak boleh kosong!{C_RESET}")

        time.sleep(2.0)
        sys.stdout.write("\033[?25l") # Hide cursor
        sys.stdout.flush()
        init_terminal()
        self.clear_screen()

    def quit(self):
        self.running = False
        cleanup_terminal()
        self.clear_screen()
        print("\nKeluar dari NetMon TUI. Terima kasih!\n")
        sys.exit(0)


if __name__ == "__main__":
    tui = NetMonTUI()
    tui.run()
