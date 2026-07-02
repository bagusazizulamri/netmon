/* ============================================================
   NetMon — main.js  (shared across all pages)
   ============================================================ */

// ---- Socket.IO setup ----
const socket = io({ transports: ['polling', 'websocket'] });

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
socket.on('alert_update', (d) => {
  if (typeof window.onAlertUpdate === 'function') window.onAlertUpdate(d);
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

function formatBandwidth(bps) {
  if (bps === null || bps === undefined || isNaN(bps) || bps === '') return '—';
  const val = parseFloat(bps);
  if (val === 0) return '0 bps';
  const commaFormatted = Math.round(val).toLocaleString('id-ID');
  if (val >= 1000000000) {
    const formattedVal = (val / 1000000000).toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${formattedVal} Gbps (${commaFormatted} bps)`;
  }
  if (val >= 1000000) {
    const formattedVal = (val / 1000000).toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${formattedVal} Mbps (${commaFormatted} bps)`;
  }
  if (val >= 1000) {
    const formattedVal = (val / 1000).toLocaleString('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${formattedVal} Kbps (${commaFormatted} bps)`;
  }
  return `${Math.round(val).toLocaleString('id-ID')} bps`;
}

function formatPercent(val) {
  if (val === null || val === undefined || isNaN(val) || val === '') return '—';
  return `${parseFloat(val).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}

function formatTemp(val) {
  if (val === null || val === undefined || isNaN(val) || val === '') return '—';
  return `${parseFloat(val).toLocaleString('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}°C`;
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

// ============================================================
// Global Device Details Real-time Polling & Charting
// ============================================================
let detailModal;
let detailPollInterval = null;
let activeDetailDeviceId = null;
let activeDetailDeviceType = null;
let trafficChartInstance = null;
let interfaceTrafficData = {};
let chartLabels = [];
let chartRxData = [];
let chartTxData = [];

document.addEventListener('DOMContentLoaded', () => {
  const modalEl = document.getElementById('detailModal');
  if (modalEl) {
    detailModal = new bootstrap.Modal(modalEl);
  }
});

function openDeviceDetail(id) {
  activeDetailDeviceId = id;
  interfaceTrafficData = {};
  chartLabels = [];
  chartRxData = [];
  chartTxData = [];
  
  const select = document.getElementById('det-iface-select');
  if (select) select.innerHTML = '<option value="">Loading ports…</option>';
  
  const cpuBar = document.getElementById('det-cpu-bar');
  if (cpuBar) cpuBar.style.width = '0%';
  const cpuVal = document.getElementById('det-cpu-val');
  if (cpuVal) cpuVal.textContent = '—';
  
  const memBar = document.getElementById('det-mem-bar');
  if (memBar) memBar.style.width = '0%';
  const memVal = document.getElementById('det-mem-val');
  if (memVal) memVal.textContent = '—';
  
  const tempBar = document.getElementById('det-temp-bar');
  if (tempBar) tempBar.style.width = '0%';
  const tempVal = document.getElementById('det-temp-val');
  if (tempVal) tempVal.textContent = '—';
  
  const tbody = document.getElementById('det-interfaces-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4"><i class="bi bi-arrow-repeat spin me-1"></i>Loading interface data…</td></tr>';
  
  // Try to find the device locally first
  let dev = null;
  if (typeof allDevices !== 'undefined' && Array.isArray(allDevices)) {
    dev = allDevices.find(x => x.id === id);
  }
  
  if (trafficChartInstance) {
    trafficChartInstance.destroy();
    trafficChartInstance = null;
  }

  const startPolling = () => {
    initChart();
    if (detailModal) detailModal.show();
    fetchRealtimeStats();
    if (detailPollInterval) clearInterval(detailPollInterval);
    detailPollInterval = setInterval(fetchRealtimeStats, 3000);
    loadHistoryInterfaces(activeDetailDeviceId);
    loadHistoryChart(activeDetailDeviceId, null, 1);
  };

  if (dev) {
    activeDetailDeviceType = dev.type;
    populateBasicFields(dev);
    startPolling();
  } else {
    // Fetch device info
    fetch(`/api/devices/${id}`)
      .then(r => r.json())
      .then(data => {
        activeDetailDeviceType = data.type;
        populateBasicFields(data);
        startPolling();
      })
      .catch(err => console.error("Error loading device metadata:", err));
  }
}

function populateBasicFields(dev) {
  if (!dev) return;
  const title = document.getElementById('det-title');
  if (title) title.textContent = dev.name;
  
  const statusBadgeEl = document.getElementById('det-status-badge');
  if (statusBadgeEl) {
    statusBadgeEl.className = `badge bg-${dev.status === 'up' ? 'success' : 'danger'}`;
    statusBadgeEl.textContent = dev.status === 'up' ? 'ONLINE' : 'OFFLINE';
  }
  
  const ipEl = document.getElementById('det-ip');
  if (ipEl) ipEl.textContent = dev.ip;
  
  const vendorModelEl = document.getElementById('det-vendor-model');
  if (vendorModelEl) vendorModelEl.textContent = `${dev.vendor || 'Unknown'} ${dev.model || '—'}`;
  
  const sysNameEl = document.getElementById('det-sys-name');
  if (sysNameEl) sysNameEl.textContent = dev.sys_name || '—';
  
  const uptimeEl = document.getElementById('det-uptime');
  if (uptimeEl) uptimeEl.textContent = dev.uptime || '—';
  
  const descEl = document.getElementById('det-desc');
  if (descEl) descEl.textContent = dev.description || '—';
}

function closeDetailModal() {
  if (detailPollInterval) {
    clearInterval(detailPollInterval);
    detailPollInterval = null;
  }
  if (_histChart) {
    _histChart.destroy();
    _histChart = null;
  }
  activeDetailDeviceId = null;
}

function initChart() {
  const chartCanvas = document.getElementById('trafficChart');
  if (!chartCanvas) return;
  
  const ctx = chartCanvas.getContext('2d');
  const now = new Date();
  for (let i = 9; i >= 0; i--) {
    const t = new Date(now.getTime() - i * 3000);
    chartLabels.push(t.toLocaleTimeString());
    chartRxData.push(0);
    chartTxData.push(0);
  }

  const isLight = document.body.classList.contains('light-theme');
  const tickColor = isLight ? '#6e6e73' : '#8b949e';
  const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';
  
  trafficChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: chartLabels,
      datasets: [
        {
          label: 'Inbound (Download)',
          data: chartRxData,
          borderColor: '#58a6ff',
          backgroundColor: 'rgba(88, 166, 255, 0.1)',
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 2
        },
        {
          label: 'Outbound (Upload)',
          data: chartTxData,
          borderColor: '#bc8cff',
          backgroundColor: 'rgba(188, 140, 255, 0.1)',
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          pointRadius: 2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: tickColor, font: { size: 10 } }
        },
        y: {
          grid: { color: gridColor },
          ticks: {
            color: tickColor,
            font: { size: 10 },
            callback: function(value) {
              return formatBandwidthSimple(value);
            }
          }
        }
      }
    }
  });
}

function formatBandwidthSimple(bps) {
  if (bps === 0) return '0 bps';
  const val = parseFloat(bps);
  if (val >= 1000000000) return `${(val / 1000000000).toFixed(1)} Gbps`;
  if (val >= 1000000) return `${(val / 1000000).toFixed(1)} Mbps`;
  if (val >= 1000) return `${(val / 1000).toFixed(1)} Kbps`;
  return `${val.toFixed(0)} bps`;
}

function fetchRealtimeStats() {
  if (!activeDetailDeviceId) return;
  
  fetch(`/api/devices/${activeDetailDeviceId}/realtime_stats`)
    .then(r => r.json())
    .then(res => {
      if (res.status !== 'success' || !activeDetailDeviceId) return;
      
      const uptimeEl = document.getElementById('det-uptime');
      if (uptimeEl && res.uptime) uptimeEl.textContent = res.uptime;
      
      const titleEl = document.getElementById('det-title');
      if (titleEl && res.sys_name) titleEl.textContent = res.sys_name;
      
      const descEl = document.getElementById('det-desc');
      if (descEl && res.description) descEl.textContent = res.description;
      
      updateResourceProgress('det-cpu-bar', 'det-cpu-val', res.cpu_usage, '%');
      updateResourceProgress('det-mem-bar', 'det-mem-val', res.memory_usage, '%');
      updateResourceProgress('det-temp-bar', 'det-temp-val', res.temperature, '°C');

      const isClientDev = res.client_count !== null && res.client_count !== undefined;
      const rtHeader = document.querySelector('#detailModal h6.m-0');
      if (rtHeader) {
        rtHeader.innerHTML = isClientDev
          ? '<i class="bi bi-people-fill me-2 text-accent"></i>Connected Clients'
          : '<i class="bi bi-activity me-2 text-accent"></i>Real-time Traffic';
      }
      
      const legIn = document.getElementById('det-traffic-in');
      const legOut = document.getElementById('det-traffic-out');
      const legInWrapper = legIn ? legIn.closest('div') : null;
      const legOutWrapper = legOut ? legOut.closest('div') : null;
      
      if (isClientDev) {
        if (legIn) {
          legIn.textContent = `${Math.round(res.client_count)} clients`;
          if (legInWrapper) {
            const labelSpan = legInWrapper.querySelector('.text-xs');
            if (labelSpan) labelSpan.firstChild.textContent = 'Clients: ';
          }
        }
        if (legOutWrapper) legOutWrapper.style.display = 'none';
        
        const selectWrapper = document.getElementById('det-iface-select-wrapper');
        const interfacesCard = document.getElementById('det-interfaces-card');
        const tbody = document.getElementById('det-interfaces-tbody');
        
        if (selectWrapper) selectWrapper.style.setProperty('display', 'none', 'important');
        if (interfacesCard) {
          interfacesCard.style.setProperty('display', 'block', 'important');
          
          // Update title to Connected Clients List
          const cardTitle = interfacesCard.querySelector('h6');
          if (cardTitle) {
            cardTitle.innerHTML = '<i class="bi bi-people-fill me-2 text-accent"></i>Connected Clients List';
          }
          
          // Update headers
          const thead = interfacesCard.querySelector('thead');
          if (thead) {
            thead.innerHTML = `
              <tr>
                <th class="border-0">Client Name</th>
                <th class="border-0">IP Address</th>
                <th class="border-0">Connection</th>
                <th class="border-0">Signal</th>
                <th class="border-0">MAC Address</th>
              </tr>
            `;
          }
          
          // Render clients in tbody
          if (tbody) {
            const clients = res.clients || [];
            if (clients.length === 0) {
              tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No clients connected.</td></tr>';
            } else {
              tbody.innerHTML = clients.map(c => `
                <tr>
                  <td class="fw-500">${esc(c.name)}</td>
                  <td class="mono-sm">${esc(c.ip)}</td>
                  <td><span class="badge bg-secondary text-xs">${esc(c.essid)}</span></td>
                  <td class="mono-sm">${c.signal !== null ? `${c.signal} dBm` : '—'}</td>
                  <td class="mono-sm text-muted">${esc(c.mac)}</td>
                </tr>
              `).join('');
            }
          }
        }
        
        if (trafficChartInstance) {
          const timeStr = new Date().toLocaleTimeString();
          trafficChartInstance.data.datasets[0].label = 'Clients';
          trafficChartInstance.data.datasets[1].hidden = true;
          trafficChartInstance.options.scales.y.ticks.callback = function(val) { return val; };
          
          chartLabels.push(timeStr);
          chartRxData.push(res.client_count);
          chartTxData.push(0);
          
          if (chartLabels.length > 10) {
            chartLabels.shift();
            chartRxData.shift();
            chartTxData.shift();
          }
          trafficChartInstance.update('none');
        }
        return;
      } else {
        if (legOutWrapper) legOutWrapper.style.display = 'block';
        if (legInWrapper) {
          const labelSpan = legInWrapper.querySelector('.text-xs');
          if (labelSpan) labelSpan.firstChild.textContent = 'Inbound: ';
        }
        if (trafficChartInstance) {
          trafficChartInstance.data.datasets[0].label = 'Inbound (Download)';
          trafficChartInstance.data.datasets[1].hidden = false;
          trafficChartInstance.options.scales.y.ticks.callback = function(value) {
            return formatBandwidthSimple(value);
          };
        }
        
        // Restore standard interface headers
        const interfacesCard = document.getElementById('det-interfaces-card');
        if (interfacesCard) {
          const cardTitle = interfacesCard.querySelector('h6');
          if (cardTitle) {
            cardTitle.innerHTML = '<i class="bi bi-ethernet me-2 text-accent"></i>Interface Status';
          }
          const thead = interfacesCard.querySelector('thead');
          if (thead) {
            thead.innerHTML = `
              <tr>
                <th class="border-0">Port Name</th>
                <th class="border-0">Status</th>
                <th class="border-0">Port Speed</th>
                <th class="border-0">Received (Rx)</th>
                <th class="border-0">Transmitted (Tx)</th>
              </tr>
            `;
          }
        }
      }
      
      const interfaces = res.interfaces || [];
      const select = document.getElementById('det-iface-select');
      const tbody = document.getElementById('det-interfaces-tbody');
      const selectWrapper = document.getElementById('det-iface-select-wrapper');
      const interfacesCard = document.getElementById('det-interfaces-card');
      
      const typeLower = String(activeDetailDeviceType || '').toLowerCase();
      const titleText = String(document.getElementById('det-title')?.textContent || '').toLowerCase();
      const modelText = String(document.getElementById('det-vendor-model')?.textContent || '').toLowerCase();
      
      const hasInterfaces = interfaces.length > 0;
      
      const showPortList = (
        hasInterfaces && !new Set(['printer', 'camera', 'ups', 'server']).has(activeDetailDeviceType || '')
      );
      
      // Show interface selector only for routers/switches with multiple ports
      if (selectWrapper) {
        selectWrapper.style.setProperty('display', (showPortList && hasInterfaces) ? 'flex' : 'none', 'important');
      }
      // Show interface table only for routers/switches
      if (interfacesCard) {
        interfacesCard.style.setProperty('display', (showPortList && hasInterfaces) ? 'block' : 'none', 'important');
      }
      
      if (!showPortList || !hasInterfaces) {
        // Non-router/switch or no interfaces: sum all traffic for global chart
        if (hasInterfaces) {
          const globalIface = {
            index: 9999,
            name: 'Global Traffic',
            rx_bytes: interfaces.reduce((sum, item) => sum + (item.rx_bytes || 0), 0),
            tx_bytes: interfaces.reduce((sum, item) => sum + (item.tx_bytes || 0), 0)
          };
          updateChartData(globalIface);
        }
        return;
      }
      
      if (!select || !tbody) return;
      
      if (interfaces.length === 0) {
        select.innerHTML = '<option value="">No interfaces</option>';
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">No ports found on this device. Make sure SNMP is enabled and working.</td></tr>';
        return;
      }
      
      const prevSelectedIdx = select.value;
      const existingRows = tbody.querySelectorAll('tr[data-index]');
      const isInitialBuild = (existingRows.length !== interfaces.length);
      
      if (isInitialBuild) {
        // Build select options
        let optHtml = '';
        interfaces.forEach(iface => {
          const isSelected = (prevSelectedIdx === String(iface.index)) ? 'selected' : '';
          const statusLabel = iface.status === 'up' ? '🟢' : '🔴';
          optHtml += `<option value="${iface.index}" ${isSelected}>${statusLabel} ${esc(iface.name)}</option>`;
        });
        select.innerHTML = optHtml;
        
        // Build table body
        tbody.innerHTML = interfaces.map(iface => `
          <tr data-index="${iface.index}" onclick="selectInterface(${iface.index})" style="cursor: pointer;" class="${prevSelectedIdx === String(iface.index) ? 'table-active' : ''}">
            <td class="fw-500">${esc(iface.name)}</td>
            <td>${iface.status === 'up' ? '<span class="text-success fw-600">UP</span>' : '<span class="text-danger">DOWN</span>'}</td>
            <td class="mono-sm">${formatBandwidthSimple(iface.speed)}</td>
            <td class="mono-sm text-muted">${(iface.rx_bytes || 0).toLocaleString()} B</td>
            <td class="mono-sm text-muted">${(iface.tx_bytes || 0).toLocaleString()} B</td>
          </tr>
        `).join('');
      } else {
        // Update existing elements inline to prevent layout shifts/scroll resets
        interfaces.forEach(iface => {
          const row = tbody.querySelector(`tr[data-index="${iface.index}"]`);
          if (row) {
            // Update status text
            const statusCell = row.cells[1];
            const statusHtml = iface.status === 'up' ? '<span class="text-success fw-600">UP</span>' : '<span class="text-danger">DOWN</span>';
            if (statusCell.innerHTML !== statusHtml) statusCell.innerHTML = statusHtml;
            
            // Update speed text
            const speedText = formatBandwidthSimple(iface.speed);
            if (row.cells[2].textContent !== speedText) row.cells[2].textContent = speedText;
            
            // Update Rx Bytes text
            const rxText = `${(iface.rx_bytes || 0).toLocaleString()} B`;
            if (row.cells[3].textContent !== rxText) row.cells[3].textContent = rxText;
            
            // Update Tx Bytes text
            const txText = `${(iface.tx_bytes || 0).toLocaleString()} B`;
            if (row.cells[4].textContent !== txText) row.cells[4].textContent = txText;
          }
        });
      }
      
      let activeIdx = parseInt(select.value);
      if (isNaN(activeIdx) && interfaces.length > 0) {
        activeIdx = interfaces[0].index;
        select.value = activeIdx;
      }
      
      const activeIface = interfaces.find(x => x.index === activeIdx);
      if (activeIface) {
        updateChartData(activeIface);
      }
    })
    .catch(err => console.error("Error fetching realtime stats:", err));
}

function updateResourceProgress(barId, valId, val, unit) {
  const bar = document.getElementById(barId);
  const text = document.getElementById(valId);
  if (!bar || !text) return;
  
  if (val !== null && val !== undefined) {
    const fVal = parseFloat(val);
    bar.style.width = `${Math.min(100, Math.max(0, fVal))}%`;
    text.textContent = `${fVal.toFixed(1)}${unit}`;
  } else {
    bar.style.width = '0%';
    text.textContent = '—';
  }
}

function selectInterface(idx) {
  const select = document.getElementById('det-iface-select');
  if (select) {
    select.value = idx;
    onInterfaceChange();
  }
}

function onInterfaceChange() {
  const select = document.getElementById('det-iface-select');
  const tbody = document.getElementById('det-interfaces-tbody');
  if (!select || !tbody) return;
  
  const activeIdx = select.value;
  
  Array.from(tbody.rows).forEach(row => {
    const rowIdx = row.dataset.index;
    if (rowIdx === String(activeIdx)) {
      row.classList.add('table-active');
    } else {
      row.classList.remove('table-active');
    }
  });
  
  // Reset chart rolling datasets for the new interface to avoid draw lines connecting previous metrics
  if (trafficChartInstance) {
    chartRxData.fill(0);
    chartTxData.fill(0);
    trafficChartInstance.update('none');
  }
}

function updateChartData(iface) {
  const now = new Date();
  const timeStr = now.toLocaleTimeString();
  const currentTimestamp = now.getTime();
  
  let rxSpeed = 0;
  let txSpeed = 0;
  
  const ifName = iface.name;
  const history = interfaceTrafficData[ifName];
  
  if (history) {
    const dt = (currentTimestamp - history.time) / 1000.0;
    if (dt >= 1.0) {
      let is64bit = (history.rx > 4294967295 || iface.rx_bytes > 4294967295 ||
                     history.tx > 4294967295 || iface.tx_bytes > 4294967295);
      
      let diffRx = iface.rx_bytes - history.rx;
      let diffTx = iface.tx_bytes - history.tx;
      
      if (diffRx < 0) {
        if (is64bit) {
          diffRx = 0;
        } else {
          if (history.rx > 3000000000) {
            diffRx += Math.pow(2, 32);
          } else {
            diffRx = 0;
          }
        }
      }
      
      if (diffTx < 0) {
        if (is64bit) {
          diffTx = 0;
        } else {
          if (history.tx > 3000000000) {
            diffTx += Math.pow(2, 32);
          } else {
            diffTx = 0;
          }
        }
      }
      
      if (diffRx >= 0 && diffTx >= 0) {
        rxSpeed = (diffRx * 8) / dt;
        txSpeed = (diffTx * 8) / dt;
        
        // Spike protection: ignore values that are physically impossible (e.g. > 100 Gbps)
        if (rxSpeed > 100e9) rxSpeed = 0;
        if (txSpeed > 100e9) txSpeed = 0;
      }
    }
  }
  
  interfaceTrafficData[ifName] = {
    rx: iface.rx_bytes,
    tx: iface.tx_bytes,
    time: currentTimestamp
  };
  
  const txIn = document.getElementById('det-traffic-in');
  if (txIn) txIn.textContent = formatBandwidth(rxSpeed);
  const txOut = document.getElementById('det-traffic-out');
  if (txOut) txOut.textContent = formatBandwidth(txSpeed);
  
  if (trafficChartInstance) {
    chartLabels.push(timeStr);
    chartRxData.push(rxSpeed);
    chartTxData.push(txSpeed);
    
    if (chartLabels.length > 10) {
      chartLabels.shift();
      chartRxData.shift();
      chartTxData.shift();
    }
    
    trafficChartInstance.update('none');
  }
}

// ── State untuk history chart ──
let _histHours = 1;
let _histIface = null;
let _histChart = null;

function loadHistoryChart(deviceId, ifaceName, hours) {
  if (!deviceId) return;
  if (hours !== undefined) _histHours = hours;
  if (ifaceName !== undefined) _histIface = ifaceName;
  const url = `/api/devices/${deviceId}/traffic_history?hours=${_histHours}` +
              (_histIface ? `&iface=${encodeURIComponent(_histIface)}` : '');
  fetch(url).then(r => r.json()).then(res => {
    if (res.status !== 'success') return;
    const pts    = res.points || [];
    const fmt    = _histHours <= 1
      ? d => new Date(d).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'})
      : d => new Date(d).toLocaleString([],{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
    const labels = pts.map(p => { try { return fmt(p.ts); } catch { return p.ts; } });
    const rxData = pts.map(p => p.rx_bps || 0);
    const txData = pts.map(p => p.tx_bps || 0);
    const canvas = document.getElementById('historyChart');
    if (!canvas) return;

    const isClient = res.is_client_chart === true;
    const labelFmt = isClient 
      ? ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y} clients`
      : ctx => ` ${ctx.dataset.label}: ${formatBandwidthSimple(ctx.parsed.y)}`;
      
    const yTickFmt = isClient 
      ? v => v + ' clients'
      : v => formatBandwidthSimple(v);

    const histIfaceSelect = document.getElementById('hist-iface-select');
    if (histIfaceSelect) {
      histIfaceSelect.style.display = isClient ? 'none' : 'block';
    }
    const histTitle = document.querySelector('#history-chart-panel .panel-header > span');
    if (histTitle) {
      histTitle.innerHTML = isClient 
        ? '<i class="bi bi-people-fill me-2 text-accent"></i>Client History'
        : '<i class="bi bi-graph-up-arrow me-2 text-accent"></i>Traffic History';
    }

    if (_histChart) {
      _histChart.data.labels = labels;
      _histChart.data.datasets[0].data = rxData;
      _histChart.data.datasets[1].data = txData;
      _histChart.data.datasets[0].label = isClient ? 'Connected Clients' : 'RX (Inbound)';
      _histChart.data.datasets[1].hidden = isClient;
      _histChart.options.plugins.tooltip.callbacks.label = labelFmt;
      _histChart.options.scales.y.ticks.callback = yTickFmt;
      _histChart.options.plugins.legend.display = !isClient;
      _histChart.update('none');
    } else {
      const isLight = document.body.classList.contains('light-theme');
      const tickColor = isLight ? '#6e6e73' : '#8b949e';
      const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';

      _histChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets: [
          { label: isClient ? 'Connected Clients' : 'RX (Inbound)',  data:rxData, borderColor:'#58a6ff',
            backgroundColor:'rgba(88,166,255,0.12)', fill:true, tension:0.3,
            borderWidth:2, pointRadius:1 },
          { label:'TX (Outbound)', data:txData, borderColor:'#bc8cff',
            backgroundColor:'rgba(188,140,255,0.12)', fill:true, tension:0.3,
            borderWidth:2, pointRadius:1, hidden: isClient }
        ]},
        options: {
          responsive:true, maintainAspectRatio:false, animation:false,
          plugins: {
            legend:{ display:!isClient, labels:{color:tickColor,font:{size:11}} },
            tooltip:{ callbacks:{ label: labelFmt } }
          },
          scales: {
            x:{ grid:{display:false}, ticks:{color:tickColor,font:{size:10},maxTicksLimit:8,maxRotation:0} },
            y:{ grid:{color:gridColor}, ticks:{color:tickColor,font:{size:10},
                callback: yTickFmt } }
          }
        }
      });
    }
    const noData = document.getElementById('hist-no-data');
    if (noData) noData.style.display = pts.length === 0 ? '' : 'none';
  }).catch(err => console.warn('[History]', err));
}

function loadHistoryInterfaces(deviceId) {
  fetch(`/api/devices/${deviceId}/traffic_interfaces`)
    .then(r => r.json())
    .then(res => {
      const sel = document.getElementById('hist-iface-select');
      if (!sel) return;
      sel.innerHTML = '<option value="">Semua interface (agregat)</option>' +
        (res.interfaces || []).map(i => `<option value="${esc(i.name)}">${esc(i.name)}</option>`).join('');
    }).catch(()=>{});
}

function exportHistoryChart() {
  if (!_histChart) { showToast('Belum ada data grafik', 'warning'); return; }
  const a    = document.createElement('a');
  const name = document.getElementById('det-title')?.textContent || 'device';
  a.download = `traffic_${name.replace(/\s+/g,'_')}_${_histHours}h.png`;
  a.href     = _histChart.toBase64Image('image/png', 1.0);
  a.click();
}

// ---- Day/Night (Light/Dark) Theme Toggle ----
document.addEventListener('DOMContentLoaded', () => {
  const themeToggleBtn = document.getElementById('theme-toggle-btn');
  if (!themeToggleBtn) return;

  const toggleIcon = document.getElementById('toggle-icon');
  const toggleText = document.getElementById('toggle-text');
  const themeIndicator = document.getElementById('theme-icon-indicator');

  function updateChartsTheme(isLight) {
    const tickColor = isLight ? '#6e6e73' : '#8b949e';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';

    if (trafficChartInstance) {
      if (trafficChartInstance.options && trafficChartInstance.options.scales) {
        if (trafficChartInstance.options.scales.x && trafficChartInstance.options.scales.x.ticks) {
          trafficChartInstance.options.scales.x.ticks.color = tickColor;
        }
        if (trafficChartInstance.options.scales.y) {
          if (trafficChartInstance.options.scales.y.ticks) trafficChartInstance.options.scales.y.ticks.color = tickColor;
          if (trafficChartInstance.options.scales.y.grid) trafficChartInstance.options.scales.y.grid.color = gridColor;
        }
        trafficChartInstance.update();
      }
    }
    if (_histChart) {
      if (_histChart.options && _histChart.options.scales) {
        if (_histChart.options.scales.x) {
          if (_histChart.options.scales.x.ticks) _histChart.options.scales.x.ticks.color = tickColor;
        }
        if (_histChart.options.scales.y) {
          if (_histChart.options.scales.y.ticks) _histChart.options.scales.y.ticks.color = tickColor;
          if (_histChart.options.scales.y.grid) _histChart.options.scales.y.grid.color = gridColor;
        }
        if (_histChart.options.plugins && _histChart.options.plugins.legend && _histChart.options.plugins.legend.labels) {
          _histChart.options.plugins.legend.labels.color = tickColor;
        }
        _histChart.update();
      }
    }
  }

  function updateThemeUI(isLight) {
    if (isLight) {
      document.body.classList.add('light-theme');
      if (toggleIcon) {
        toggleIcon.className = 'bi bi-moon-stars-fill';
      }
      if (toggleText) {
        toggleText.textContent = 'Dark';
      }
      if (themeIndicator) {
        themeIndicator.className = 'bi bi-sun-fill text-warning';
      }
    } else {
      document.body.classList.remove('light-theme');
      if (toggleIcon) {
        toggleIcon.className = 'bi bi-brightness-high-fill';
      }
      if (toggleText) {
        toggleText.textContent = 'Light';
      }
      if (themeIndicator) {
        themeIndicator.className = 'bi bi-moon-stars-fill';
      }
    }
    updateChartsTheme(isLight);
  }

  // Initial check based on class applied by fast-path script in body
  const isLight = document.body.classList.contains('light-theme');
  updateThemeUI(isLight);

  themeToggleBtn.addEventListener('click', () => {
    const isCurrentlyLight = document.body.classList.contains('light-theme');
    const newLight = !isCurrentlyLight;
    localStorage.setItem('theme', newLight ? 'light' : 'dark');
    updateThemeUI(newLight);
  });
});

window.showConfirm = function(title, message, onConfirm) {
  const overlay = document.createElement('div');
  overlay.className = 'custom-confirm-overlay';
  
  const dialog = document.createElement('div');
  dialog.className = 'custom-confirm-dialog';
  
  const icon = document.createElement('div');
  icon.className = 'custom-confirm-icon';
  icon.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i>';
  
  const titleEl = document.createElement('h3');
  titleEl.className = 'custom-confirm-title';
  titleEl.textContent = title;
  
  const messageEl = document.createElement('p');
  messageEl.className = 'custom-confirm-message';
  messageEl.textContent = message;
  
  const buttons = document.createElement('div');
  buttons.className = 'custom-confirm-buttons';
  
  const btnCancel = document.createElement('button');
  btnCancel.className = 'btn-nm btn-confirm-cancel';
  btnCancel.textContent = 'Cancel';
  btnCancel.onclick = () => {
    overlay.classList.remove('active');
    setTimeout(() => overlay.remove(), 200);
  };
  
  const btnConfirm = document.createElement('button');
  btnConfirm.className = 'btn-nm btn-confirm-danger';
  btnConfirm.textContent = 'Confirm';
  btnConfirm.onclick = () => {
    overlay.classList.remove('active');
    setTimeout(() => {
      overlay.remove();
      if (typeof onConfirm === 'function') onConfirm();
    }, 200);
  };
  
  buttons.appendChild(btnCancel);
  buttons.appendChild(btnConfirm);
  
  dialog.appendChild(icon);
  dialog.appendChild(titleEl);
  dialog.appendChild(messageEl);
  dialog.appendChild(buttons);
  overlay.appendChild(dialog);
  
  document.body.appendChild(overlay);
  
  setTimeout(() => {
    overlay.classList.add('active');
  }, 10);
};
