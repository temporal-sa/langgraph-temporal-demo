// Chat UI for the support agent. Vanilla JS, no build step.
// Talks to whichever gateway the selected backend preset points at.

const $ = (id) => document.getElementById(id);
const BACKEND_STORAGE_KEY = 'support-agent.backend';
const TOKEN_STORAGE_KEY = 'support-agent.demoToken';

let conversationId = null;
let activeBackendId = null;
let activeBackend = null;
let approvalPending = false;
let turnInterrupted = false;
let conversationStatus = null;
let demoControls = null;
let controlsOpen = false;
let controlsLoading = false;

const FALLBACK_BACKENDS = {
  langgraph: {
    label: 'LangGraph standalone',
    url: 'http://localhost:8001',
    poweredBy: 'Powered by LangGraph',
    conversationIdLabel: 'conversationId',
    conversationLinkBase: '',
  },
};

const BACKENDS = normalizeBackends(window.AGENT_BACKENDS);

function normalizeBackends(configured) {
  const source =
    configured && Object.keys(configured).length
      ? configured
      : window.BACKEND_URL
        ? {
            configured: {
              label: 'Configured backend',
              url: window.BACKEND_URL,
              poweredBy: window.AGENT_POWERED_BY || 'Powered by the agent backend',
              conversationIdLabel: window.CONVERSATION_ID_LABEL || 'conversationId',
              conversationLinkBase: window.CONVERSATION_LINK_BASE || '',
            },
          }
        : FALLBACK_BACKENDS;

  return Object.fromEntries(
    Object.entries(source).map(([id, backend]) => [
      id,
      {
        id,
        label: backend.label || id,
        url: (backend.url || '').replace(/\/$/, ''),
        poweredBy: backend.poweredBy || 'Powered by the agent backend',
        conversationIdLabel: backend.conversationIdLabel || 'conversationId',
        conversationLinkBase: (backend.conversationLinkBase || '').replace(/\/$/, ''),
      },
    ]),
  );
}

function storageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore private-window or file:// storage failures.
  }
}

function tokenStorageGet() {
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function tokenStorageSet(value) {
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, value);
  } catch {
    // Ignore private-window or file:// storage failures.
  }
}

function demoToken() {
  const url = new URL(window.location.href);
  const requested = url.searchParams.get('token') || url.searchParams.get('access_token');
  if (requested) {
    tokenStorageSet(requested);
    url.searchParams.delete('token');
    url.searchParams.delete('access_token');
    window.history.replaceState(null, '', url);
    return requested;
  }
  return tokenStorageGet() || '';
}

function initialBackendId() {
  const requested = new URLSearchParams(window.location.search).get('backend');
  const configured = window.DEFAULT_AGENT_BACKEND || window.DEFAULT_BACKEND;
  for (const id of [requested, storageGet(BACKEND_STORAGE_KEY), configured]) {
    if (id && BACKENDS[id]) return id;
  }
  return Object.keys(BACKENDS)[0];
}

function selectBackend(id, { persist = true, updateUrl = true } = {}) {
  if (!BACKENDS[id]) return;
  activeBackendId = id;
  activeBackend = BACKENDS[id];
  if (persist) storageSet(BACKEND_STORAGE_KEY, id);
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set('backend', id);
    window.history.replaceState(null, '', url);
  }
  applyConfig();
  if (controlsOpen) loadDemoControls();
}

// ── tiny fetch helper ────────────────────────────────────────────────────────
async function call(method, path, body) {
  const token = demoToken();
  const headers = { 'Content-Type': 'application/json' };
  if (token) {
    headers['X-Demo-Token'] = token;
  }
  const res = await fetch(activeBackend.url + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if (res.status === 401) {
      throw new Error('Demo access token required. Open the UI with ?token=<token>.');
    }
    throw new Error(err.error || `${res.status} ${res.statusText}`);
  }
  return res.status === 204 ? {} : res.json();
}

