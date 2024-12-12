# PageChat — Chat with any webpage

A Chrome extension + FastAPI backend that lets you ask questions about the webpage you're on. Answers come from the page itself via retrieval; when the page doesn't have the answer, the model automatically falls back to live web search.

**Try it:** open any article → click the extension → ask "summarize this" or "when was this released?"



---

## Features

- **Chat interface in the popup** — conversation history, typing indicator, per-answer copy button, live backend status indicator
- **Lite retrieval (RAG-style) on every question** — long pages are chunked and keyword-scored; only the most relevant chunks reach the model, cutting token cost and improving focus
- **Automatic web search fallback** — the LLM decides via tool-calling when the page can't answer, then re-answers from DuckDuckGo results (tagged in the UI)
- **Multi-model** — switch between Gemini 2.5 Flash, GPT-4o Mini, and DeepSeek R1 mid-conversation via a single OpenAI-compatible gateway
- **Per-tab session memory** — follow-up questions keep context per browser tab
- **Production cost & abuse controls** — output-token caps, per-IP and global daily rate limits, model allowlist, input truncation

## Architecture

```
┌─────────────────┐     page text + question      ┌──────────────────────────┐
│ Chrome Extension │ ────────────────────────────▶ │      FastAPI backend     │
│  (Manifest V3)   │ ◀──────────────────────────── │                          │
└─────────────────┘        answer (JSON)          │  1. rate limit (IP/day)  │
                                                  │  2. lite retrieval:      │
                                                  │     chunk → keyword      │
                                                  │     score → top-4        │
                                                  │  3. LLM via Mesh API     │──▶ Gemini / GPT / DeepSeek
                                                  │  4. tool-call fallback   │──▶ DuckDuckGo search
                                                  └──────────────────────────┘
```

**Request flow:** the popup extracts the active tab's visible text (`chrome.scripting`), posts it with the question to `/chat`, the backend trims it to the most relevant chunks, calls the selected model with a `web_search` tool attached, and returns the answer (with a flag when search was used).

## Engineering decisions

**Keyword-scored retrieval instead of embedding RAG.** The first iteration used `sentence-transformers` + FAISS. That worked, but torch needs ~1 GB RAM — forcing paid hosting (~$25/mo) — plus slow cold starts and a runtime dependency on HuggingFace model downloads. I replaced it with a ~30-line pure-Python retriever: paragraph-boundary chunking, stopword-filtered keyword overlap scoring, top-k selection with original page order preserved, and a fallback to the page opening when nothing matches. For webpage Q&A the vocabulary of the question usually appears verbatim in the answering paragraph, so the semantic-matching loss is small — and the payoff is a 6-package backend that boots in ~2 seconds and deploys on a free 512 MB tier. `build_context()` is deliberately the single seam where hosted embeddings could be swapped back in.

**Cost is bounded by design, not by hope.** Every completion call carries `max_tokens`; requests are rate-limited per-IP and globally per day (in-memory, proxy-aware via `X-Forwarded-For`); only low-cost models are exposed through `/models`, so the client can't select an expensive one; incoming page text is truncated before processing. Worst-case daily spend is a config constant, not a surprise.

**Graceful degradation everywhere.** Missing API key → clear 500 at request time instead of a crash at import time. DuckDuckGo down → the chat still answers from page context. Tool-calling unsupported (DeepSeek R1) → the fallback path is skipped, not errored. `chrome://` pages → caught client-side with an actionable message.

## Tech stack

| Layer | Tech |
|---|---|
| Extension | Vanilla JS, Chrome Manifest V3 (`activeTab`, `scripting`) |
| Backend | Python, FastAPI, Uvicorn |
| LLM gateway | Mesh API (OpenAI-compatible, async client) |
| Retrieval | Custom pure-Python keyword-scored chunking |
| Search fallback | DuckDuckGo (`ddgs`) via LLM tool-calling |
| Deploy | Render free tier (`render.yaml` blueprint) |

## Run locally

**Backend**

```bash
cd backend
pip install -r requirements.txt          # 6 small packages, seconds to install
cp .env.example .env                     # Windows: copy .env.example .env
# edit .env → MESH_API=your_key
uvicorn main:app --reload                # or: python -m uvicorn main:app --reload
```

Verify: http://127.0.0.1:8000/models should return JSON with 3 models.

**Extension**

1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select `extension/`
2. Open any normal webpage, click the PageChat icon (green dot = backend connected), ask away.

## Deploy

1. Push to GitHub (`.env` is gitignored).
2. [Render](https://render.com) → New → Web Service → connect the repo. Set **Root Directory** = `backend`, start command `uvicorn main:app --host 0.0.0.0 --port $PORT`, plan **Free**.
3. Add `MESH_API` in the Environment tab → deploy → confirm `https://YOUR-APP.onrender.com/models` returns JSON.
4. Point the extension at it: `extension/popup.js` line 4 → your Render URL → reload the extension.

*Free-tier note: the service sleeps after ~15 min idle; first request after that takes ~30–50 s to wake.*

## Configuration

All tunables live in one CONFIG block at the top of `backend/main.py`:

| Constant | Purpose |
