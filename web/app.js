// Rex Code Web Dashboard Frontend Logic

let ws = null;
let currentMode = "plan";
let currentSessionId = localStorage.getItem("rexSessionId");
let streamedResponse = "";
let agentRunning = false;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  lucide.createIcons();
  loadConfig();
  loadSessions();
  refreshFiles();
  connectWebSocket();
});

// Load configuration
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    currentMode = cfg.active_mode || "plan";
    updateModeUI(currentMode);

    const modelSelect = document.getElementById("model-select");
    modelSelect.replaceChildren();
    Object.entries(cfg.providers || {}).forEach(([providerId, provider]) => {
      (provider.available_models || []).forEach(model => {
        const option = new Option(`${provider.name}: ${model}`, model);
        option.dataset.provider = providerId;
        option.selected = providerId === cfg.active_provider && model === cfg.active_model;
        modelSelect.add(option);
      });
    });
  } catch (err) {
    console.error("Gagal memuat config:", err);
  }
}

// Switch Mode (Plan vs Build)
async function switchMode(mode) {
  currentMode = mode;
  updateModeUI(mode);
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_mode: mode })
    });
  } catch (err) {
    console.error("Gagal update mode:", err);
  }
}

function updateModeUI(mode) {
  const btnPlan = document.getElementById("btn-mode-plan");
  const btnBuild = document.getElementById("btn-mode-build");
  const banner = document.getElementById("mode-banner");
  const desc = document.getElementById("mode-desc");
  const quickBuild = document.getElementById("btn-quick-build");

  if (mode === "plan") {
    btnPlan.className = "flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all bg-blue-600 text-white shadow-md";
    btnBuild.className = "flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white transition-all";
    banner.className = "bg-blue-950/40 border-b border-blue-900/40 px-6 py-2.5 flex items-center justify-between text-xs";
    desc.className = "flex items-center gap-2 text-blue-300";
    desc.innerText = "Mode Plan Aktif: Rex Code hanya meneliti dan merancang tanpa mengubah file.";
    quickBuild.classList.add("hidden");
  } else {
    btnBuild.className = "flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold transition-all bg-emerald-600 text-white shadow-md";
    btnPlan.className = "flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white transition-all";
    banner.className = "bg-emerald-950/40 border-b border-emerald-900/40 px-6 py-2.5 flex items-center justify-between text-xs";
    desc.className = "flex items-center gap-2 text-emerald-300";
    desc.innerText = "Mode Build Aktif: Rex Code memiliki izin penuh menulis kode, eksekusi terminal & auto-debug.";
    quickBuild.classList.add("hidden");
  }
}

// Change active model
async function changeModel(select) {
  const option = select.selectedOptions[0];
  if (!option) return;

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        active_provider: option.dataset.provider,
        active_model: option.value
      })
    });
    if (!res.ok) throw new Error(await res.text());
  } catch (err) {
    console.error("Gagal ganti model:", err);
    loadConfig();
  }
}

// WebSocket Connection
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleAgentEvent(msg);
  };

  ws.onclose = () => {
    setTimeout(connectWebSocket, 2000);
  };
}

async function loadSessions(preferredId = currentSessionId) {
  try {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessionList(sessions);
    const target = sessions.find(item => item.id === preferredId) || sessions[0];
    if (target && target.id !== currentSessionId) await openSession(target.id, false);
    else if (target) await renderSession(target.id);
    else await createSession();
  } catch (err) {
    console.error("Gagal memuat percakapan:", err);
  }
}

function renderSessionList(sessions) {
  const list = document.getElementById("session-list");
  list.replaceChildren(...sessions.map(session => {
    const row = document.createElement("div");
    row.className = `group flex items-center rounded-lg ${session.id === currentSessionId ? "bg-cyan-950/60 text-cyan-200" : "text-slate-400 hover:bg-slate-800"}`;
    const open = document.createElement("button");
    open.className = "flex-1 min-w-0 p-2 text-left text-xs truncate";
    open.textContent = session.title || "Percakapan baru";
    open.onclick = () => openSession(session.id);
    const remove = document.createElement("button");
    remove.className = "p-2 opacity-0 group-hover:opacity-100 hover:text-red-400";
    remove.title = "Hapus percakapan";
    remove.innerHTML = '<i data-lucide="trash-2" class="w-3.5 h-3.5"></i>';
    remove.onclick = () => deleteSession(session.id);
    row.append(open, remove);
    return row;
  }));
  lucide.createIcons();
}

async function createSession() {
  const res = await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (!res.ok) return;
  const session = await res.json();
  await openSession(session.id);
}

async function openSession(sessionId, refreshList = true) {
  currentSessionId = sessionId;
  localStorage.setItem("rexSessionId", sessionId);
  await renderSession(sessionId);
  if (refreshList) {
    const res = await fetch("/api/sessions");
    if (res.ok) renderSessionList(await res.json());
  }
}