// ── markdown (assistant messages only) ──────────────────────────────────────
// Tiny renderer for what the model actually emits: bold/italic/code, bullet
// and numbered lists, pipe tables. Input is HTML-escaped first → XSS-safe.
function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*\*([^*]+)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*\s][^*]*)\*/g, '<em>$1</em>');
}

const isTableRow = (s) => /^\s*\|.*\|\s*$/.test(s);
const isTableSep = (s) => /^\s*\|[\s:|-]+\|\s*$/.test(s);
const splitRow = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

function mdToHtml(md) {
  const esc = md.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const lines = esc.split('\n');
  let html = '', list = null, para = [];
  const flushPara = () => { if (para.length) { html += `<p>${para.join('<br>')}</p>`; para = []; } };
  const closeList = () => { if (list) { html += `</${list}>`; list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();

    // pipe table: header row + separator row, then body rows
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flushPara(); closeList();
      const cells = (r) => splitRow(r).map((c) => inlineMd(c));
      html += '<table><thead><tr>'
        + cells(line).map((c) => `<th>${c}</th>`).join('')
        + '</tr></thead><tbody>';
      i++; // skip separator
      while (i + 1 < lines.length && isTableRow(lines[i + 1].trimEnd())) {
        i++;
        html += '<tr>' + cells(lines[i]).map((c) => `<td>${c}</td>`).join('') + '</tr>';
      }
      html += '</tbody></table>';
      continue;
    }

    const ul = line.match(/^\s*[-*•]\s+(.*)/);
    const ol = line.match(/^\s*(\d+)[.)]\s+(.*)/);
    if (ul || ol) {
      flushPara();
      const want = ul ? 'ul' : 'ol';
      if (list !== want) {
        closeList();
        html += ul ? '<ul>' : `<ol start="${ol[1]}">`;
        list = want;
      }
      html += `<li>${inlineMd(ul ? ul[1] : ol[2])}</li>`;
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(inlineMd(line));
    }
  }
  flushPara(); closeList();
  return html;
}

// ── rendering ────────────────────────────────────────────────────────────────
function addMsg(role, content) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') div.innerHTML = mdToHtml(content);
  else div.textContent = content;
  $('chat').appendChild(div);
  div.scrollIntoView({ behavior: 'smooth' });
  return div;
}

function renderTranscript(messages) {
  $('chat').querySelectorAll('.msg').forEach((el) => el.remove());
  for (const m of messages) addMsg(m.role, m.content);
}

function renderConversationStatus(status) {
  conversationStatus = status;
  turnInterrupted = status?.status === 'interrupted';
  $('chat').querySelector('.recovery-card')?.remove();
  if (turnInterrupted) {
    const card = document.createElement('div');
    card.className = 'recovery-card';
    card.innerHTML = `
      <div class="title">Checkpoint recovered; execution stopped</div>
      <div class="desc">The user input is durable in Postgres, but this self-hosted app needs an explicit invocation to continue.</div>
      <button class="pill" type="button">Resume turn</button>`;
    card.querySelector('button').onclick = resumeInterruptedTurn;
    $('chat').appendChild(card);
  }
  setBusy(false);
  if (demoControls) renderDemoControls(demoControls);
}

function setBusy(busy, label) {
  const composerDisabled = busy || approvalPending || turnInterrupted;
  $('input').disabled = composerDisabled;
  $('send').disabled = composerDisabled;
  const t = $('chat').querySelector('.typing');
  if (t) t.remove();
  if (busy) addMsg('assistant typing', label || 'thinking…');
  else if (!composerDisabled) $('input').focus();
}

function showError(message) {
  const el = $('error');
  el.textContent = message;
  el.style.display = 'block';
  setTimeout(() => (el.style.display = 'none'), 6000);
}

function applyConfig() {
  document.querySelectorAll('[data-powered-by]').forEach((el) => {
    el.textContent = activeBackend.poweredBy;
  });
  document.querySelectorAll('[data-backend-name]').forEach((el) => {
    el.textContent = activeBackend.label;
  });
}

// ── demo fault controls ─────────────────────────────────────────────────────
function setControlsMessage(message, { error = false } = {}) {
  const el = $('controls-message');
  el.textContent = message;
  el.classList.toggle('error', error);
}

