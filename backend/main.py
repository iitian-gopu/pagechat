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


