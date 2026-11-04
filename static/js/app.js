/**
 * College GPT — Frontend Application Logic
 * Capstone RAG Model Interactive Controller
 * Browser-Stored Chat History & Google AI Studio Integration
 * Dynamic Attachment Lifecycle (Visible on start/attach, dismissed on first send)
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM References
  const chatContainer = document.getElementById("chatContainer");
  const composerInput = document.getElementById("composerInput");
  const sendBtn = document.getElementById("sendBtn");
  const composerForm = document.getElementById("composerForm");
  const attachBtn = document.getElementById("attachBtn");
  const fileInput = document.getElementById("fileInput");
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const newChatBtn = document.getElementById("newChatBtn");
  const composerAttachmentTray = document.getElementById("composerAttachmentTray");

  // Sidebar elements
  const totalChunksEl = document.getElementById("totalChunks");
  const historyCounterEl = document.getElementById("historyCounter");
  const chatHistoryListEl = document.getElementById("chatHistoryList");
  const toastContainer = document.getElementById("toastContainer");

  // State
  let isGenerating = false;
  let currentSessionId = null;
  let chatSessions = [];
  let latestUploadedFiles = [];

  // Allowed file extensions (strictly PDF & Word Docs)
  const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".doc"];

  // Turn off browser spellcheck, Edge Copilot/Compose writing assistance, and grammar suggestions
  if (composerInput) {
    composerInput.setAttribute("spellcheck", "false");
    composerInput.setAttribute("autocomplete", "off");
    composerInput.setAttribute("autocorrect", "off");
    composerInput.setAttribute("autocapitalize", "off");
    composerInput.setAttribute("data-ms-editor", "false");
    composerInput.setAttribute("data-copilot", "false");
    composerInput.setAttribute("data-edge-copilot", "false");
    composerInput.setAttribute("data-gramm", "false");
    composerInput.setAttribute("data-gramm_editor", "false");
    composerInput.setAttribute("data-enable-grammarly", "false");
    composerInput.spellcheck = false;
  }

  // Initialize
  initTheme();
  initSessions();
  fetchSystemStatus();

  // ========================================================================
  // Theme Management
  // ========================================================================
  function initTheme() {
    const saved = localStorage.getItem("college_gpt_theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon(saved);
  }

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("college_gpt_theme", next);
      updateThemeIcon(next);
    });
  }

  function updateThemeIcon(theme) {
    if (!themeToggleBtn) return;
    themeToggleBtn.innerHTML = theme === "dark" ? "☀️" : "🌙";
    themeToggleBtn.setAttribute("title", `Switch to ${theme === "dark" ? "light" : "dark"} mode`);
  }

  // ========================================================================
  // Toast Notifications
  // ========================================================================
  function showToast(message, type = "info") {
    if (!toastContainer) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icon = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";
    toast.innerHTML = `<span style="font-weight:bold;">${icon}</span> <span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(20px)";
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // ========================================================================
  // Browser-Stored Chat History (Zero Cost, No External Database)
  // ========================================================================
  function initSessions() {
    try {
      chatSessions = JSON.parse(localStorage.getItem("college_gpt_sessions") || "[]");
    } catch (e) {
      chatSessions = [];
    }

    if (chatSessions.length > 0) {
      loadSession(chatSessions[0].id);
    } else {
      createNewSession();
    }
    renderHistoryList();
  }

  function saveSessionsToStorage() {
    try {
      localStorage.setItem("college_gpt_sessions", JSON.stringify(chatSessions));
    } catch (e) {
      console.warn("Storage quota exceeded:", e);
    }
  }

  function createNewSession() {
    currentSessionId = "session_" + Date.now();
    const newSession = {
      id: currentSessionId,
      title: "New Conversation",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      messages: []
    };
    chatSessions.unshift(newSession);
    saveSessionsToStorage();
    renderWelcomeHero();
    renderHistoryList();

    // At the start of a conversation, show the attached document card
    renderAttachmentTray(latestUploadedFiles);

    if (composerInput) {
      composerInput.value = "";
      composerInput.focus();
    }
  }

  function renderHistoryList() {
    if (!chatHistoryListEl) return;
    chatHistoryListEl.innerHTML = "";

    if (historyCounterEl) historyCounterEl.textContent = chatSessions.length;

    if (chatSessions.length === 0) {
      chatHistoryListEl.innerHTML = `<div style="font-size:0.75rem; color:var(--text-subtle); text-align:center; padding:10px 0;">No chat history yet.</div>`;
      return;
    }

    chatSessions.forEach((s) => {
      const item = document.createElement("div");
      item.className = `history-item ${s.id === currentSessionId ? "active" : ""}`;
      item.innerHTML = `
        <span style="font-size:12px;">💬</span>
        <div class="history-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</div>
        <button class="history-del-btn" title="Delete conversation" data-id="${s.id}">✕</button>
      `;

      item.addEventListener("click", (e) => {
        if (e.target.classList.contains("history-del-btn")) return;
        loadSession(s.id);
      });

      const delBtn = item.querySelector(".history-del-btn");
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(s.id);
      });

      chatHistoryListEl.appendChild(item);
    });
  }

  function loadSession(sessionId) {
    const session = chatSessions.find((s) => s.id === sessionId);
    if (!session) return;

    currentSessionId = sessionId;
    chatContainer.innerHTML = "";

    if (!session.messages || session.messages.length === 0) {
      renderWelcomeHero();
      // Brand new conversation: show attachment chip in composer tray
      renderAttachmentTray(latestUploadedFiles);
    } else {
      session.messages.forEach((m) => {
        appendMessageToDom(m.role, m.text, m.sources || [], m.provider || "");
      });
      // Chat in progress: keep composer tray hidden
      if (composerAttachmentTray) {
        composerAttachmentTray.classList.remove("has-files");
        composerAttachmentTray.innerHTML = "";
      }
    }

    renderHistoryList();
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function deleteSession(sessionId) {
    chatSessions = chatSessions.filter((s) => s.id !== sessionId);
    saveSessionsToStorage();

    if (currentSessionId === sessionId) {
      if (chatSessions.length > 0) {
        loadSession(chatSessions[0].id);
      } else {
        createNewSession();
      }
    } else {
      renderHistoryList();
    }
  }

  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      createNewSession();
      showToast("Started a new conversation.", "info");
    });
  }

  function renderWelcomeHero() {
    chatContainer.innerHTML = `
      <div class="welcome-hero" id="welcomeHero">
        <div class="welcome-logo-icon">✦</div>
        <h2>Welcome to College GPT</h2>

        <div class="suggestion-grid">
          <div class="suggestion-card" data-question="What is the timetable for Tuesday?">
            <span class="chip-icon">📅</span>
            <span class="chip-text">What is the timetable for Tuesday?</span>
          </div>
          <div class="suggestion-card" data-question="What is the mandatory attendance requirement?">
            <span class="chip-icon">📊</span>
            <span class="chip-text">What is the mandatory attendance requirement?</span>
          </div>
          <div class="suggestion-card" data-question="What subjects and labs are scheduled for Semester V?">
            <span class="chip-icon">📚</span>
            <span class="chip-text">What subjects & labs are in Semester V?</span>
          </div>
          <div class="suggestion-card" data-question="What are the campus library timings and rules?">
            <span class="chip-icon">📖</span>
            <span class="chip-text">What are the campus library timings & rules?</span>
          </div>
        </div>
      </div>
    `;

    // Hook up suggestion cards
    chatContainer.querySelectorAll(".suggestion-card").forEach((card) => {
      card.addEventListener("click", () => {
        const q = card.getAttribute("data-question");
        if (q) {
          composerInput.value = q;
          handleSend();
        }
      });
    });
  }

  // ========================================================================
  // System Status & Attachment Tray Management
  // ========================================================================
  async function fetchSystemStatus() {
    try {
      const res = await fetch("/api/status");
      const json = await res.json();
      if (json.success && json.data) {
        renderStatus(json.data);
      }
    } catch (e) {
      console.warn("Could not fetch status:", e);
    }
  }

  function renderStatus(data) {
    if (totalChunksEl) totalChunksEl.textContent = data.total_chunks || 0;
    latestUploadedFiles = data.uploaded_files || [];

    // Check if current conversation has already asked questions
    const currentSession = chatSessions.find((s) => s.id === currentSessionId);
    if (!currentSession || !currentSession.messages || currentSession.messages.length === 0) {
      renderAttachmentTray(latestUploadedFiles);
    } else {
      // In-progress conversation: keep chat box clean
      if (composerAttachmentTray) {
        composerAttachmentTray.classList.remove("has-files");
        composerAttachmentTray.innerHTML = "";
      }
    }
  }

  // ChatGPT-Style Attachment Card Rendering in the Composer Box
  function renderAttachmentTray(files) {
    if (!composerAttachmentTray) return;
    composerAttachmentTray.innerHTML = "";

    if (!files || files.length === 0) {
      composerAttachmentTray.classList.remove("has-files");
      return;
    }

    composerAttachmentTray.classList.add("has-files");

    files.forEach((filename) => {
      const isWord = filename.endsWith(".docx") || filename.endsWith(".doc");
      const badgeClass = isWord ? "docx" : "pdf";
      const badgeText = isWord ? "DOCX" : "PDF";

      const chip = document.createElement("div");
      chip.className = "attached-file-chip";
      chip.setAttribute("title", filename);

      chip.innerHTML = `
        <button class="chip-remove-btn" title="Remove ${escapeHtml(filename)}" data-filename="${escapeHtml(filename)}">✕</button>
        <div class="chip-preview-box">
          <div class="chip-preview-header">
            <div class="chip-preview-logo"></div>
            <div class="chip-preview-title-bar"></div>
          </div>
          <div class="chip-preview-grid">
            <div class="chip-preview-grid-row"></div>
            <div class="chip-preview-grid-row"></div>
            <div class="chip-preview-grid-row"></div>
          </div>
          <div class="chip-preview-line short" style="margin-top:2px;"></div>
        </div>
        <div class="chip-footer">
          <span class="chip-badge ${badgeClass}">${badgeText}</span>
          <span class="chip-title" title="${escapeHtml(filename)}">${escapeHtml(filename)}</span>
        </div>
      `;

      // Handle document deletion on '✕' click
      const removeBtn = chip.querySelector(".chip-remove-btn");
      removeBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await deleteDocument(filename);
      });

      composerAttachmentTray.appendChild(chip);
    });
  }

  async function deleteDocument(filename) {
    try {
      const res = await fetch("/api/delete-doc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
      });
      const data = await res.json();
      if (data.success) {
        showToast(`Removed "${filename}"`, "info");
        latestUploadedFiles = latestUploadedFiles.filter((f) => f !== filename);
        fetchSystemStatus();
      } else {
        showToast(data.error || "Failed to remove document.", "error");
      }
    } catch (err) {
      showToast("Error removing document: " + err.message, "error");
    }
  }

  // ========================================================================
  // File Upload (PDF & Word Docs ONLY via Composer 📎 Button)
  // ========================================================================
  function validateAndUpload(file) {
    if (!file) return;

    if (file.size === 0) {
      showToast(`The file "${file.name}" is empty (0 bytes). Please choose a valid document.`, "error");
      fileInput.value = "";
      return;
    }

    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      showToast(`Invalid file type "${ext}"! Only PDF (.pdf) and Word documents (.docx, .doc) are permitted.`, "error");
      fileInput.value = "";
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    showToast(`Uploading and indexing "${file.name}"...`, "info");

    fetch("/api/upload", {
      method: "POST",
      body: formData,
    })
      .then(async (r) => {
        const data = await r.json().catch(() => ({}));
        if (r.ok && data.success) {
          showToast(`✓ ${data.message}`, "success");
          if (!latestUploadedFiles.includes(data.filename)) {
            latestUploadedFiles.push(data.filename);
          }
          // Immediately show the newly attached document in the composer tray!
          renderAttachmentTray([data.filename]);
          fetchSystemStatus();
        } else {
          showToast(`Upload Error: ${data.error || 'Failed to process document.'}`, "error");
        }
      })
      .catch((err) => {
        showToast(`Upload failed: ${err.message}`, "error");
      })
      .finally(() => {
        fileInput.value = "";
      });
  }

  // Single change event listener on the file input (triggered via chatbox 📎 attach button)
  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length > 0) {
        validateAndUpload(e.target.files[0]);
      }
    });
  }

  // ========================================================================
  // Chat Messaging & Targeted RAG Inference
  // ========================================================================
  function adjustTextareaHeight() {
    composerInput.style.height = "auto";
    composerInput.style.height = Math.min(composerInput.scrollHeight, 140) + "px";
  }

  if (composerInput) {
    composerInput.addEventListener("input", adjustTextareaHeight);

    composerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
  }

  if (composerForm) {
    composerForm.addEventListener("submit", (e) => {
      e.preventDefault();
      handleSend();
    });
  }

  async function handleSend() {
    const text = composerInput.value.trim();
    if (!text || isGenerating) return;

    // Remove welcome hero on first prompt
    const welcomeEl = document.getElementById("welcomeHero");
    if (welcomeEl) welcomeEl.remove();

    // After asking the first question, dismiss attached file chip from chatbox composer
    if (composerAttachmentTray) {
      composerAttachmentTray.classList.remove("has-files");
      composerAttachmentTray.innerHTML = "";
    }

    // Find current session
    let session = chatSessions.find((s) => s.id === currentSessionId);
    if (!session) {
      createNewSession();
      session = chatSessions[0];
    }

    // Set title on first message
    if (session.messages.length === 0) {
      session.title = text.length > 30 ? text.slice(0, 30) + "..." : text;
    }

    // Append User Bubble to DOM and state
    appendMessageToDom("user", text);
    session.messages.push({ role: "user", text, sources: [], provider: "" });
    saveSessionsToStorage();
    renderHistoryList();

    composerInput.value = "";
    adjustTextareaHeight();

    // Disable send button and show typing indicator
    isGenerating = true;
    if (sendBtn) sendBtn.disabled = true;
    const typingId = appendTypingIndicator();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json();
      removeTypingIndicator(typingId);

      if (data.success) {
        appendMessageToDom("assistant", data.answer, data.sources || [], data.provider);
        session.messages.push({
          role: "assistant",
          text: data.answer,
          sources: data.sources || [],
          provider: data.provider || "Google AI Studio",
        });
        saveSessionsToStorage();
      } else {
        const errMsg = `⚠️ **Error:** ${data.error || "An error occurred while retrieving answers."}`;
        appendMessageToDom("assistant", errMsg);
        session.messages.push({ role: "assistant", text: errMsg, sources: [], provider: "" });
        saveSessionsToStorage();
      }
    } catch (err) {
      removeTypingIndicator(typingId);
      const netMsg = `⚠️ **Network Error:** Could not contact College GPT server. (${err.message})`;
      appendMessageToDom("assistant", netMsg);
      session.messages.push({ role: "assistant", text: netMsg, sources: [], provider: "" });
      saveSessionsToStorage();
    } finally {
      isGenerating = false;
      if (sendBtn) sendBtn.disabled = false;
      if (composerInput) composerInput.focus();
    }
  }

  // ========================================================================
  // Message Rendering (Clean & Direct Answers without Datasets or Noise)
  // ========================================================================
  function appendMessageToDom(role, text) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const parsedMarkdown = renderMarkdown(text);

    let actionsHtml = "";
    if (role === "assistant") {
      actionsHtml = `
        <div class="msg-actions">
          <button class="action-link copy-btn" title="Copy answer">📋 Copy</button>
        </div>
      `;
    }

    row.innerHTML = `
      ${role === "assistant" ? `<div class="msg-avatar">✦</div>` : ""}
      <div class="bubble-content-wrap">
        <div class="message-bubble">
          ${parsedMarkdown}
        </div>
        ${actionsHtml}
      </div>
    `;

    // Hook up copy button
    const copyBtn = row.querySelector(".copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(text).then(() => {
          showToast("Answer copied to clipboard!", "success");
        });
      });
    }

    chatContainer.appendChild(row);
    chatContainer.scrollTop = chatContainer.scrollHeight;
  }

  function appendTypingIndicator() {
    const id = "typing_" + Date.now();
    const row = document.createElement("div");
    row.className = "message-row assistant";
    row.id = id;
    row.innerHTML = `
      <div class="msg-avatar">✦</div>
      <div class="bubble-content-wrap">
        <div class="message-bubble typing-bubble">
          <span style="font-size: 0.8rem; color: var(--text-muted); margin-right: 4px;">Searching college documents</span>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
    chatContainer.appendChild(row);
    chatContainer.scrollTop = chatContainer.scrollHeight;
    return id;
  }

  function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // ========================================================================
  // Markdown & Security Helper
  // ========================================================================
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function renderMarkdown(md) {
    if (!md) return "";
    let html = escapeHtml(md);

    // Headers
    html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
    html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
    html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");

    // Bold & Italic
    html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");

    // Inline Code
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Blockquote
    html = html.replace(/^>\s?(.*$)/gim, "<blockquote>$1</blockquote>");

    // Lists (bullet points)
    html = html.replace(/^\s*[-*]\s+(.*$)/gim, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>)/gms, "<ul>$1</ul>");

    // Line breaks
    html = html.replace(/\n\n/g, "</p><p>");
    html = html.replace(/\n/g, "<br>");

    return `<p>${html}</p>`;
  }
});
