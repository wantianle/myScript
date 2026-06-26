// ---- Elements ----
const statusDot     = document.getElementById('status-dot');
const statusLabel   = document.getElementById('status-label');
const statusLatency = document.getElementById('status-latency');
const toggleInput   = document.getElementById('toggle-connection');
const serverListEl  = document.getElementById('server-list');

// ---- State ----
let currentServerId = '';

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
  refreshStatus();
  refreshServers();

  // Toggle connection
  toggleInput.addEventListener('change', () => {
    const connected = window.go.main.App.ToggleConnection();
    toggleInput.checked = connected;
    updateConnectionUI(connected);
    window.go.main.App.GetStatus().then(s => updateStatusUI(s));
  });

  // Edit config
  document.getElementById('btn-edit').addEventListener('click', () => {
    window.go.main.App.EditConfig();
  });

  // Reload
  document.getElementById('btn-reload').addEventListener('click', () => {
    window.go.main.App.Reload().then(() => {
      refreshStatus();
      refreshServers();
    });
  });

  // Hide panel
  document.getElementById('btn-hide').addEventListener('click', () => {
    window.go.main.App.HidePanel();
  });

  // Auto-hide on blur
  window.addEventListener('blur', () => {
    window.go.main.App.HidePanel();
  });

  // Periodic status refresh
  setInterval(refreshStatus, 3000);
});

// ---- API helpers ----

function refreshStatus() {
  window.go.main.App.GetStatus().then(s => updateStatusUI(s));
}

function refreshServers() {
  window.go.main.App.GetServers().then(servers => {
    currentServerId = '';
    serverListEl.innerHTML = '';
    servers.forEach(s => {
      if (s.selected === 'true') currentServerId = s.id;
      renderServerItem(s);
    });
  });
}

// ---- UI updaters ----

function updateStatusUI(s) {
  updateConnectionUI(s.connected);
  if (s.connected) {
    statusLatency.textContent = s.latency > 0 ? s.latency + 'ms 延迟' : '连接中...';
  } else {
    statusLatency.textContent = '--';
  }
}

function updateConnectionUI(connected) {
  if (connected) {
    statusDot.classList.add('connected');
    statusLabel.textContent = '已连接';
    toggleInput.checked = true;
  } else {
    statusDot.classList.remove('connected');
    statusLabel.textContent = '已断开';
    toggleInput.checked = false;
  }
}

function renderServerItem(s) {
  const item = document.createElement('div');
  item.className = 'server-item' + (s.selected === 'true' ? ' selected' : '');
  item.dataset.serverId = s.id;

  const dot = document.createElement('div');
  dot.className = 'dot';
  item.appendChild(dot);

  const name = document.createElement('div');
  name.className = 'name';
  name.textContent = s.name;
  item.appendChild(name);

  const lat = document.createElement('div');
  lat.className = 'latency';
  lat.textContent = '';
  item.appendChild(lat);

  item.addEventListener('click', () => {
    window.go.main.App.SelectServer(s.id).then(ok => {
      if (ok) refreshServers();
    });
  });

  serverListEl.appendChild(item);
}
