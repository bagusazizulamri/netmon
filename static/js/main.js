/* ============================================================
   NetMon — main.js  (shared across all pages)
   ============================================================ */

// ---- Socket.IO setup ----
const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
  const el = document.getElementById('sb-conn');
  if (el) el.innerHTML = '<i class="bi bi-wifi text-success"></i> Connected';
});
socket.on('disconnect', () => {
  const el = document.getElementById('sb-conn');
  if (el) el.innerHTML = '<i class="bi bi-wifi-off text-danger"></i> Disconnected';
});
socket.on('connect_error', () => {
  const el = document.getElementById('sb-conn');
  if (el) el.innerHTML = '<i class="bi bi-exclamation-triangle text-warning"></i> Reconnecting…';
});

// --- Dispatch init data to page handlers ---
socket.on('init_data', (data) => {
  if (typeof window.onInitData === 'function') window.onInitData(data);
  if (data.stats) updateSidebarStats(data.stats);
});

socket.on('stats_update', (stats) => {
  updateSidebarStats(stats);
  if (typeof window.onStatsUpdate === 'function') window.onStatsUpdate(stats);
});

socket.on('device_status_update', (dev) => {
  if (typeof window.onDeviceStatusUpdate === 'function') window.onDeviceStatusUpdate(dev);
  if (typeof window.onDeviceUpdate       === 'function') window.onDeviceUpdate(dev);
});

socket.on('device_added', (dev) => {
  if (typeof window.onDeviceUpdate === 'function') window.onDeviceUpdate(dev);
});
socket.on('device_updated', (dev) => {
  if (typeof window.onDeviceStatusUpdate === 'function') window.onDeviceStatusUpdate(dev);
  if (typeof window.onDeviceUpdate       === 'function') window.onDeviceUpdate(dev);
});
socket.on('device_deleted', (data) => {
  if (typeof window.onDeviceUpdate === 'function') window.onDeviceUpdate(data);
});

socket.on('new_alert', (alert) => {
  if (typeof window.onNewAlert === 'function') window.onNewAlert(alert);
  showToast(alert.message, alert.severity === 'critical' ? 'danger' : (alert.severity || 'info'), 5000);
});

socket.on('alert_acked', (d) => {
  if (typeof window.onAlertAcked === 'function') window.onAlertAcked(d);
});
socket.on('all_alerts_acked', () => {
  if (typeof window.onAllAlertsAcked === 'function') window.onAllAlertsAcked();
});

socket.on('scan_progress', (d) => {
  if (typeof window.onScanProgress === 'function') window.onScanProgress(d);
});
socket.on('scan_complete', (d) => {
  if (typeof window.onScanComplete === 'function') window.onScanComplete(d);
});
socket.on('scan_started', (d) => {
  if (typeof window.onScanStarted === 'function') window.onScanStarted(d);
});
socket.on('scan_error', (d) => {
  showToast('Scan error: ' + d.error, 'danger');
  if (typeof window.onScanError === 'function') window.onScanError(d);
});
socket.on('device_found', (d) => {
  if (typeof window.onDeviceFound === 'function') window.onDeviceFound(d);
});
socket.on('unifi_sync_complete', (d) => {
  if (typeof window.onUnifiSync === 'function') window.onUnifiSync(d);
});

// ---- Sidebar stats ----
function updateSidebarStats(s) {
  if (!s) return;
  setEl('sb-up',   s.up      ?? '—');
  setEl('sb-down', s.down    ?? '—');
  setEl('sb-warn', s.warning ?? '—');
  setEl('sb-unk',  s.unknown ?? '—');
}

// ---- Clock ----
function updateClock() {
  const el = document.getElementById('sb-time');
  if (el) el.textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);
updateClock();

// ============================================================
// DOM helpers
// ============================================================
function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function relTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts.replace ? ts.replace(' ', 'T') : ts);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (isNaN(diff)) return ts;
  if (diff < 5)    return 'just now';
  if (diff < 60)   return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
  if (diff < 86400)return `${Math.floor(diff/3600)}h ago`;
  return `${Math.floor(diff/86400)}d ago`;
}

function statusBadge(status) {
  const map = {
    up:      ['up',      'check-circle-fill', 'Online'],
    down:    ['down',    'x-circle-fill',     'Offline'],
    warning: ['warning', 'exclamation-circle-fill', 'Warning'],
    unknown: ['unknown', 'question-circle-fill', 'Unknown'],
  };
  const [cls, icon, label] = map[status] || map.unknown;
  return `<span class="status-dot ${cls}">
    <i class="bi bi-${icon}"></i>${label}
  </span>`;
}

function iconClass(type) {
  const map = {
    router:       'diagram-3-fill',
    switch:       'hdd-rack-fill',
    server:       'server-fill',
    access_point: 'wifi',
    firewall:     'shield-fill',
    printer:      'printer-fill',
    camera:       'camera-video-fill',
    ups:          'battery-charging',
    unifi:        'diagram-2-fill',
    unknown:      'hdd-fill',
    device:       'hdd-fill',
  };
  return map[type] || 'hdd-fill';
}

// ============================================================
// Toast notifications
// ============================================================
function showToast(msg, type = 'info', duration = 3500) {
  const stack = document.getElementById('toast-stack');
  if (!stack) return;
  const id  = 'toast-' + Date.now();
  const div = document.createElement('div');
  div.className = `nm-toast ${type}`;
  div.id = id;
  const iconMap = { success:'check-circle-fill', danger:'x-circle-fill', warning:'exclamation-triangle-fill', info:'info-circle-fill' };
  div.innerHTML = `<i class="bi bi-${iconMap[type]||'info-circle-fill'}"></i><span>${esc(msg)}</span>`;
  stack.appendChild(div);
  setTimeout(() => { div.style.opacity = '0'; div.style.transition = 'opacity 0.4s'; setTimeout(() => div.remove(), 400); }, duration);
}

// ============================================================
// Alert banner
// ============================================================
function showBanner(msg) {
  const el = document.getElementById('alert-banner');
  const tx = document.getElementById('alert-banner-text');
  if (!el || !tx) return;
  tx.textContent = msg;
  el.classList.remove('d-none');
}
function dismissBanner() {
  const el = document.getElementById('alert-banner');
  if (el) el.classList.add('d-none');
}
