/* Rex Desktop — vanilla JS SPA. No build step, no npm. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  running: false, mode: "PLAN", session: null, title: "",
  providers: [], activeProvider: null, settings: {}, files: [],
  acItems: [], acIndex: 0, acToken: null, streamEl: null,
};

// ── tiny helpers ────────────────────────────────────────────
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function scrollChat() { const c = $("chat"); c.scrollTop = c.scrollHeight; }

// ── boot: token from ?t= ────────────────────────────────────
const TOKEN = new URLSearchParams(location.search).get("t") || "";
async function api(path, opts) {
  const o = opts || {};
  o.headers = Object.assign({ "Content-Type": "application/json" }, o.headers || {});
  const r = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + TOKEN, o);
  return r.json();
}
function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body || {}) });
}

// ── chat rendering ─────────────────────────────────────────
function bubble(style, text) {
  const m = el("div", "message " + (style || ""));
  const b = el("div", "msg-bubble", text);
  m.appendChild(b);
  $("messages").appendChild(m);
  scrollChat();
  return b;
}
function renderEvent(ev) {
  switch (ev.type) {
    case "message": bubble(ev.style || "info", ev.text); break;
    case "table":
      state.streamEl = null;
      { const m = el("div", "message msg-table");
        if (ev.title) m.appendChild(el("div", "tbl-title", ev.title));
        m.appendChild(el("pre", null, ev.text));
        $("messages").appendChild(m); scrollChat(); }
      break;
    case "stream_delta":
      if (!state.streamEl) {
        state.streamEl = bubble("", "");
        state.streamEl.classList.add("stream-cursor");
      }
      state.streamEl.textContent += ev.text;
      scrollChat();
      break;
    case "thought":
      { const m = el("div", "message");
        m.appendChild(el("div", "thought", ev.text));
        $("messages").appendChild(m); scrollChat(); }
      break;
    case "tool_call":
      { const m = el("div", "message");
        const card = el("div", "tool-card");
        const head = el("div", "tool-head");
        head.appendChild(el("span", "arrow", "▶"));
        head.appendChild(el("span", null, "🛠 " + (ev.tool || ev.name || "tool")));
        const body = el("div", "tool-body hidden", ev.summary || JSON.stringify(ev.args || {}));
        head.onclick = () => body.classList.toggle("hidden");
        card.appendChild(head); card.appendChild(body);
        m.appendChild(card);
        $("messages").appendChild(m); scrollChat(); }
      break;
    case "tool_result":
      { const cards = document.querySelectorAll(".tool-card");
        const last = cards[cards.length - 1];
        if (last) {
          const b = last.querySelector(".tool-body");
          b.textContent = (b.textContent || "") + "\n" + (ev.summary || ev.text || "");
          b.classList.remove("hidden");
        } else bubble("info", ev.summary || ev.text || ""); }
      break;
    case "todo_update": renderTodos(ev.todos || []); break;
    case "usage_alert": bubble("warn", ev.text || "Token budget alert"); break;
    case "mode_changed": state.mode = ev.mode; paintMode(); break;
    case "session_changed":
      state.session = ev.session_id; state.title = ev.title || "";
      $("chat-title").textContent = state.title || "Percakapan baru";
      refreshSessions();
      break;
    case "providers":
      state.providers = ev.items || []; state.activeProvider = ev.active;
      paintProviderChip();
      break;
    case "help":
      bubble("info", (ev.items || []).map((p) => p[0].padEnd(22) + " — " + p[1]).join("\n"));
      break;
    case "agent_state":
      state.running = !!ev.running;
      $("running-indicator").classList.toggle("hidden", !state.running);
      if (!state.running && state.streamEl) {
        state.streamEl.classList.remove("stream-cursor");
        state.streamEl = null;
      }
      break;
    case "approval_request": showApproval(ev); break;
    case "approval_resolved": hideApproval(); break;
    case "submit_prompt":
      if (state.running) bubble("warn", "Sesi masih berjalan — perintah /skill ditunda.");
      else post("/api/send", { text: ev.text });
      break;
    case "quit": window.close(); break;
    default: break;
  }
}

// ── SSE events stream ──────────────────────────────────────
function connectEvents() {
  const es = new EventSource("/api/events?t=" + TOKEN);
  es.onmessage = (m) => { try { renderEvent(JSON.parse(m.data)); } catch (e) { /* ignore */ } };
  es.onerror = () => { es.close(); setTimeout(connectEvents, 1500); };
}


