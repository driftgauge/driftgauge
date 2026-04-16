const AUTH_TOKEN_KEY = 'driftgaugeAuthToken';
let authToken = localStorage.getItem(AUTH_TOKEN_KEY) || '';
let authenticatedUsername = '';
let sourceIndex = new Map();

function setPrivateVisibility(isLoggedIn, username = '') {
  const shell = document.getElementById('private-shell');
  const authShell = document.getElementById('auth-shell');
  const sessionBanner = document.getElementById('session-banner');
  const sessionUsername = document.getElementById('session-username');

  if (shell) {
    shell.classList.toggle('hidden', !isLoggedIn);
  }
  if (authShell) {
    authShell.classList.toggle('authenticated', isLoggedIn);
  }
  if (sessionBanner) {
    sessionBanner.classList.toggle('hidden', !isLoggedIn);
  }
  if (sessionUsername) {
    sessionUsername.textContent = isLoggedIn ? `Logged in as ${username || 'authorized user'}` : '';
  }
}

function storeAuthToken(token, username = '') {
  authToken = token;
  authenticatedUsername = username;
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  const authResult = document.getElementById('auth-result');
  if (authResult) {
    authResult.textContent = '';
  }
  setPrivateVisibility(Boolean(token), username);
}

function clearAuthToken(message = '') {
  authToken = '';
  authenticatedUsername = '';
  localStorage.removeItem(AUTH_TOKEN_KEY);
  const authResult = document.getElementById('auth-result');
  if (authResult) {
    authResult.textContent = message;
  }
  setPrivateVisibility(false);
}

function currentEntriesUserId() {
  return document.querySelector('#entry-form input[name="user_id"]')?.value || 'demo-user';
}

function currentSourcesUserId() {
  return document.querySelector('#source-form input[name="user_id"]')?.value || 'demo-user';
}

function renderPublicPlaceholder(label, summary, explanation) {
  document.getElementById('state-label').textContent = label;
  document.getElementById('state-summary').textContent = summary;
  document.getElementById('state-explanation').textContent = explanation;
  document.getElementById('public-stats').innerHTML = '';
  document.getElementById('evidence-gauges').innerHTML = '';
  document.getElementById('source-breakdown').innerHTML = '';
  document.getElementById('recent-evidence').innerHTML = '';
}

function renderGauge(item) {
  return `
    <div class="gauge-card">
      <div class="gauge-header">
        <span>${item.label}</span>
        <strong>${item.display}</strong>
      </div>
      <div class="gauge-track"><span style="width:${item.percent}%"></span></div>
    </div>
  `;
}

function renderSourceBar(item, maxCount) {
  const width = maxCount ? Math.max(8, (item.count / maxCount) * 100) : 0;
  return `
    <div class="source-bar-row">
      <div class="source-meta">
        <span>${item.label}</span>
        <strong>${item.count}</strong>
      </div>
      <div class="source-bar"><span style="width:${width}%"></span></div>
    </div>
  `;
}

function renderStatCard(item) {
  return `
    <div class="stat-card">
      <span>${item.label}</span>
      <strong>${item.value}</strong>
      <small>${item.detail}</small>
    </div>
  `;
}

const sourceForm = document.getElementById('source-form');
const sourceSubmitButton = document.getElementById('source-submit-button');
const sourceResetButton = document.getElementById('source-reset-button');
const defaultSourceFormValues = sourceForm ? {
  source_key: sourceForm.querySelector('input[name="source_key"]').value,
  label: sourceForm.querySelector('input[name="label"]').value,
  url: sourceForm.querySelector('input[name="url"]').value,
  kind: sourceForm.querySelector('select[name="kind"]').value,
  enabled: sourceForm.querySelector('input[name="enabled"]').checked,
} : null;

function setIngestionResult(body) {
  document.getElementById('ingestion-result').textContent = JSON.stringify(body, null, 2);
}

function classifySourceStatus(source) {
  if (!source.enabled) {
    return { key: 'paused', label: 'Paused' };
  }
  if (!source.last_status) {
    return { key: 'empty', label: 'Never run' };
  }
  if (String(source.last_status).startsWith('error:')) {
    return { key: 'failing', label: 'Failing' };
  }
  if (String(source.last_status).startsWith('ok:0')) {
    return { key: 'empty', label: 'No items yet' };
  }
  return { key: 'healthy', label: 'Healthy' };
}

