// PageChat popup logic
// ─────────────────────────────────────────────────────────────
// Change this one line after deploying (e.g. "https://pagechat-backend.onrender.com")
const API = "https://pagechat-bp2d.onrender.com";
// ─────────────────────────────────────────────────────────────

const chatLog     = document.getElementById("chatLog");
const emptyState  = document.getElementById("emptyState");
const queryInput  = document.getElementById("queryInput");
const sendBtn     = document.getElementById("sendBtn");
const modelSelect = document.getElementById("modelSelect");
const statusDot   = document.getElementById("statusDot");
const newChatBtn  = document.getElementById("newChatBtn");
const metaHint    = document.getElementById("metaHint");

let sessionId = "default";
let busy = false;

// ── Backend status + models ─────────────────────────────────
async function init() {
  try {
    const res = await fetch(`${API}/models`);
    if (!res.ok) throw new Error();
    const data = await res.json();

    modelSelect.innerHTML = "";
    data.models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.name;
      modelSelect.appendChild(opt);
    });
    if (data.default) modelSelect.value = data.default;

    statusDot.classList.add("online");
    statusDot.title = "Backend connected";
  } catch {
    statusDot.classList.add("offline");
    statusDot.title = "Backend unreachable";
    modelSelect.innerHTML = `<option value="">Backend offline</option>`;
    addError(`Can't reach the backend at ${API}. Start it and reopen this popup.`);
  }

  chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
    if (tabs[0]) sessionId = String(tabs[0].id);
  });
}

// ── Page text extraction ────────────────────────────────────
function grabText() {
  return document.body.innerText;
}

function extractPage() {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      const tab = tabs[0];
      if (!tab || tab.url.startsWith("chrome://") || tab.url.startsWith("edge://")) {
        reject(new Error("This page can't be read. Try a normal website."));
        return;
      }
      chrome.scripting.executeScript(
        { target: { tabId: tab.id }, function: grabText },
        results => {
