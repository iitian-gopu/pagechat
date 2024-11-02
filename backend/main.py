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

