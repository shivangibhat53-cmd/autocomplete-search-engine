"""
BK-Tree Microservice.

A standalone FastAPI + gRPC service that:
  1. Loads ALL words from PostgreSQL at startup
  2. Builds a BK-Tree for O(log n) fuzzy search
  3. Serves FuzzySearch requests via gRPC
  4. Exposes an HTTP health endpoint for Docker healthcheck
  5. Stays completely independent of shard health

Why separate from shards:
  - Shards hold 1/3 of words each — BK-Tree needs ALL words
  - Shard failures don't affect fuzzy search availability
  - Can be scaled independently (fuzzy search is CPU-heavy)
  - Clean separation of concerns — prefix search vs fuzzy search
"""
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv

from src.bk_tree import BKTree
from src.db.database import init_db, close_db
from src.bk_tree_service.loader import load_all_words
from src.bk_tree_service.grpc_server import serve
from src.api.middleware import LoggingMiddleware

load_dotenv()

GRPC_PORT = int(os.getenv("BK_TREE_GRPC_PORT", "50060"))

# Shared BK-Tree instance
bk_tree = BKTree()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. Connect to Postgres
      2. Load ALL words into BK-Tree
      3. Start gRPC server

    Shutdown:
      4. Close DB connection
    """
    print("\nBK-Tree service starting up...")
    print(f"  gRPC port: {GRPC_PORT}")

    await init_db()

    word_count = await load_all_words(bk_tree)
    print(f"✅ BK-Tree ready — {word_count} words, "
          f"depth={bk_tree.depth()}")

    # Start gRPC server as background task
    async def run_grpc():
        try:
            await serve(bk_tree, GRPC_PORT)
        except Exception as e:
            print(f"❌ BK-Tree gRPC server failed: {e}")
            import traceback
            traceback.print_exc()

    grpc_task = asyncio.create_task(run_grpc())

    # Give gRPC time to initialise
    await asyncio.sleep(1)

    if grpc_task.done():
        print("❌ BK-Tree gRPC task died immediately")
    else:
        print(f"✅ BK-Tree gRPC task running on port {GRPC_PORT}")

    yield

    grpc_task.cancel()
    try:
        await grpc_task
    except asyncio.CancelledError:
        pass

    await close_db()
    print("BK-Tree service shut down")


app = FastAPI(
    title   = "BK-Tree Fuzzy Search Service",
    version = "1.0.0",
    lifespan= lifespan,
)

app.add_middleware(LoggingMiddleware)


@app.get("/health")
async def health():
    """HTTP health check — used by Docker and health monitor."""
    stats = bk_tree.stats()
    return {
        "service"   : "bk-tree",
        "status"    : "healthy",
        "word_count": bk_tree.size(),
        "bk_depth"  : stats["depth"],
        "grpc_port" : GRPC_PORT,
    }