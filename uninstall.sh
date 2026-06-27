#!/usr/bin/env bash
# =============================================================
#  NetMon — Uninstall Script
#  Cleans up all system configurations, files, user, and service
#  to ensure a 100% fresh reinstall.
# =============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

INSTALL_DIR="/opt/netmon"
SERVICE_USER="netmon"
PORT="5000"
OS=$(uname -s)

info()    { echo -e "  ${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "  ${RED}[ERROR]${NC} $*" >&2; exit 1; }
step()    { echo -e "\n  ${BOLD}▶ $*${NC}"; }

# Check root permissions
check_root() {
  if [[ $OS == "Linux" && $EUID -ne 0 ]]; then
    error "Run as root: sudo $0"
  fi
}

# Stop and Disable Systemd Service
stop_service() {
  if [[ $OS == "Linux" ]] && command -v systemctl &>/dev/null; then
    step "Stopping and disabling NetMon service"
    
    if systemctl is-active --quiet netmon; then
      systemctl stop netmon
      info "Service netmon stopped"
    else
      info "Service netmon is already stopped"
    fi

    if systemctl is-enabled --quiet netmon 2>/dev/null; then
      systemctl disable netmon
      info "Service netmon disabled"
    fi

    # Remove systemd unit file
    if [[ -f /etc/systemd/system/netmon.service ]]; then
      rm -f /etc/systemd/system/netmon.service
      systemctl daemon-reload
      success "Systemd service file removed"
    fi
  fi
}

# Remove Firewall Rules
remove_firewall() {
  [[ $OS != "Linux" ]] && return
  step "Removing firewall rules"
  
  if command -v ufw &>/dev/null && ufw status | grep -q "Status: active"; then
    ufw delete allow "$PORT/tcp" 2>/dev/null || true
    success "ufw: port $PORT rule deleted"
  elif command -v firewall-cmd &>/dev/null && firewall-cmd --state &>/dev/null; then
    firewall-cmd --permanent --remove-port="${PORT}/tcp" 2>/dev/null || true
    firewall-cmd --reload 2>/dev/null || true
    success "firewalld: port $PORT rule deleted"
  else
    info "No active firewall configurations found"
  fi
}

# Delete Installation Files
delete_files() {
  step "Deleting installation files"
  if [[ -f "/usr/local/bin/netmon-tui" ]]; then
    rm -f "/usr/local/bin/netmon-tui"
    success "Removed CLI command: /usr/local/bin/netmon-tui"
  fi
  if [[ -d "$INSTALL_DIR" ]]; then
    # Double check it is not root directory before deletion
    if [[ "$INSTALL_DIR" != "/" && "$INSTALL_DIR" != "/home" ]]; then
      
      # Database preservation logic
      if [[ -f "$INSTALL_DIR/netmon.db" ]]; then
        if [[ ! "${REMOVE_DB:-N}" =~ ^[Yy]$ ]]; then
          info "Preserving database: copying $INSTALL_DIR/netmon.db to /var/lib/netmon.db"
          mkdir -p /var/lib
          cp "$INSTALL_DIR/netmon.db" /var/lib/netmon.db
          success "Database preserved at /var/lib/netmon.db"
        fi
      fi
      
      # Clean python cache inside install dir before deletion
      find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
      find "$INSTALL_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
      
      rm -rf "$INSTALL_DIR"
      success "Deleted folder: $INSTALL_DIR (venv, code, templates, and static assets cleaned)"
    else
      error "Safety trigger: INSTALL_DIR points to root or home directory!"
    fi
  else
    info "Installation directory $INSTALL_DIR not found"
  fi
  
  # Deep Cleaning remnants
  step "Deep cleaning system caches and temporary files"
  
  # Clean PIP cache
  rm -rf /root/.cache/pip
  rm -rf /home/*/.cache/pip
  if command -v pip &>/dev/null; then
    pip cache purge &>/dev/null || true
  fi
  success "Cleared PIP installation cache"
  
  # Clean system temporary files
  rm -rf /tmp/netmon*
  rm -rf /tmp/pip-unpack-*
  success "Cleared temporary build files"
  
  # Reset systemd failed logs
  if [[ $OS == "Linux" ]] && command -v systemctl &>/dev/null; then
    systemctl reset-failed netmon 2>/dev/null || true
    systemctl daemon-reload
    success "Reset systemd failed units registry"
  fi
}

# Delete Service User
delete_user() {
  [[ $OS != "Linux" ]] && return
  step "Deleting service user '$SERVICE_USER'"
  
  if id "$SERVICE_USER" &>/dev/null; then
    # Kill any lingering processes owned by netmon user
    pkill -u "$SERVICE_USER" 2>/dev/null || true
    sleep 1
    
    userdel -r "$SERVICE_USER" 2>/dev/null || true
    groupdel "$SERVICE_USER" 2>/dev/null || true
    success "User and group '$SERVICE_USER' deleted"
  else
    info "User '$SERVICE_USER' does not exist"
  fi
}

# main
main() {
  echo -e "${CYAN}${BOLD}"
  echo "  ███╗   ██╗███████╗████████╗███╗   ███╗ ██████╗ ███╗   ██╗"
  echo "  ████╗  ██║██╔════╝╚══██╔══╝████╗ ████║██╔═══██╗████╗  ██║"
  echo "  ██╔██╗ ██║█████╗     ██║   ██╔████╔██║██║   ██║██╔██╗ ██║"
  echo "  ██║╚██╗██║██╔══╝     ██║   ██║╚██╔╝██║██║   ██║██║╚██╗██║"
  echo "  ██║ ╚████║███████╗   ██║   ██║ ╚═╝ ██║╚██████╔╝██║ ╚████║"
  echo "  ╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"
  echo -e "${NC}"
  echo -e "  ${BOLD}Network Monitoring Application${NC} — Uninstall Script"
  echo "  This will delete all logs, database, settings, and code."
  echo ""
  
  check_root
  
  read -rp "  Are you sure you want to completely uninstall NetMon? [y/N]: " CONFIRM
  CONFIRM="${CONFIRM:-N}"
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "\n  ${YELLOW}Uninstallation cancelled.${NC}\n"
    exit 0
  fi
  
  read -rp "  Apakah Anda ingin menghapus database aplikasi (netmon.db)? [y/N]: " REMOVE_DB
  REMOVE_DB="${REMOVE_DB:-N}"
  
  stop_service
  remove_firewall
  delete_files
  delete_user
  
  echo ""
  echo -e "${GREEN}${BOLD}  ===============================================${NC}"
  echo -e "${GREEN}${BOLD}   NetMon has been uninstalled successfully!${NC}"
  echo -e "${GREEN}${BOLD}   System is clean and ready for a fresh install.${NC}"
  echo -e "${GREEN}${BOLD}  ===============================================${NC}"
  echo ""
}

main "$@"
