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