function renderSourceSummary(sources) {
  const summary = document.getElementById('source-summary');
  if (!summary) return;
  if (!sources.length) {
    summary.innerHTML = '';
    return;
  }

  const counts = { healthy: 0, empty: 0, failing: 0, paused: 0 };
  for (const source of sources) {
    counts[classifySourceStatus(source).key] += 1;
  }

  summary.innerHTML = [
    { label: 'Healthy', value: counts.healthy, detail: 'sources returning usable items or valid checks' },
    { label: 'Empty', value: counts.empty, detail: 'sources reachable but not yielding content yet' },
    { label: 'Failing', value: counts.failing, detail: 'sources returning errors or blocked responses' },
    { label: 'Paused', value: counts.paused, detail: 'sources disabled from scheduled runs' },
  ].map(renderStatCard).join('');
}

function resetSourceForm() {
  if (!sourceForm || !defaultSourceFormValues) return;
  sourceForm.querySelector('input[name="source_key"]').value = defaultSourceFormValues.source_key;
  sourceForm.querySelector('input[name="label"]').value = defaultSourceFormValues.label;
  sourceForm.querySelector('input[name="url"]').value = defaultSourceFormValues.url;
  sourceForm.querySelector('select[name="kind"]').value = defaultSourceFormValues.kind;
  sourceForm.querySelector('input[name="enabled"]').checked = defaultSourceFormValues.enabled;
  sourceSubmitButton.textContent = 'Save source';
  sourceResetButton.classList.add('hidden');
}

