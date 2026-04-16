const AUTH_TOKEN_KEY = 'driftgaugeAuthToken';
let authToken = localStorage.getItem(AUTH_TOKEN_KEY) || '';

function storeAuthToken(token) {
  authToken = token;
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function currentEntriesUserId() {
  return document.querySelector('#entry-form input[name="user_id"]')?.value || 'demo-user';
}

function currentSourcesUserId() {
  return document.querySelector('#source-form input[name="user_id"]')?.value || 'demo-user';
}

async function refreshSources() {
  const userId = currentSourcesUserId();
  const res = await apiFetch(`/ingestion/sources?user_id=${encodeURIComponent(userId)}`);
  const body = await res.json();
  const list = document.getElementById('sources-list');
  list.innerHTML = '';

  if (!body.length) {
    const li = document.createElement('li');
    li.textContent = 'No sources configured yet.';
    list.appendChild(li);
    return;
  }

  for (const source of body) {
    const li = document.createElement('li');
    li.textContent = `${source.label} — ${source.url} — ${source.last_status || 'never run'}`;
    list.appendChild(li);
  }
}

async function apiFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (authToken) {
    headers['X-Auth-Token'] = authToken;
  }
  return fetch(url, { ...options, headers });
}

async function refreshEntries() {
  const userId = currentEntriesUserId();
  const res = await apiFetch(`/entries?user_id=${encodeURIComponent(userId)}&limit=20`);
  const entries = await res.json();
  const list = document.getElementById('entries-list');
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

document.getElementById('register-form').addEventListener('submit', async (event) => {
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
    storeAuthToken(body.token);
  }
  document.getElementById('auth-result').textContent = JSON.stringify(body, null, 2);
});

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
    storeAuthToken(body.token);
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
  document.getElementById('ingestion-result').textContent = JSON.stringify(body, null, 2);
  await refreshSources();
});

document.getElementById('run-ingestion-now').addEventListener('click', async () => {
  const res = await apiFetch('/ingestion/run', { method: 'POST' });
  const body = await res.json();
  document.getElementById('ingestion-result').textContent = JSON.stringify(body, null, 2);
  await refreshSources();
  await refreshEntries();
});

document.getElementById('refresh-sources').addEventListener('click', refreshSources);
document.getElementById('refresh-entries').addEventListener('click', refreshEntries);

refreshEntries();
refreshSources();