function setControlAvailable(rowId, inputId, available) {
  const row = $(rowId);
  const input = $(inputId);
  row.classList.toggle('unavailable', !available);
  input.disabled = controlsLoading || !available;
}

function renderDemoControls(controls) {
  demoControls = controls;
  const capabilities = controls.capabilities || {};

  $('control-random').checked = Boolean(controls.randomOpenAIFailures);
  $('control-random-copy').textContent = controls.randomOpenAIFailures
    ? `Fail ${Math.round((controls.randomOpenAIFailureRate || 0) * 100)}% of OpenAI planning calls.`
    : 'When enabled, fail about half of OpenAI planning calls.';
  $('control-openai').checked = !controls.openAIResponsesOutage;
  $('control-app').checked = controls.langGraphAppEnabled !== false;
  $('control-worker').checked = controls.workerEnabled !== false;

  setControlAvailable('control-row-random', 'control-random', true);
  setControlAvailable('control-row-outage', 'control-openai', true);
  setControlAvailable('control-row-app', 'control-app', Boolean(capabilities.langGraphApp));
  setControlAvailable('control-row-worker', 'control-worker', Boolean(capabilities.worker));

  const canResume = Boolean(
    capabilities.resumeTurn &&
      conversationId &&
      controls.langGraphAppEnabled !== false &&
      conversationStatus?.resumable,
  );
  $('control-resume-turn').disabled = controlsLoading || !canResume;
  $('control-resume-copy').textContent = !capabilities.resumeTurn
    ? 'Manual turn recovery is available only for standalone LangGraph.'
    : !conversationId
      ? 'Start a conversation to demonstrate manual recovery.'
      : conversationStatus?.resumable
        ? 'The checkpoint is durable, but no process is running this turn.'
        : 'Kill the standalone app during a turn to enable manual recovery.';

  const injecting =
    controls.randomOpenAIFailures ||
    controls.openAIResponsesOutage ||
    controls.langGraphAppEnabled === false ||
    controls.workerEnabled === false;
  document.querySelector('#controls-toggle .status-dot')?.classList.toggle('injecting', injecting);
}

function setControlsLoading(loading) {
  controlsLoading = loading;
  const capabilities = demoControls?.capabilities || {};
  $('control-random').disabled = loading;
  $('control-openai').disabled = loading;
  $('control-app').disabled = loading || !capabilities.langGraphApp;
  $('control-worker').disabled = loading || !capabilities.worker;
  $('control-resume-turn').disabled =
    loading || !capabilities.resumeTurn || !conversationStatus?.resumable;
}

async function refreshConversationFromCheckpoint() {
  if (!conversationId || demoControls?.langGraphAppEnabled === false) return;
  const capabilities = demoControls?.capabilities || {};
  if (!capabilities.resumeTurn) return;
  const [{ messages }, { pending }, status] = await Promise.all([
    call('GET', `/conversations/${conversationId}/transcript`),
    call('GET', `/conversations/${conversationId}/pending-approval`),
    call('GET', `/conversations/${conversationId}/status`),
  ]);
  renderTranscript(messages);
  approvalPending = Boolean(pending);
  if (pending) showApprovalCard(pending);
  renderConversationStatus(status);
}

async function loadDemoControls() {
  setControlsLoading(true);
  setControlsMessage('Loading controls…');
  try {
    const controls = await call('GET', '/demo/controls');
    demoControls = controls;
    setControlsLoading(false);
    renderDemoControls(controls);
    await refreshConversationFromCheckpoint();
    setControlsMessage('Controls are applied to this backend immediately.');
  } catch (error) {
    setControlsLoading(false);
    setControlsMessage(error.message, { error: true });
  }
}