function populateSourceForm(source) {
  if (!sourceForm) return;
  sourceForm.querySelector('input[name="source_key"]').value = source.source_key;
  sourceForm.querySelector('input[name="label"]').value = source.label;
  sourceForm.querySelector('input[name="url"]').value = source.url;
  sourceForm.querySelector('select[name="kind"]').value = source.kind;
  sourceForm.querySelector('input[name="enabled"]').checked = Boolean(source.enabled);
  sourceSubmitButton.textContent = 'Update source';
  sourceResetButton.classList.remove('hidden');
  sourceForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSourceItem(source) {
  const toggleLabel = source.enabled ? 'Pause' : 'Enable';
  const status = source.last_status || 'never run';
  const statusInfo = classifySourceStatus(source);
  return `
    <li data-source-key="${source.source_key}">
      <div class="source-title-row">
        <div>
          <strong>${source.label}</strong>
          <div>${source.kind.toUpperCase()}</div>
          <div class="source-url">${source.url}</div>
          <div class="source-status">${status}</div>
        </div>
        <span class="status-chip ${statusInfo.key}">${statusInfo.label}</span>
      </div>
      <div class="source-actions">
        <button type="button" data-source-action="edit" data-source-key="${source.source_key}" class="secondary-button">Edit</button>
        <button type="button" data-source-action="toggle" data-source-key="${source.source_key}" class="secondary-button">${toggleLabel}</button>
        <button type="button" data-source-action="run" data-source-key="${source.source_key}">Retry now</button>
        <button type="button" data-source-action="clear" data-source-key="${source.source_key}" class="secondary-button">Clear data</button>
        <button type="button" data-source-action="delete" data-source-key="${source.source_key}" class="secondary-button">Delete</button>
      </div>
    </li>
  `;
}

async function refreshPublicSummary() {
  const userId = currentEntriesUserId();
  const res = await fetch(`/public/summary?user_id=${encodeURIComponent(userId)}`);
  const body = await res.json();
  if (!res.ok) {
    renderPublicPlaceholder('MONITORING UNAVAILABLE', 'Public monitoring metrics could not be loaded.', body.detail || 'Configure a monitored account first.');
    return;
  }

  document.getElementById('state-subject').textContent = body.subject_name;
  document.getElementById('state-label').textContent = body.headline;
  document.getElementById('state-summary').textContent = body.summary;
  document.getElementById('state-explanation').textContent = 'This page shows neutral metrics only, not inferred mood or mental-state output.';
  document.getElementById('public-stats').innerHTML = (body.stats || []).map(renderStatCard).join('');

  const gauges = document.getElementById('evidence-gauges');
  gauges.innerHTML = (body.gauges || []).map(renderGauge).join('') || '<p class="subtle">No evaluation inputs yet.</p>';

  const sourceBreakdown = document.getElementById('source-breakdown');
  const sourceData = body.source_breakdown || [];
  const maxCount = sourceData.reduce((max, item) => Math.max(max, item.count), 0);
  sourceBreakdown.innerHTML = sourceData.map((item) => renderSourceBar(item, maxCount)).join('') || '<p class="subtle">No source activity yet.</p>';

  const recentEvidence = document.getElementById('recent-evidence');
  recentEvidence.innerHTML = '';
  for (const entry of body.recent_activity || []) {
    const li = document.createElement('li');
    li.textContent = `[${entry.created_at}] ${entry.source} — ${entry.word_count} words`;
    recentEvidence.appendChild(li);
  }
  if (!(body.recent_activity || []).length) {
    const li = document.createElement('li');
    li.textContent = 'No recent activity yet.';
    recentEvidence.appendChild(li);
  }
}

async function refreshSources() {
  const list = document.getElementById('sources-list');
  const summary = document.getElementById('source-summary');
  if (!authToken) {
    sourceIndex = new Map();
    if (summary) summary.innerHTML = '';
    list.innerHTML = '<li>Log in to manage monitored sources.</li>';
    return;
  }

  const userId = currentSourcesUserId();
  const res = await apiFetch(`/ingestion/sources?user_id=${encodeURIComponent(userId)}`);
  if (!res.ok) {
    sourceIndex = new Map();
    if (summary) summary.innerHTML = '';
    list.innerHTML = '<li>Log in to manage monitored sources.</li>';
    return;
  }
  const body = await res.json();
  sourceIndex = new Map(body.map((source) => [source.source_key, source]));
  list.innerHTML = '';
  renderSourceSummary(body);

  if (!body.length) {
    const li = document.createElement('li');
    li.textContent = 'No sources configured yet.';
    list.appendChild(li);
    return;
  }

  list.innerHTML = body.map(renderSourceItem).join('');
}

async function handleSourceAction(event) {
  const button = event.target.closest('button[data-source-action]');
  if (!button) return;

  const sourceKey = button.dataset.sourceKey;
  const action = button.dataset.sourceAction;
  const source = sourceIndex.get(sourceKey);
  if (!source) return;

  if (action === 'edit') {
    populateSourceForm(source);
    return;
  }

  if (action === 'toggle') {
    const res = await apiFetch(`/ingestion/sources/${encodeURIComponent(sourceKey)}/toggle?enabled=${String(!source.enabled)}`, { method: 'POST' });
    const body = await res.json();
    setIngestionResult(body);
    await refreshSources();
    await refreshPublicSummary();
    return;
  }

  if (action === 'run') {
    const res = await apiFetch(`/ingestion/sources/${encodeURIComponent(sourceKey)}/run`, { method: 'POST' });
    const body = await res.json();
    setIngestionResult(body);
    await refreshSources();
    await refreshEntries();
    await refreshPublicSummary();
    return;
  }

  if (action === 'clear') {
    if (!window.confirm(`Clear imported data for ${source.label}? This will remove saved entries for this source.`)) {
      return;
    }
    const res = await apiFetch(`/ingestion/sources/${encodeURIComponent(sourceKey)}/clear`, { method: 'POST' });
    const body = await res.json();
    setIngestionResult(body);
    await refreshSources();
    await refreshEntries();
    await refreshPublicSummary();
    return;
  }

  if (action === 'delete') {
    if (!window.confirm(`Delete source ${source.label}?`)) {
      return;
    }
    const res = await apiFetch(`/ingestion/sources/${encodeURIComponent(sourceKey)}`, { method: 'DELETE' });
    const body = await res.json();
    setIngestionResult(body);
    if (sourceForm?.querySelector('input[name="source_key"]')?.value === sourceKey) {
      resetSourceForm();
    }
    await refreshSources();
    await refreshEntries();
    await refreshPublicSummary();
  }
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authToken) {
    headers['X-Auth-Token'] = authToken;
  }
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401 && authToken) {
    clearAuthToken(JSON.stringify({ detail: 'Session expired. Please log in again.' }, null, 2));
  }
  return response;
}

async function restoreSession() {
  if (!authToken) {
    setPrivateVisibility(false);
    return false;
  }

  const res = await apiFetch('/auth/session');
  if (!res.ok) {
    return false;
  }

  const body = await res.json();
  authenticatedUsername = body.username || '';
  setPrivateVisibility(true, authenticatedUsername);
  return true;
}

async function refreshEntries() {
  const list = document.getElementById('entries-list');
  if (!authToken) {
    list.innerHTML = '<li>Log in to view collected entries.</li>';
    return;
  }

  const userId = currentEntriesUserId();
  const res = await apiFetch(`/entries?user_id=${encodeURIComponent(userId)}&limit=20`);
  if (!res.ok) {
    list.innerHTML = '<li>Log in to view collected entries.</li>';
    return;
  }
  const entries = await res.json();
  list.innerHTML = '';

  if (!entries.length) {
    const li = document.createElement('li');
    li.textContent = 'No entries yet.';
    list.appendChild(li);
    return;
  }

  for (const entry of entries) {
    const li = document.createElement('li');
    li.textContent = `[${entry.created_at}] ${entry.source}: ${entry.text}`;
    list.appendChild(li);
  }
}

