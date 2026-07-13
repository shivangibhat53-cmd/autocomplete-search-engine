"""
Shard Service — one instance per shard container.

Each shard:
  1. Reads SHARD_NAME and ALL_SHARDS from environment
  2. Connects to Postgres and loads only its assigned words
  3. Starts a gRPC server to serve search requests
  4. Optionally exposes a minimal HTTP health endpoint
"""
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from src.trie import Trie
from src.app import trie as shared_trie
from src.db.database import init_db, close_db
from src.shard_service.loader import load_shard_words
from src.shard_service.grpc_server import serve
from src.api.middleware import LoggingMiddleware

load_dotenv()

SHARD_NAME      = os.getenv("SHARD_NAME", "shard-1")
SHARD_PORT      = int(os.getenv("SHARD_PORT", "50051"))
ALL_SHARDS_STR  = os.getenv(
    "ALL_SHARDS",
    "shard-1,shard-2,shard-3"
)
ALL_SHARD_NAMES = [s.strip() for s in ALL_SHARDS_STR.split(",")]


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\n{SHARD_NAME} starting up...")
    print(f"  All shards: {ALL_SHARD_NAMES}")
    print(f"  gRPC port : {SHARD_PORT}")

    await init_db()

    word_count = await load_shard_words(
        shared_trie,
        SHARD_NAME,
        ALL_SHARD_NAMES,
    )

    print(f"✅ {SHARD_NAME} ready — {word_count} words loaded")

    # Start gRPC server with explicit error catching
    async def run_grpc():
        try:
            await serve(SHARD_NAME, shared_trie, SHARD_PORT)
        except Exception as e:
            print(f"❌ gRPC server failed: {e}")
            import traceback
            traceback.print_exc()

    grpc_task = asyncio.create_task(run_grpc())

    # Give gRPC a moment to start and catch immediate failures
    await asyncio.sleep(2)

    if grpc_task.done():
        print(f"❌ gRPC task died immediately")
        exc = grpc_task.exception()
        if exc:
            print(f"   Error: {exc}")
    else:
        print(f"✅ gRPC task running on port {SHARD_PORT}")

    yield

    grpc_task.cancel()
    try:
        await grpc_task
    except asyncio.CancelledError:
        pass

    await close_db()
    print(f"{SHARD_NAME} shut down")


app = FastAPI(
    title    = f"Autocomplete Shard — {SHARD_NAME}",
    version  = "1.0.0",
    lifespan = lifespan,
)

app.add_middleware(LoggingMiddleware)


@app.get("/health")
async def health():
    """Minimal HTTP health check alongside the gRPC server."""
    return {
        "shard"     : SHARD_NAME,
        "status"    : "healthy",
        "word_count": shared_trie.size(),
    }