async function updateDemoControl(field, enabled) {
  setControlsLoading(true);
  setControlsMessage('Applying change…');
  try {
    const controls = await call('PUT', '/demo/controls', { [field]: enabled });
    demoControls = controls;
    setControlsLoading(false);
    renderDemoControls(controls);
    if (field === 'langGraphAppEnabled' && enabled) {
      await refreshConversationFromCheckpoint();
    } else if (field === 'langGraphAppEnabled' && !enabled) {
      conversationStatus = null;
      turnInterrupted = false;
      $('chat').querySelector('.recovery-card')?.remove();
    }
    setControlsMessage('Control updated.');
  } catch (error) {
    setControlsLoading(false);
    if (demoControls) renderDemoControls(demoControls);
    setControlsMessage(error.message, { error: true });
  }
}

async function resumeInterruptedTurn() {
  if (!conversationId || !conversationStatus?.resumable) return;
  setControlsLoading(true);
  setControlsMessage('Manually invoking the saved LangGraph thread…');
  setBusy(true, 'resuming saved checkpoint…');
  try {
    await call('POST', `/conversations/${conversationId}/resume`);
    await refreshConversationFromCheckpoint();
    setControlsLoading(false);
    if (demoControls) renderDemoControls(demoControls);
    setControlsMessage('Interrupted turn resumed explicitly.');
  } catch (error) {
    setBusy(false);
    setControlsLoading(false);
    if (demoControls) renderDemoControls(demoControls);
    setControlsMessage(error.message, { error: true });
    showError(error.message);
  }
}

function setControlsOpen(open) {
  controlsOpen = open;
  $('controls-panel').classList.toggle('open', open);
  $('controls-backdrop').classList.toggle('open', open);
  $('controls-panel').setAttribute('aria-hidden', String(!open));
  $('controls-toggle').setAttribute('aria-expanded', String(open));
  if (open) loadDemoControls();
}

function setupDemoControls() {
  $('controls-toggle').onclick = () => setControlsOpen(true);
  $('controls-close').onclick = () => setControlsOpen(false);
  $('controls-backdrop').onclick = () => setControlsOpen(false);
  $('control-random').onchange = (event) =>
    updateDemoControl('randomOpenAIFailures', event.target.checked);
  $('control-openai').onchange = (event) =>
    updateDemoControl('openAIResponsesOutage', !event.target.checked);
  $('control-app').onchange = (event) =>
    updateDemoControl('langGraphAppEnabled', event.target.checked);
  $('control-worker').onchange = (event) =>
    updateDemoControl('workerEnabled', event.target.checked);
  $('control-resume-turn').onclick = resumeInterruptedTurn;
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && controlsOpen) setControlsOpen(false);
  });
}

function setupBackendSelector() {
  const select = $('backend-select');
  if (!select) return;
  select.replaceChildren(
    ...Object.values(BACKENDS).map((backend) => {
      const option = document.createElement('option');
      option.value = backend.id;
      option.textContent = backend.label;
      return option;
    }),
  );
  select.value = activeBackendId;
  select.onchange = () => selectBackend(select.value);
}

function showConversationId(id) {
  if (activeBackend.conversationLinkBase) {
    const link = document.createElement('a');
    link.href = `${activeBackend.conversationLinkBase}/${encodeURIComponent(id)}`;
    link.target = '_blank';
    link.rel = 'noopener';
    link.innerHTML = `<span class="label">${activeBackend.conversationIdLabel}:&nbsp;</span>`;
    link.append(id);
    $('conv-id').replaceChildren(link);
    return;
  }

  const pill = document.createElement('span');
  pill.className = 'id-pill';
  pill.innerHTML = `<span class="label">${activeBackend.conversationIdLabel}:&nbsp;</span>`;
  pill.append(id);
  $('conv-id').replaceChildren(pill);
}

// ── approval card (the HITL moment) ─────────────────────────────────────────
function showApprovalCard(pending) {
  approvalPending = true;
  $('chat').querySelector('.approval-card')?.remove();
  const card = document.createElement('div');
  card.className = 'approval-card';
  card.dataset.approvalId = pending.approvalId || '';
  card.innerHTML = `
    <div class="title">⏸ Purchase approval required</div>
    <div class="desc"></div>
    <button class="pill approve">Approve</button>
    <button class="reject">Reject</button>`;
  card.querySelector('.desc').textContent =
    pending.description || `Track IDs: ${(pending.trackIds || []).join(', ')}`;
  card.querySelector('.approve').onclick = () => decide(card, true);
  card.querySelector('.reject').onclick = () => decide(card, false);
  $('chat').appendChild(card);
  card.scrollIntoView({ behavior: 'smooth' });
}