async function renderSession(sessionId) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (!res.ok) return;
  const session = await res.json();
  const stats = session.stats || {};
  document.getElementById("mode-desc").title = `${stats.messages || 0} pesan Â· ${stats.characters || 0} karakter tersimpan`;
  const container = document.getElementById("messages-container");
  container.replaceChildren();
  session.messages.forEach(message => {
    if (message.role === "user") appendUserMessage(message.content || "");
    else if (message.role === "assistant") appendAssistantMessage(message.content || "");
  });
}

async function deleteSession(sessionId) {
  if (!confirm("Hapus percakapan ini? Tindakan tidak dapat dibatalkan.")) return;
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  if (!res.ok) return;
  if (currentSessionId === sessionId) {
    currentSessionId = null;
    localStorage.removeItem("rexSessionId");
  }
  await loadSessions();
}

function handleChatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN || !currentSessionId) return;

  // Append user message to UI
  appendUserMessage(text);
  input.value = "";

  // Send over websocket
  ws.send(JSON.stringify({
    message: text,
    mode: currentMode,
    session_id: currentSessionId
  }));

  // Append thinking indicator
  showThinkingIndicator();
  setRunning(true);
}

function setRunning(running) {
  agentRunning = running;
  document.getElementById("send-btn").classList.toggle("hidden", running);
  document.getElementById("stop-btn").classList.toggle("hidden", !running);
  document.getElementById("chat-input").disabled = running;
}

function stopAgent() {
  if (agentRunning && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "abort" }));
    document.getElementById("stop-btn").disabled = true;
  }
}

function sendQuickPrompt(prompt) {
  document.getElementById("chat-input").value = prompt;
  document.getElementById("chat-form").dispatchEvent(new Event("submit"));
}

function appendUserMessage(text) {
  const container = document.getElementById("messages-container");
  const div = document.createElement("div");
  div.className = "flex gap-3 max-w-2xl ml-auto flex-row-reverse";
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-cyan-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
      Anda
    </div>
    <div class="bg-cyan-950/60 border border-cyan-800/60 rounded-2xl p-4 text-sm leading-relaxed text-cyan-100 shadow-sm">
      ${escapeHtml(text)}
    </div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function appendAssistantMessage(text) {
  const container = document.getElementById("messages-container");
  const div = document.createElement("div");
  div.className = "flex gap-3 max-w-3xl";
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-base shrink-0">ðŸ¦–</div>
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 text-sm leading-relaxed text-slate-200">${formatMarkdown(text)}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

let activeStepBlock = null;

function showThinkingIndicator() {
  removeThinkingIndicator();
  streamedResponse = "";
  const container = document.getElementById("messages-container");
  activeStepBlock = document.createElement("div");
  activeStepBlock.className = "flex gap-3 max-w-3xl";
  activeStepBlock.id = "active-agent-step";
  activeStepBlock.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-base shrink-0 animate-pulse">
      ðŸ¦–
    </div>
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 text-sm text-slate-300 w-full space-y-2">
      <div id="step-log" class="space-y-1.5 text-xs">
        <div class="flex items-center gap-2 text-cyan-400 animate-pulse">
          <i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i>
          <span>Rex Code sedang memproses instruksi Anda...</span>
        </div>
      </div>
      <div id="step-final-content" class="text-sm leading-relaxed text-slate-200 mt-2 hidden"></div>
    </div>
  `;
  container.appendChild(activeStepBlock);
  container.scrollTop = container.scrollHeight;
  lucide.createIcons();
}

function removeThinkingIndicator() {
  const existing = document.getElementById("active-agent-step");
  if (existing) existing.id = "";
}

function handleAgentEvent(msg) {
  const logContainer = document.querySelector("#active-agent-step #step-log");
  const finalContainer = document.querySelector("#active-agent-step #step-final-content");

  if (!logContainer) return;

  if (msg.type === "stream_delta") {
    streamedResponse += String(msg.data || "");
    if (finalContainer) {
      finalContainer.classList.remove("hidden");
      finalContainer.textContent = streamedResponse;
    }
  } else if (msg.type === "thought") {
    const item = document.createElement("div");
    item.className = "p-2 rounded bg-slate-950/60 border border-slate-800 text-slate-400 italic text-[11px]";
    item.innerText = `ðŸ§  ${msg.data}`;
    logContainer.appendChild(item);
  } else if (msg.type === "tool_call") {
    streamedResponse = "";
    if (finalContainer) finalContainer.textContent = "";
    const item = document.createElement("div");
    item.className = "flex items-center gap-1.5 text-amber-400 font-mono text-[11px]";
    item.textContent = `Tool: ${msg.data.name}(${JSON.stringify(msg.data.args)})`;
    logContainer.appendChild(item);
  } else if (msg.type === "tool_result") {
    const item = document.createElement("div");
    item.className = "p-2 rounded bg-slate-950 border border-emerald-900/40 text-emerald-400 font-mono text-[11px] max-h-32 overflow-auto";
    item.innerText = `âœ“ ${msg.data.name}: ${msg.data.result}`;
    logContainer.appendChild(item);
    refreshFiles();
  } else if (msg.type === "final_response") {
    // Show final response
    if (finalContainer) {
      finalContainer.classList.remove("hidden");
      finalContainer.innerHTML = formatMarkdown(msg.data);
    }
    streamedResponse = "";
    setRunning(false);
    document.getElementById("stop-btn").disabled = false;
    removeThinkingIndicator();
    if (msg.session_id) {
      currentSessionId = msg.session_id;
      localStorage.setItem("rexSessionId", msg.session_id);
      loadSessions(msg.session_id);
    }
    refreshFiles();

    // If in plan mode, show quick build prompt button
    if (currentMode === "plan") {
      document.getElementById("btn-quick-build").classList.remove("hidden");
    }
  } else if (msg.type === "error") {
    if (finalContainer) {
      finalContainer.classList.remove("hidden");
      finalContainer.textContent = String(msg.data || "Terjadi kesalahan");
      finalContainer.classList.add("text-red-400");
    }
    removeThinkingIndicator();
    setRunning(false);
  }

  const container = document.getElementById("messages-container");
  container.scrollTop = container.scrollHeight;
}

// Refresh File List
async function refreshFiles() {
  try {
    const res = await fetch("/api/files");
    const data = await res.json();

    // Workspace files
    const fileList = document.getElementById("file-list");
    if (!data.workspace || data.workspace.length === 0) {
      fileList.innerHTML = `<p class="text-slate-500 italic">Belum ada file di workspace.</p>`;
    } else {
      fileList.innerHTML = data.workspace.map(f => `
        <div onclick="viewFile('${f}', 'workspace')" class="flex items-center gap-2 p-2 rounded-lg hover:bg-slate-800 cursor-pointer text-slate-300 hover:text-white transition">
          <i data-lucide="file" class="w-3.5 h-3.5 text-cyan-400 shrink-0"></i>
          <span class="truncate">${f}</span>
        </div>
      `).join("");
    }

    // Workflow files
    const wfList = document.getElementById("workflow-list");
    if (!data.workflows || data.workflows.length === 0) {
      wfList.innerHTML = `<p class="text-slate-500 italic">Belum ada workflow otomasi.</p>`;
    } else {
      wfList.innerHTML = data.workflows.map(f => `
        <div onclick="viewFile('${f}', 'workflows')" class="flex items-center justify-between p-2 rounded-lg hover:bg-slate-800 cursor-pointer text-slate-300 hover:text-white transition">
          <div class="flex items-center gap-2 truncate">
            <i data-lucide="share-2" class="w-3.5 h-3.5 text-amber-400 shrink-0"></i>
            <span class="truncate">${f}</span>
          </div>
          <span class="text-[10px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded">n8n JSON</span>
        </div>
      `).join("");
    }

    lucide.createIcons();
  } catch (err) {
    console.error("Gagal refresh file:", err);
  }
}

// View file content in viewer tab
async function viewFile(path, source) {
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent(path)}&source=${source}`);
    const data = await res.json();
    document.getElementById("viewing-filename").innerText = `${source}/${data.filename}`;
    document.getElementById("code-preview").innerText = data.content;
    switchTab("viewer");
  } catch (err) {
    alert("Gagal membaca isi file.");
  }
}