// ── sidebar: mode / provider / sessions ────────────────────
function paintMode() {
  $("mode-plan").className = "mode-btn" + (state.mode === "PLAN" ? " active-plan" : "");
  $("mode-build").className = "mode-btn" + (state.mode === "BUILD" ? " active-build" : "");
}
function paintProviderChip() {
  const p = state.providers.find((x) => x.id === state.activeProvider);
  $("provider-chip").textContent = p ? (p.id + " · " + (p.model || "?")) : "pilih provider";
}
async function refreshState() {
  const s = await api("/api/state");
  state.mode = s.mode; state.session = s.session_id;
  paintMode();
  $("provider-chip").textContent = (s.provider || "?") + " · " + (s.model || "?");
  const u = await api("/api/usage");
  $("usage-footer").textContent = "Sesi ini: " + (u.total_tokens || 0).toLocaleString() + " token";
}
async function refreshSessions() {
  const data = await api("/api/sessions");
  const list = $("session-list");
  list.innerHTML = "";
  (data.sessions || []).forEach((s) => {
    const item = el("div", "session-item" + (s.id === state.session ? " active" : ""));
    item.appendChild(el("span", null, s.title || "Percakapan baru"));
    item.appendChild(el("span", "meta", (s.model || "?") + " · " + (s.updated_at || "")));
    item.onclick = () => post("/api/sessions", { action: "resume", id: s.id }).then(refreshState);
    list.appendChild(item);
  });
}
function renderTodos(todos) {
  $("todo-panel").classList.remove("hidden");
  const list = $("todo-list");
  list.innerHTML = "";
  todos.forEach((t) => {
    const line = el("li", "todo-line" + (t.status === "completed" ? " done" : ""));
    line.textContent = (t.status === "completed" ? "☑" : t.status === "in_progress" ? "◐" : "☐") + " " + t.content;
    list.appendChild(line);
  });
}

// ── approval modal ─────────────────────────────────────────
let approvalId = null;
function showApproval(ev) {
  approvalId = ev.id;
  $("approval-action").textContent = ev.action + " — perlu persetujuan";
  $("approval-summary").textContent = ev.summary || "";
  $("approval-modal").classList.remove("hidden");
}
function hideApproval() { $("approval-modal").classList.add("hidden"); approvalId = null; }
function answerApproval(decision, remember) {
  if (approvalId) post("/api/approve", { id: approvalId, decision, remember });
  hideApproval();
}

// ── composer + @ autocomplete ──────────────────────────────
async function workspaceFiles(token) {
  const data = await api("/api/files");
  state.files = data.files || [];
  return state.files.filter((f) => f.indexOf(token) >= 0).slice(0, 8);
}
function paintAutocomplete(items) {
  const box = $("autocomplete");
  state.acItems = items; state.acIndex = 0;
  if (!items.length) { box.classList.add("hidden"); return; }
  box.innerHTML = "";
  items.forEach((f, i) => {
    const item = el("div", "ac-item" + (i === 0 ? " selected" : ""));
    const dot = f.lastIndexOf(".");
    item.appendChild(el("b", null, "@" + f.slice(0, dot < 0 ? f.length : dot + 1)));
    item.appendChild(document.createTextNode(dot < 0 ? "" : f.slice(dot + 1)));
    item.onclick = () => applyAutocomplete(f);
    box.appendChild(item);
  });
  box.classList.remove("hidden");
}
function applyAutocomplete(file) {
  const input = $("input");
  const pos = input.value.lastIndexOf("@");
  input.value = input.value.slice(0, pos) + "@" + file + " ";
  $("autocomplete").classList.add("hidden");
  input.focus();
}
async function handleInputKeydown(e) {
  const box = $("autocomplete");
  const visible = !box.classList.contains("hidden");
  if (visible && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === "Tab")) {
    e.preventDefault();
    if (e.key === "ArrowDown") state.acIndex = Math.min(state.acIndex + 1, state.acItems.length - 1);
    else if (e.key === "ArrowUp") state.acIndex = Math.max(state.acIndex - 1, 0);
    else { applyAutocomplete(state.acItems[state.acIndex]); return; }
    [...box.children].forEach((c, i) => c.classList.toggle("selected", i === state.acIndex));
    return;
  }
  if (e.key === "Escape") { box.classList.add("hidden"); return; }
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendInput(); return; }
  // debounce @-autocomplete
  setTimeout(async () => {
    const v = $("input").value;
    const m = v.match(/@([\w./-]*)$/);
    if (m) paintAutocomplete(await workspaceFiles(m[1]));
    else box.classList.add("hidden");
  }, 0);
}
function sendInput() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.running) return;
  input.value = "";
  $("autocomplete").classList.add("hidden");
  bubble("user", text);
  post("/api/send", { text });
}


