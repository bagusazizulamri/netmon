#!/usr/bin/env bash
# =============================================================
#  NetMon — Update Script
#  Updates the application in place at /opt/netmon, pulls the
#  latest changes from git, installs new dependencies,
#  and restarts the systemd service safely without deleting the database.
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

check_root() {
  if [[ $OS == "Linux" && $EUID -ne 0 ]]; then
    error "Run as root: sudo $0"
  fi
}

check_root

step "Updating source code"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null; then
  info "Pulling latest code changes from Git..."
  git pull
  success "Git source repository updated"
else
  info "Not inside a git repository, using current directory files directly"
fi

if [[ -d "$INSTALL_DIR" ]]; then
  step "Applying updates to installation directory: $INSTALL_DIR"
  
  # Copy files except database and virtual environment
  info "Copying updated files to $INSTALL_DIR..."
  
  # Using rsync if available to avoid overwriting netmon.db and venv
  if command -v rsync &>/dev/null; then
    rsync -rtv --exclude='venv' --exclude='netmon.db' --exclude='*.pyc' --exclude='__pycache__' --exclude='.git' "$SCRIPT_DIR/" "$INSTALL_DIR/"
  else
    # Fallback to manual copying of safe directories/files
    cp -r "$SCRIPT_DIR"/templates "$INSTALL_DIR/" 2>/dev/null || true
    cp -r "$SCRIPT_DIR"/static "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR"/update.sh "$INSTALL_DIR/" 2>/dev/null || true
  fi
  success "Files updated successfully"
  
  # Update dependencies if virtual environment exists
  if [[ -d "$INSTALL_DIR/venv" ]]; then
    step "Updating Python dependencies"
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
    success "Dependencies updated"
  fi
  
  # Set permissions
  if [[ $OS == "Linux" ]]; then
    chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR"
    chmod -R 755 "$INSTALL_DIR"
  fi
  
  # Restart service
  if [[ $OS == "Linux" ]] && command -v systemctl &>/dev/null; then
    if systemctl list-unit-files | grep -q "netmon.service"; then
      step "Restarting systemd service: netmon"
      systemctl daemon-reload
      systemctl restart netmon
      success "NetMon systemd service restarted successfully!"
    fi
  fi
else
  # If running in local directory (development or custom setup)
  step "Running in-place local update"
  if [[ -d "venv" ]]; then
    ./venv/bin/pip install --upgrade pip -q
    ./venv/bin/pip install -r requirements.txt -q
    success "Local venv dependencies updated"
  fi
fi

echo ""
echo -e "${GREEN}${BOLD}  ===============================================${NC}"
echo -e "${GREEN}${BOLD}   NetMon has been updated successfully!${NC}"
echo -e "${GREEN}${BOLD}  ===============================================${NC}"
echo ""