async function decide(card, approved) {
  const approvalId = card.dataset.approvalId;
  if (!approvalId) {
    showError('This approval request is missing an ID. Refresh the conversation and try again.');
    return;
  }
  card.querySelectorAll('button').forEach((b) => (b.disabled = true));
  try {
    // Baseline from the SERVER, not the client render count: multi-step turns
    // put intermediate assistant texts (alongside tool calls) in the server
    // transcript that were never rendered here, so the client count lags.
    const { messages } = await call('GET', `/conversations/${conversationId}/transcript`);
    const baseline = messages.filter((m) => m.role === 'assistant').length;
    await call('POST', `/conversations/${conversationId}/approve`, { approvalId, approved });
    card.remove();
    setBusy(true, approved ? 'completing purchase…' : 'cancelling…');
    await pollUntilSettled(baseline);
  } catch (e) {
    showError(e.message);
    card.querySelectorAll('button').forEach((b) => (b.disabled = false));
  }
}

// After approval the turn resumes server-side; poll until a new
// assistant message lands (or another approval is requested — multi-purchase turns).
async function pollUntilSettled(baselineAssistant) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const [{ messages }, { pending }] = await Promise.all([
      call('GET', `/conversations/${conversationId}/transcript`),
      call('GET', `/conversations/${conversationId}/pending-approval`),
    ]);
    if (pending) {
      renderTranscript(messages);
      showApprovalCard(pending);
      await refreshConversationFromCheckpoint();
      setBusy(false);
      return;
    }
    const serverCount = messages.filter((m) => m.role === 'assistant').length;
    if (serverCount > baselineAssistant) {
      renderTranscript(messages);
      approvalPending = false;
      await refreshConversationFromCheckpoint();
      setBusy(false);
      return;
    }
  }
  approvalPending = false;
  setBusy(false);
  showError('Timed out waiting for the agent — check the backend.');
}

// ── send a message (blocks until the turn settles — see contract) ───────────
$('composer').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('input').value.trim();
  if (!text) return;
  $('input').value = '';
  addMsg('user', text);
  setBusy(true);
  try {
    const r = await call('POST', `/conversations/${conversationId}/messages`, { text });
    if (r.reply) addMsg('assistant', r.reply);
    if (r.status === 'awaiting_approval') {
      const { pending } = await call('GET', `/conversations/${conversationId}/pending-approval`);
      if (pending) showApprovalCard(pending);
    }
    if (demoControls?.capabilities?.resumeTurn) {
      await refreshConversationFromCheckpoint();
    }
    setBusy(false);
  } catch (err) {
    setBusy(false);
    if (
      conversationId &&
      demoControls?.capabilities?.resumeTurn &&
      demoControls.langGraphAppEnabled !== false
    ) {
      await refreshConversationFromCheckpoint().catch(() => {});
    }
    showError(err.message);
  }
};

// ── start a conversation ────────────────────────────────────────────────────
$('start-form').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const { conversationId: id } = await call('POST', '/conversations', {
      customerEmail: $('email').value.trim(),
    });
    conversationId = id;
    conversationStatus = { status: 'idle', resumable: false };
    turnInterrupted = false;
    if (demoControls) renderDemoControls(demoControls);
    showConversationId(id);
    $('start').remove();
    setBusy(false);
    // client-side greeting only, not part of the server transcript.
    addMsg('assistant', 'Hi! I can help you find music, check your orders, or buy tracks. What are you looking for?');
  } catch (err) {
    showError(err.message);
  }
};

selectBackend(initialBackendId(), { persist: false, updateUrl: false });
setupBackendSelector();
setupDemoControls();
demoToken();
