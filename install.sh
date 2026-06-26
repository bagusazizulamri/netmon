#!/usr/bin/env bash
# =============================================================
#  NetMon — Install Script
#  Supports: Ubuntu 20.04+, Debian 11+, CentOS 8+, macOS 12+
# =============================================================
set -euo pipefail
IFS=$'\n\t'

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

INSTALL_DIR="${NETMON_DIR:-/opt/netmon}"
SERVICE_USER="${NETMON_USER:-netmon}"
PORT="${NETMON_PORT:-5000}"
OS=$(uname -s)

banner() {
  echo ""
  echo -e "${CYAN}${BOLD}"
  echo "  ███╗   ██╗███████╗████████╗███╗   ███╗ ██████╗ ███╗   ██╗"
  echo "  ████╗  ██║██╔════╝╚══██╔══╝████╗ ████║██╔═══██╗████╗  ██║"
  echo "  ██╔██╗ ██║█████╗     ██║   ██╔████╔██║██║   ██║██╔██╗ ██║"
  echo "  ██║╚██╗██║██╔══╝     ██║   ██║╚██╔╝██║██║   ██║██║╚██╗██║"
  echo "  ██║ ╚████║███████╗   ██║   ██║ ╚═╝ ██║╚██████╔╝██║ ╚████║"
  echo "  ╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"
  echo -e "${NC}"
  echo -e "  ${BOLD}Network Monitoring Application${NC} — Install Script"
  echo ""
}

