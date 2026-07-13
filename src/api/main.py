"""
FastAPI application setup.

Middleware registered:
  - LoggingMiddleware only — runs on every request (correct for logging)
  - SessionMiddleware removed — replaced by Depends(get_session) per-route

Lifespan handles startup/shutdown:
  - Connect DB and Redis
  - Load words from Postgres into Trie
  - Seed sample data if DB is empty
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.db.database import init_db, close_db
from src.cache.redis_client import init_redis, close_redis
from src.db.models import get_all_words
from src.app import trie, bk_tree 
from src.api.routes import search, words, health, selection
from src.api.middleware import LoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    print("Starting up...")

    await init_db()
    await init_redis()

    # Load words from PostgreSQL into Trie
    words_from_db = await get_all_words()
    for row in words_from_db:
        trie.insert(row["word"], row["frequency"])
        bk_tree.insert(row["word"], row["frequency"])   # ← add this

    print(f"✅ Trie loaded with {trie.size()} words from database")
    print(f"✅ BK-Tree loaded with {bk_tree.size()} words")

    # Seed sample data if DB is empty
    if trie.size() == 0:
        from src.data_loader import load_sample_data
        from src.db.models import upsert_word

        load_sample_data(trie)

        # Rebuild all suggestion caches after bulk load
        trie.rebuild_all_suggestions()

        # Persist to DB
        for word in trie.all_words():
            freq = trie.get_frequency(word)
            bk_tree.insert(word, freq)
            await upsert_word(word, freq)

        print(f"✅ Sample data loaded: {trie.size()} words")

    yield

    # Shutdown
    print("Shutting down...")
    await close_db()
    await close_redis()


# ── Rate limiter ───────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title      = "Autocomplete Search Engine",
    description= "Trie-based autocomplete with personalization, Redis caching, and PostgreSQL persistence",
    version    = "1.0.0",
    lifespan   = lifespan,
)

# ── Rate limit error handler ───────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ───────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Logging middleware only ─────────────────────────────────────
# Session is handled per-route via Depends(get_session)
# so /health, /docs, /stats never touch cookie logic
app.add_middleware(LoggingMiddleware)

# ── Routers ────────────────────────────────────────────────────
app.include_router(health.router,     tags=["health"])
app.include_router(search.router,     tags=["search"])
app.include_router(words.router,      tags=["words"])
app.include_router(selection.router,  tags=["selection"])