const registerForm = document.getElementById('register-form');
if (registerForm) {
  registerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (body.token) {
      storeAuthToken(body.token, body.user?.username || body.username || payload.username);
      await refreshEntries();
      await refreshSources();
    }
    document.getElementById('auth-result').textContent = JSON.stringify(body, null, 2);
  });
}

document.getElementById('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  const res = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (body.token) {
    storeAuthToken(body.token, body.username || payload.username);
    await refreshEntries();
    await refreshSources();
  }
  document.getElementById('auth-result').textContent = JSON.stringify(body, null, 2);
});

document.getElementById('entry-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  const res = await apiFetch('/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  document.getElementById('entry-result').textContent = JSON.stringify(body, null, 2);
  await refreshEntries();
  await refreshPublicSummary();
});

document.getElementById('analyze-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.window_size = Number(payload.window_size);
  const res = await apiFetch('/analyze/latest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  const panel = document.getElementById('alert-panel');
  panel.classList.remove('hidden');
  document.getElementById('alert-level').textContent = body.level;
  document.getElementById('alert-score').textContent = body.risk_score;
  document.getElementById('alert-explanation').textContent = body.explanation;
  const ul = document.getElementById('alert-recommendations');
  ul.innerHTML = '';
  for (const item of body.recommendations || []) {
    const li = document.createElement('li');
    li.textContent = item;
    ul.appendChild(li);
  }
  await refreshPublicSummary();
});

const importForm = document.getElementById('import-form');
if (importForm) {
  importForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());
    const res = await apiFetch('/import/files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    document.getElementById('import-result').textContent = JSON.stringify(body, null, 2);
    await refreshEntries();
    await refreshPublicSummary();
  });
}

document.getElementById('privacy-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.retention_days = Number(payload.retention_days);
  payload.allow_file_imports = event.target.querySelector('input[name="allow_file_imports"]').checked;
  const userId = payload.user_id;
  const res = await apiFetch(`/privacy/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  document.getElementById('privacy-result').textContent = JSON.stringify(body, null, 2);
});

document.getElementById('schedule-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.interval_minutes = Number(payload.interval_minutes);
  payload.enabled = event.target.querySelector('input[name="enabled"]').checked;
  const res = await apiFetch('/schedule/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  document.getElementById('schedule-result').textContent = JSON.stringify(body, null, 2);
});

document.getElementById('run-schedule-now').addEventListener('click', async () => {
  const res = await apiFetch('/schedule/run', { method: 'POST' });
  const body = await res.json();
  document.getElementById('schedule-result').textContent = JSON.stringify(body, null, 2);
  await refreshPublicSummary();
});

document.getElementById('alert-settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.email_enabled = event.target.querySelector('input[name="email_enabled"]').checked;
  const userId = payload.user_id;
  const res = await apiFetch(`/alerts/settings/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  document.getElementById('alert-settings-result').textContent = JSON.stringify(body, null, 2);
});

document.getElementById('source-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.enabled = event.target.querySelector('input[name="enabled"]').checked;
  const res = await apiFetch('/ingestion/sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  setIngestionResult(body);
  resetSourceForm();
  await refreshSources();
  await refreshPublicSummary();
});

document.getElementById('run-ingestion-now').addEventListener('click', async () => {
  const res = await apiFetch('/ingestion/run', { method: 'POST' });
  const body = await res.json();
  setIngestionResult(body);
  await refreshSources();
  await refreshEntries();
  await refreshPublicSummary();
});

document.getElementById('run-historical-backfill').addEventListener('click', async () => {
  const res = await apiFetch('/ingestion/backfill?max_pages=25&max_items=250', { method: 'POST' });
  const body = await res.json();
  setIngestionResult(body);
  await refreshSources();
  await refreshEntries();
  await refreshPublicSummary();
});

document.getElementById('refresh-sources').addEventListener('click', refreshSources);
document.getElementById('refresh-entries').addEventListener('click', refreshEntries);
document.getElementById('sources-list').addEventListener('click', handleSourceAction);
sourceResetButton?.addEventListener('click', resetSourceForm);
document.getElementById('logout-button').addEventListener('click', async () => {
  if (authToken) {
    await apiFetch('/auth/logout', { method: 'POST' });
  }
  clearAuthToken();
  await refreshEntries();
  await refreshSources();
});

async function initializeApp() {
  await restoreSession();
  await refreshEntries();
  await refreshSources();
  await refreshPublicSummary();
}

initializeApp();
