"""
PageChat backend — chat with any webpage.

Lightweight by design: no torch, no FAISS, no model downloads.
Long pages are handled by "lite retrieval": chunks are scored against the
question with keyword overlap and only the best ones are sent to the model.
Starts in ~2 seconds and runs comfortably in 512 MB (free hosting tiers).
"""

import json
import os
import re
from collections import deque
from datetime import date
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

# DuckDuckGo search — package was renamed "duckduckgo-search" → "ddgs"
try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  CONFIG — tune everything here
# ═══════════════════════════════════════════════════════════════════════
MAX_OUTPUT_TOKENS  = 500     # hard cap on answer length (biggest cost lever)
MAX_INPUT_CHARS    = 40000   # raw page text accepted (retrieval trims it further)
MAX_QUERY_CHARS    = 500
CONTEXT_CHUNKS     = 4       # how many best-matching chunks go to the model
CHUNK_SIZE         = 700     # target characters per chunk

ENABLE_WEB_SEARCH  = True    # fallback fires a 2nd LLM call — set False to save
DAILY_GLOBAL_LIMIT = 500     # questions/day across ALL users (budget ceiling)
PER_IP_DAILY_LIMIT = 20      # questions/day per user

ALLOWED_MODELS = {
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini"
}
DEFAULT_MODEL = "openai/gpt-4o-mini"
# ═══════════════════════════════════════════════════════════════════════

MESH_KEY = os.getenv("MESH_API", "")
if not MESH_KEY:
    print("[warn] MESH_API is not set — add it to .env (local) or environment variables (deploy).")

mesh_client = AsyncOpenAI(
    api_key=MESH_KEY or "missing-key",
    base_url="https://api.meshapi.ai/v1",
)

MODEL_NAMES = {
    "google/gemini-2.5-flash": "Gemini 2.5 Flash",
    "openai/gpt-4o-mini":      "GPT-4o Mini",
    "deepseek/deepseek-r1":    "DeepSeek R1",
}

# Models that can't do tool calling — web-search fallback is skipped for them
NO_TOOLS_MODELS = {"deepseek/deepseek-r1"}

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web when the page context does not contain the answer.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
}

app = FastAPI(title="PageChat Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

session_db: Dict[str, deque] = {}


# ── Rate limiting (in-memory; resets daily and on restart) ──────────────
_usage = {"day": date.today(), "global": 0, "per_ip": {}}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request):
    today = date.today()
    if _usage["day"] != today:
        _usage["day"] = today
        _usage["global"] = 0
        _usage["per_ip"] = {}

    ip = _client_ip(request)
    used = _usage["per_ip"].get(ip, 0)

    if _usage["global"] >= DAILY_GLOBAL_LIMIT:
        raise HTTPException(429, "Daily service limit reached. Please try again tomorrow.")
    if used >= PER_IP_DAILY_LIMIT:
        raise HTTPException(429, "You've reached today's question limit. Please come back tomorrow.")

    _usage["global"] += 1
    _usage["per_ip"][ip] = used + 1


# ── Lite retrieval: pick the chunks most relevant to the question ───────
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "of", "in", "on", "to",
    "and", "or", "for", "with", "at", "by", "it", "its", "this", "that", "what",
    "which", "who", "how", "why", "when", "where", "do", "does", "did", "can",
    "about", "as", "from", "me", "my", "you", "your", "i", "we", "us",
}


def _words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS]


def _chunk(text: str) -> list:
    """Split on paragraph boundaries into ~CHUNK_SIZE pieces."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 1 <= CHUNK_SIZE:
            buf = f"{buf}\n{p}".strip()
        else:
            if buf:
                chunks.append(buf)
            buf = p[:CHUNK_SIZE]
    if buf:
        chunks.append(buf)
    return chunks


def build_context(text: str, query: str) -> str:
    text = (text or "")[:MAX_INPUT_CHARS]
    chunks = _chunk(text)
    if len(chunks) <= CONTEXT_CHUNKS:
        return "\n\n".join(chunks)

    q_words = set(_words(query))
    scored = []
    for i, c in enumerate(chunks):
        c_words = _words(c)
        score = sum(1 for w in c_words if w in q_words)
        scored.append((score, i, c))

    top = sorted(scored, key=lambda t: t[0], reverse=True)[:CONTEXT_CHUNKS]
    if top and top[0][0] == 0:
        # Question matched nothing — fall back to the start of the page
        return "\n\n".join(chunks[:CONTEXT_CHUNKS])
    top.sort(key=lambda t: t[1])  # restore page order
    return "\n\n".join(c for _, _, c in top)


# ── Session history ─────────────────────────────────────────────────────
def get_history(session_id: str) -> deque:
    if session_id not in session_db:
        session_db[session_id] = deque(maxlen=6)
    return session_db[session_id]


def format_history(history: deque) -> str:
    return "".join(f"User: {u}\nAI: {a}\n" for u, a in history)


# ── Web search fallback ─────────────────────────────────────────────────
def run_web_search(query: str, max_results: int = 5) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        joined = "\n\n".join(f"{r.get('title', '')}\n{r.get('body', '')}" for r in results)
        return joined or "No results found."
    except Exception as e:  # search being down should never crash a chat
        print(f"[web_search error] {e}")
        return "Web search is currently unavailable."


# ── Model call ──────────────────────────────────────────────────────────
async def ask_model(model: str, context: str, query: str, history_str: str) -> dict:
    """Returns {'answer': str, 'used_search': bool}."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant answering questions about a webpage.\n"
                "1. Answer from the provided page context and conversation history.\n"
                "2. If the context doesn't contain the answer, call the web_search tool.\n"
                "3. Answer directly and concisely. Use plain text, no markdown headers."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Conversation so far:\n{history_str}\n\n"
                f"Page content:\n{context}\n\n"
                f"Question: {query}"
            ),
        },
    ]

    supports_tools = ENABLE_WEB_SEARCH and model not in NO_TOOLS_MODELS
