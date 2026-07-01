#!/usr/bin/env bash
# ==============================================================================
#  NetMon Resource Monitor Script
# ==============================================================================
#  Deskripsi: Script ini memantau penggunaan resource (CPU, RAM, DB size, Status)
#             khusus untuk aplikasi monitoring NetMon di Linux/WSL.
# ==============================================================================

# Lokasi instalasi NetMon
NETMON_DIR="/opt/netmon"
DB_PATH="$NETMON_DIR/netmon.db"

# Warna untuk output terminal
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}${BOLD}          NETMON RESOURCE MONITORING STATUS           ${NC}"
echo -e "${CYAN}======================================================${NC}"
echo -e "Waktu Cek: $(date '+%d %B %Y - %H:%M:%S')"
echo ""

# 1. Cek Status Service Systemd atau Manual Process
echo -e "${YELLOW}[1] STATUS LAYANAN (SERVICE STATUS)${NC}"
PID=""
if command -v systemctl &>/dev/null && systemctl is-active --quiet netmon.service; then
    echo -e "Service Status : ${GREEN}ACTIVE (Running via systemd)${NC}"
    PID=$(systemctl show -p MainPID --value netmon.service)
    echo -e "Main PID       : $PID"
else
    # Cari PID manual (jika berjalan tanpa systemd / WSL manual)
    PID=$(pgrep -f "app.py" | head -n 1 || true)
    if [ -n "$PID" ]; then
        echo -e "Service Status : ${YELLOW}RUNNING (Manual Mode)${NC}"
        echo -e "Main PID       : $PID"
    else
        echo -e "Service Status : ${RED}INACTIVE (Stopped)${NC}"
    fi
fi
echo ""

# 2. Cek Penggunaan Resource CPU & RAM (khusus NetMon)
echo -e "${YELLOW}[2] PENGGUNAAN RESOURCE CPU & RAM (NETMON PROCESS)${NC}"
if [ -n "$PID" ]; then
    # Mengambil CPU & RAM menggunakan ps
    CPU_USAGE=$(ps -p "$PID" -o %cpu --no-headers | tr -d ' ')
    MEM_USAGE_KB=$(ps -p "$PID" -o rss --no-headers | tr -d ' ')
    MEM_USAGE_MB=$(echo "scale=2; $MEM_USAGE_KB / 1024" | bc)
    
    # Ambil RAM total sistem untuk persentase
    TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    MEM_PERCENT=$(echo "scale=2; ($MEM_USAGE_KB / $TOTAL_MEM_KB) * 100" | bc)
    
    # Dapatkan jumlah thread dari NetMon
    THREAD_COUNT=$(ps -o nlwp --no-headers -p "$PID" | tr -d ' ')

    echo -e "CPU Usage      : ${GREEN}$CPU_USAGE%${NC}"
    echo -e "RAM Usage      : ${GREEN}$MEM_USAGE_MB MB${NC} (~$MEM_PERCENT% dari total sistem RAM)"
    echo -e "Active Threads : ${GREEN}$THREAD_COUNT thread(s)${NC} (termasuk SNMP workers & SocketIO)"
else
    echo -e "CPU Usage      : ${RED}0%${NC}"
    echo -e "RAM Usage      : ${RED}0 MB${NC}"
    echo -e "Active Threads : ${RED}0${NC}"
fi
echo ""

# 3. Cek Penggunaan Penyimpanan (Database & Log)
echo -e "${YELLOW}[3] PENGGUNAAN STORAGE DATABASE & LOGS${NC}"
if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(du -sh "$DB_PATH" | awk '{print $1}')
    echo -e "Database Size (netmon.db) : ${GREEN}$DB_SIZE${NC}"
    
    # Cek mode jurnal SQLite (WAL vs DELETE)
    if [ -n "$PID" ] && command -v sqlite3 &>/dev/null; then
        DB_MODE=$(sqlite3 "$DB_PATH" "PRAGMA journal_mode;" 2>/dev/null || true)
        if [ -n "$DB_MODE" ]; then
            echo -e "Database Journal Mode     : ${GREEN}${DB_MODE^^}${NC}"
        fi
    fi
else
    # Fallback ke directory local jika /opt/netmon/netmon.db tidak ada
    LOCAL_DB="./netmon.db"
    if [ -f "$LOCAL_DB" ]; then
        DB_SIZE=$(du -sh "$LOCAL_DB" | awk '{print $1}')
        echo -e "Database Size (Local DB)  : ${GREEN}$DB_SIZE${NC}"
    else
        echo -e "Database (netmon.db)      : ${RED}TIDAK DITEMUKAN${NC}"
    fi
fi

# Cek Folder instalasi keseluruhan
if [ -d "$NETMON_DIR" ]; then
    TOTAL_SIZE=$(du -sh "$NETMON_DIR" | awk '{print $1}')
    echo -e "Total Folder Size (/opt)  : ${GREEN}$TOTAL_SIZE${NC}"
fi
echo ""

# 4. Cek Aktivitas Socket Jaringan
echo -e "${YELLOW}[4] AKTIVITAS KONEKSI NETMON (PORT BIND)${NC}"
if command -v ss &>/dev/null; then
    # Cek port 5000 (port Flask default)
    PORT_CHECK=$(ss -tlnp | grep -E ':5000\s' || true)
    if [ -n "$PORT_CHECK" ]; then
        echo -e "Web Server Interface      : ${GREEN}ONLINE (Port 5000)${NC}"
        # Hitung jumlah klien WebSocket aktif
        CONN_COUNT=$(ss -tn state established | grep -c ':5000' || true)
        echo -e "Active Clients Connected  : ${GREEN}$CONN_COUNT connection(s)${NC}"
    else
        echo -e "Web Server Interface      : ${RED}OFFLINE / Bounded to different port${NC}"
    fi
else
    echo -e "Status Koneksi            : ${YELLOW}'ss' command not found. Skip.${NC}"
fi
echo -e "${CYAN}======================================================${NC}"
