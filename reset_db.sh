#!/usr/bin/env bash
# ==============================================================================
#  NetMon Database Reset Script
# ==============================================================================
#  Deskripsi: Script ini menghapus semua data record historis (metrics, logs,
#             alerts, reports) tetapi mempertahankan data device dan settings.
# ==============================================================================

# Lokasi instalasi NetMon
NETMON_DIR="/opt/netmon"
DB_PATH="$NETMON_DIR/netmon.db"

# Warna untuk output terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Pastikan dijalankan sebagai root / sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Run as root: sudo $0${NC}"
    exit 1
fi

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}${BOLD}             NETMON DATABASE RESET TOOL               ${NC}"
echo -e "${CYAN}======================================================${NC}"
echo -e "Target Database: $DB_PATH"
echo ""

if [ ! -f "$DB_PATH" ]; then
    echo -e "${RED}[ERROR] Database tidak ditemukan di $DB_PATH!${NC}"
    exit 1
fi

# Konfirmasi pengguna
read -p "Apakah Anda yakin ingin menghapus semua data historis NetMon? (y/N) " confirm
if [[ ! "$confirm" =~ ^[yY]$ ]]; then
    echo -e "${YELLOW}Proses reset dibatalkan.${NC}"
    exit 0
fi

echo -e "${YELLOW}Menghentikan service netmon temporer...${NC}"
if command -v systemctl &>/dev/null && systemctl is-active --quiet netmon.service; then
    systemctl stop netmon.service
    WAS_RUNNING=true
else
    WAS_RUNNING=false
fi

echo -e "${YELLOW}Menghapus data record historis...${NC}"
/opt/netmon/venv/bin/python << 'EOF'
import sqlite3
try:
    conn = sqlite3.connect('/opt/netmon/netmon.db')
    c = conn.cursor()
    
    # Kosongkan data telemetry & logs
    c.execute('DELETE FROM snmp_metrics')
    c.execute('DELETE FROM interface_traffic')
    c.execute('DELETE FROM alerts')
    c.execute('DELETE FROM access_logs')
    c.execute('DELETE FROM monthly_reports')
    
    # Reclaim unused disk space
    c.execute('VACUUM')
    
    conn.commit()
    conn.close()
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {e}")
EOF

# Kembalikan kepemilikan file agar service netmon tetap bisa menulis database
chown netmon:netmon "$DB_PATH"
chmod 664 "$DB_PATH"

if [ "$WAS_RUNNING" = true ]; then
    echo -e "${YELLOW}Menjalankan kembali service netmon...${NC}"
    systemctl start netmon.service
fi

echo ""
echo -e "${GREEN}${BOLD}======================================================${NC}"
echo -e "${GREEN}${BOLD}   BERHASIL: Semua data historis telah dikosongkan!   ${NC}"
echo -e "${GREEN}${BOLD}   (Data perangkat & konfigurasi tetap terjaga)       ${NC}"
echo -e "${GREEN}${BOLD}======================================================${NC}"