// ── settings center ────────────────────────────────────────
async function openSettings() {
  const [gen, prov] = await Promise.all([api("/api/settings"), api("/api/providers")]);
  state.settings = gen.settings || {};
  state.providers = prov.providers || [];
  state.activeProvider = prov.active;
  const overlay = el("div", "");
  overlay.id = "settings-overlay";
  overlay.innerHTML = `
    <div class="settings-frame">
      <div class="settings-head"><h2>Settings</h2>
        <button class="settings-close" id="settings-close">×</button></div>
      <div class="settings-tabs">
        <div class="settings-tab active" id="tab-providers">Providers</div>
        <div class="settings-tab" id="tab-general">General</div>
      </div>
      <div class="settings-body" id="settings-body"></div>
    </div>`;
  overlay.querySelector("#settings-close").onclick = () => overlay.remove();
  overlay.querySelector("#tab-providers").onclick = () => paintSettingsTab(overlay, "providers");
  overlay.querySelector("#tab-general").onclick = () => paintSettingsTab(overlay, "general");
  document.body.appendChild(overlay);
  paintSettingsTab(overlay, "providers");
}
function paintSettingsTab(overlay, tab) {
  overlay.querySelector("#tab-providers").classList.toggle("active", tab === "providers");
  overlay.querySelector("#tab-general").classList.toggle("active", tab === "general");
  const body = overlay.querySelector("#settings-body");
  body.innerHTML = "";
  if (tab === "providers") paintProvidersTab(body);
  else paintGeneralTab(body);
}
async function paintProvidersTab(body) {
  const data = await api("/api/providers");
  state.providers = data.providers || [];
  state.activeProvider = data.active;
  body.appendChild(el("div", "side-label", "Klik Edit untuk mengubah API key, model, dan koneksi"));
  state.providers.forEach((p) => {
    const card = el("div", "provider-card" + (p.id === state.activeProvider ? " active" : ""));
    const left = el("div");
    const nameRow = el("div", "p-name", p.name);
    if (p.id === state.activeProvider) {
      const badge = el("span", "badge-active", "AKTIF");
      badge.style.marginLeft = "8px";
      nameRow.appendChild(badge);
    }
    left.appendChild(nameRow);
    left.appendChild(el("div", "p-model", "model: " + (p.model || "?")));
    if (!p.has_key) left.appendChild(el("div", "p-missing", "API key belum diisi"));
    card.appendChild(left);
    const right = el("div");

async function paintProviderEditor(body, pid) {
  const p = state.providers.find((x) => x.id === pid);
  if (!p) return;
  body.innerHTML = "";
  const editor = el("div", "provider-editor");
  editor.appendChild(el("div", "pe-title", "Edit provider: " + p.name));
  const rows = [
    ["Nama", "text", p.name, "name"],
    ["Base URL", "text", p.base_url || "", "base_url"],
    ["API key", "password", "", "api_key"],
    ["Model aktif", "text", p.model || "", "model"],
  ];
  const inputs = {};
  rows.forEach(([label, type, value, key]) => {
    const row = el("div", "form-row");
    row.appendChild(el("label", null, label));
    const input = el("input");
    input.type = type; input.value = value;
    input.placeholder = key === "api_key" ? "kirim kosong = tidak diubah" : "";
    inputs[key] = input;
    row.appendChild(input);
    editor.appendChild(row);
  });
  const modelRow = el("div", "form-row");
  modelRow.appendChild(el("label", null, "Pilih model"));
  const select = el("select");
  (p.available_models || []).forEach((m) => {
    const opt = el("option", null, m);
    opt.value = m;
    if (m === p.model) opt.selected = true;
    select.appendChild(opt);
  });
  select.onchange = () => { inputs.model.value = select.value; };
  modelRow.appendChild(select);
  editor.appendChild(modelRow);
  const actions = el("div", "form-actions");
  const result = el("div", "test-result");
  const test = el("button", "primary ghost", "Test connection");
  test.onclick = async () => {
    result.className = "test-result";
    result.textContent = "menguji…";
    const r = await post("/api/providers/" + pid + "/test", { model: inputs.model.value });
    result.className = "test-result " + (r.ok ? "ok" : "bad");
    result.textContent = r.ok ? "✓ OK — " + (r.detail || "terhubung") : "✗ Gagal — " + (r.error || "tidak terjawab");
  };
  const save = el("button", "primary", "Simpan");
  save.onclick = async () => {
    const payload = { name: inputs.name.value, base_url: inputs.base_url.value, model: inputs.model.value };
    if (inputs.api_key.value.trim()) payload.api_key = inputs.api_key.value.trim();
    const r = await post("/api/providers", { action: "update", id: pid, data: payload });
    if (r.ok) paintProvidersTab(body);
    else { result.className = "test-result bad"; result.textContent = r.error || "gagal menyimpan"; }
  };

async function paintGeneralTab(body) {
  const data = await api("/api/settings");
  const s = data.settings || {};
  body.appendChild(el("div", "side-label", "Tersimpan ke config.json — berlaku untuk semua frontend"));
  const fields = [
    ["Mode default", "select", "default_mode", ["plan", "build"], s.default_mode],
    ["Bahasa UI", "text", "language", null, s.language],
    ["Token budget", "number", "token_budget", null, s.token_budget],
    ["Max steps", "number", "max_steps", null, s.max_steps],
    ["Streaming", "select", "streaming", ["on", "off"], s.streaming],
    ["Anti-slop", "select", "anti_slop", ["on", "off"], s.anti_slop],
    ["Approval", "select", "approval", ["on", "off"], s.approval],
    ["Update channel", "select", "update_channel", ["stable", "beta"], s.update_channel],
  ];
  const inputs = {};
  fields.forEach(([label, type, key, options, value]) => {
    const row = el("div", "form-row");
    row.appendChild(el("label", null, label));
    let input;
    if (type === "select") {
      input = el("select");
      options.forEach((o) => {
        const opt = el("option", null, o);
        opt.value = o;
        if (String(value) === o) opt.selected = true;
        input.appendChild(opt);
      });
    } else {
      input = el("input");
      input.type = type === "number" ? "number" : "text";
      input.value = value === undefined || value === null ? "" : value;
    }
    inputs[key] = input;
    row.appendChild(input);
    body.appendChild(row);
  });
  const actions = el("div", "form-actions");
  const save = el("button", "primary", "Simpan General");
  save.onclick = async () => {
    const payload = {};
    Object.keys(inputs).forEach((k) => {
      const v = inputs[k].value;
      payload[k] = inputs[k].tagName === "SELECT" ? v : (inputs[k].type === "number" ? (parseInt(v, 10) || 0) : v);
    });
    const r = await post("/api/settings", payload);
    const note = el("div", "test-result " + (r.ok ? "ok" : "bad"), r.ok ? "✓ Tersimpan" : "✗ " + (r.error || "gagal"));
    body.insertBefore(note, body.firstChild);
  };
  actions.appendChild(save);
  body.appendChild(actions);
}

// ── boot ───────────────────────────────────────────────────
async function boot() {
  paintMode();
  connectEvents();
  await refreshState();
  await refreshSessions();
  $("btn-new").onclick = async () => { await post("/api/sessions", { action: "new" }); await refreshState(); };
  $("mode-plan").onclick = () => post("/api/mode", { mode: "plan" });
  $("mode-build").onclick = () => post("/api/mode", { mode: "build" });
  $("running-indicator").onclick = () => post("/api/abort", {});
  $("todo-close").onclick = () => $("todo-panel").classList.add("hidden");
  $("provider-chip").onclick = () => post("/api/send", { text: "/models" });
  $("btn-settings").onclick = openSettings;
  $("approve-allow").onclick = () => answerApproval(true, false);
  $("approve-always").onclick = () => answerApproval(true, true);
  $("approve-deny").onclick = () => answerApproval(false, false);
  $("send").onclick = sendInput;
  $("input").addEventListener("keydown", handleInputKeydown);
}
boot();

  actions.appendChild(test); actions.appendChild(save);
  editor.appendChild(actions);
  editor.appendChild(result);
  body.appendChild(editor);
}

    const edit = el("button", "primary ghost", "Edit");
    edit.onclick = () => paintProviderEditor(body, p.id);
    right.appendChild(edit);
    if (p.id !== state.activeProvider) {
      const use = el("button", "primary", "Jadikan aktif");
      use.style.marginLeft = "8px";
      use.onclick = async () => {
        await post("/api/providers", { action: "activate", id: p.id });
        paintProvidersTab(body);
      };
      right.appendChild(use);
    }
    card.appendChild(right);
    body.appendChild(card);
  });
}
