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