// Create n8n template
async function createN8nTemplate() {
  try {
    const res = await fetch("/api/n8n/create-template", { method: "POST" });
    const data = await res.json();
    alert(`Workflow n8n berhasil dibuat: ${data.file}\nFile tersimpan di folder workflows/`);
    refreshFiles();
    switchTab("n8n");
  } catch (err) {
    alert("Gagal membuat workflow n8n");
  }
}

// Switch Right Panel Tabs
function switchTab(tabId) {
  const tabs = ["files", "n8n", "viewer"];
  tabs.forEach(t => {
    document.getElementById(`tab-${t}`).classList.add("hidden");
    document.getElementById(`tab-${t}-btn`).className = "flex-1 py-2 text-xs font-semibold text-slate-400 hover:text-slate-200 border-b-2 border-transparent flex items-center justify-center gap-1.5";
  });

  document.getElementById(`tab-${tabId}`).classList.remove("hidden");
  document.getElementById(`tab-${tabId}-btn`).className = "flex-1 py-2 text-xs font-semibold text-cyan-400 border-b-2 border-cyan-400 flex items-center justify-center gap-1.5";
  lucide.createIcons();
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function formatMarkdown(text) {
  // Simple markdown converter for codeblocks and bold
  let html = escapeHtml(text);
  html = html.replace(/```([\s\S]*?)```/g, '<pre class="bg-slate-950 p-3 rounded-lg border border-slate-800 my-2 text-xs font-mono overflow-auto"><code>$1</code></pre>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white font-semibold">$1</strong>');
  html = html.replace(/`([^`]+)`/g, '<code class="bg-slate-800 px-1.5 py-0.5 rounded text-cyan-300 font-mono text-xs">$1</code>');
  html = html.replace(/\n/g, '<br/>');
  return html;
}