info()    { echo -e "  ${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "  ${RED}[ERROR]${NC} $*" >&2; exit 1; }
step()    { echo -e "\n  ${BOLD}▶ $*${NC}"; }

# =============================================================
# CHECKS
# =============================================================
check_root() {
  if [[ $OS == "Linux" && $EUID -ne 0 ]]; then
    error "Run as root: sudo $0"
  fi
}

check_python() {
  step "Checking Python 3"
  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
      PYTHON=$cmd
      VERSION=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
      MAJOR=$(echo "$VERSION" | cut -d. -f1)
      MINOR=$(echo "$VERSION" | cut -d. -f2)
      if [[ $MAJOR -ge 3 && $MINOR -ge 9 ]]; then
        success "Found Python $VERSION ($cmd)"
        return
      fi
    fi
  done
  error "Python 3.9+ required. Install it first:\n  Ubuntu: sudo apt install python3\n  CentOS: sudo dnf install python3"
}

check_pip() {
  step "Checking pip"
  if "$PYTHON" -m pip --version &>/dev/null; then
    success "pip available"
  else
    warn "pip not found — attempting install"
    "$PYTHON" -m ensurepip --upgrade 2>/dev/null || {
      if [[ $OS == "Linux" ]]; then
        apt-get install -y python3-pip 2>/dev/null || dnf install -y python3-pip 2>/dev/null || \
          error "Cannot install pip. Install manually: https://pip.pypa.io"
      else
        error "Install pip manually: https://pip.pypa.io"
      fi
    }
    success "pip installed"
  fi
}

# =============================================================
# SYSTEM PACKAGES (Linux only)
# =============================================================
install_sys_packages() {
  [[ $OS != "Linux" ]] && return
  step "Installing system packages"

  if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq \
      python3-venv python3-pip net-tools iputils-ping \
      libffi-dev libssl-dev 2>/dev/null || true
    success "apt packages installed"

  elif command -v dnf &>/dev/null; then
    dnf install -y -q \
      python3 python3-pip python3-venv net-tools \
      libffi-devel openssl-devel 2>/dev/null || true
    success "dnf packages installed"

  elif command -v yum &>/dev/null; then
    yum install -y -q \
      python3 python3-pip net-tools libffi-devel openssl-devel 2>/dev/null || true
    success "yum packages installed"
  fi
}

# =============================================================
# DIRECTORY & FILES
# =============================================================
create_dirs() {
  step "Creating install directory: $INSTALL_DIR"
  mkdir -p "$INSTALL_DIR"/{templates,static/css,static/js,static/img}
  success "Directories created"
}

copy_files() {
  step "Copying application files"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/" 2>/dev/null || true
  success "Files copied to $INSTALL_DIR"
}

# =============================================================
# VIRTUAL ENVIRONMENT
# =============================================================
create_venv() {
  step "Creating Python virtual environment"
  cd "$INSTALL_DIR"
  "$PYTHON" -m venv venv
  success "venv created at $INSTALL_DIR/venv"
}

install_deps() {
  step "Installing Python dependencies"
  cd "$INSTALL_DIR"
  ./venv/bin/pip install --upgrade pip -q
  ./venv/bin/pip install -r requirements.txt -q
  success "Dependencies installed"
  # Verify pysnmp
  if ./venv/bin/python -c "import pysnmp" 2>/dev/null; then
    success "pysnmp verified"
  else
    warn "pysnmp import check failed — SNMP features may not work"
  fi
}

# =============================================================
# START SCRIPT
# =============================================================
create_start_script() {
  step "Creating start script"
  cat > "$INSTALL_DIR/start.sh" << STARTEOF
#!/usr/bin/env bash
# NetMon Start Script
cd "$(dirname "\$0")"
source venv/bin/activate
export PORT=${PORT}
export HOST=0.0.0.0
exec python app.py
STARTEOF
  chmod +x "$INSTALL_DIR/start.sh"
  success "start.sh created"
}

# =============================================================
# REGISTER TUI COMMAND
# =============================================================
create_tui_command() {
  [[ $OS != "Linux" ]] && return
  step "Registering netmon-tui CLI command"
  
  cat > "/usr/local/bin/netmon-tui" << TUIEOF
#!/usr/bin/env bash
# NetMon TUI CLI Wrapper
exec ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/tui.py "\$@"
TUIEOF
  
  chmod +x "/usr/local/bin/netmon-tui"
  chmod +x "$INSTALL_DIR/tui.py"
  success "netmon-tui command registered (/usr/local/bin/netmon-tui)"
}

# =============================================================
# LINUX SYSTEMD SERVICE
# =============================================================
create_systemd_service() {
  [[ $OS != "Linux" ]] && return
  if ! command -v systemctl &>/dev/null; then
    warn "systemd not found — skipping service creation"
    return
  fi

  step "Setting up systemd service"

  # Create service user if needed
  if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /sbin/nologin -d "$INSTALL_DIR" "$SERVICE_USER" 2>/dev/null || true
    info "Created user: $SERVICE_USER"
  fi

  chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
  chmod -R 755 "$INSTALL_DIR"

  cat > /etc/systemd/system/netmon.service << SVCEOF
[Unit]
Description=NetMon Network Monitoring Application
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
Environment="PORT=${PORT}"
Environment="HOST=0.0.0.0"
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=netmon

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
SVCEOF

  systemctl daemon-reload
  systemctl enable netmon
  success "systemd service enabled (netmon.service)"
}

# =============================================================
# FIREWALL
# =============================================================
configure_firewall() {
  [[ $OS != "Linux" ]] && return
  step "Configuring firewall"
  if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow "$PORT/tcp" comment 'NetMon' 2>/dev/null || true
    success "ufw: port $PORT allowed"
  elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
    firewall-cmd --permanent --add-port="${PORT}/tcp" 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
    success "firewalld: port $PORT allowed"
  else
    warn "No active firewall detected — make sure port $PORT is accessible"
  fi
}

# =============================================================
# INIT DB
# =============================================================
init_database() {
  step "Initialising database"
  cd "$INSTALL_DIR"
  ./venv/bin/python -c "from database import Database; db = Database(); print('  Database OK')"
  if [[ $OS == "Linux" ]]; then
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
  fi
  success "netmon.db initialised"
}

# =============================================================
# PRINT SUMMARY
# =============================================================
print_summary() {
  IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
  echo ""
  echo -e "${GREEN}${BOLD}  ============================================${NC}"
  echo -e "${GREEN}${BOLD}   NetMon installed successfully!${NC}"
  echo -e "${GREEN}${BOLD}  ============================================${NC}"
  echo ""
  echo -e "  ${BOLD}Install directory:${NC} $INSTALL_DIR"
  echo -e "  ${BOLD}Dashboard URL:${NC}     http://${IP}:${PORT}"
  echo ""
  if [[ $OS == "Linux" ]] && command -v systemctl &>/dev/null; then
    echo -e "  ${BOLD}Service commands:${NC}"
    echo -e "    Start:   ${CYAN}sudo systemctl start netmon${NC}"
    echo -e "    Stop:    ${CYAN}sudo systemctl stop netmon${NC}"
    echo -e "    Status:  ${CYAN}sudo systemctl status netmon${NC}"
    echo -e "    Logs:    ${CYAN}sudo journalctl -u netmon -f${NC}"
    echo -e "    TUI CLI: ${CYAN}sudo netmon-tui${NC}"
    echo ""
    echo -e "  ${BOLD}Start now:${NC}"
    echo -e "    ${CYAN}sudo systemctl start netmon${NC}"
  else
    echo -e "  ${BOLD}Start manually:${NC}"
    echo -e "    ${CYAN}cd $INSTALL_DIR && ./start.sh${NC}"
  fi
  echo ""
  echo -e "  ${BOLD}Manual start (any OS):${NC}"
  echo -e "    ${CYAN}cd $INSTALL_DIR && ./start.sh${NC}"
  echo ""
  echo -e "  ${YELLOW}SNMP Note:${NC} Ensure SNMP is enabled on your devices."
  echo -e "  Default community string: ${CYAN}public${NC}"
  echo ""
}

# =============================================================
# MAIN
# =============================================================
main() {
  local backup_db=false
  local db_backup_path="/tmp/netmon.db.bak"

  banner
  check_root

  # Check for existing installation
  if [[ -d "$INSTALL_DIR" || -f "/etc/systemd/system/netmon.service" || -f "/usr/local/bin/netmon-tui" ]]; then
    step "Existing NetMon installation detected!"
    info "Initiating automatic uninstallation before performing a fresh install..."

    # 1. Backup database
    if [[ -f "$INSTALL_DIR/netmon.db" ]]; then
      info "Preserving database: backing up $INSTALL_DIR/netmon.db to $db_backup_path"
      cp "$INSTALL_DIR/netmon.db" "$db_backup_path"
      backup_db=true
    fi

    # 2. Stop and disable service
    if command -v systemctl &>/dev/null; then
      if systemctl is-active --quiet netmon; then
        info "Stopping netmon service..."
        systemctl stop netmon || true
      fi
      if systemctl is-enabled --quiet netmon 2>/dev/null; then
        info "Disabling netmon service..."
        systemctl disable netmon || true
      fi
      if [[ -f /etc/systemd/system/netmon.service ]]; then
        rm -f /etc/systemd/system/netmon.service
        systemctl daemon-reload
      fi
    fi

    # 3. Clean up CLI command
    if [[ -f "/usr/local/bin/netmon-tui" ]]; then
      rm -f "/usr/local/bin/netmon-tui"
    fi

    # 4. Delete old installation files
    if [[ -d "$INSTALL_DIR" && "$INSTALL_DIR" != "/" ]]; then
      info "Cleaning up old installation directory: $INSTALL_DIR"
      rm -rf "$INSTALL_DIR"
    fi

    success "Existing installation cleaned up successfully."
  fi

  check_python
  check_pip
  install_sys_packages
  create_dirs
  copy_files

  # Restore database if backed up
  if [[ "$backup_db" == "true" && -f "$db_backup_path" ]]; then
    step "Restoring database"
    cp "$db_backup_path" "$INSTALL_DIR/netmon.db"
    rm -f "$db_backup_path"
    success "Database restored to $INSTALL_DIR/netmon.db"
  fi

  create_venv
  install_deps
  create_start_script
  create_tui_command
  create_systemd_service
  configure_firewall
  init_database
  print_summary

  if [[ $OS == "Linux" ]] && command -v systemctl &>/dev/null; then
    read -rp "  Start NetMon now? [Y/n]: " START_NOW
    START_NOW="${START_NOW:-Y}"
    if [[ "$START_NOW" =~ ^[Yy]$ ]]; then
      systemctl start netmon
      sleep 2
      if systemctl is-active --quiet netmon; then
        success "NetMon is running on http://$(hostname -I | awk '{print $1}'):${PORT}"
      else
        warn "Service may not have started — check: sudo journalctl -u netmon -n 50"
      fi
    fi
  fi
}

main "$@"
