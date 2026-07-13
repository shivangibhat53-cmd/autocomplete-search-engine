"""
Router Service — the entry point for all autocomplete requests.

Responsibilities:
  1. Maintain the consistent hash ring
  2. Route requests to the correct shard via gRPC
  3. Monitor shard health and update ring when shards go up/down
  4. Merge personal history (Redis) with shard results
  5. Cache results in Redis
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from src.sharding.consistent_hash import ConsistentHashRing
from src.router_service.grpc_client import ShardGRPCClient, BKTreeGRPCClient
from src.router_service.circuit_breaker import CircuitBreakerRegistry
from src.router_service.health_monitor import HealthMonitor
from src.router_service.routes import router as api_router
from src.cache.redis_client import init_redis, close_redis
from src.api.middleware import LoggingMiddleware

from src.app import trie, bk_tree
from src.db.database import init_db, close_db
from src.db.models import get_all_words
from src.api.routes import words
load_dotenv()

# ── Shard configuration from environment ──────────────────────
# Format: "shard-1:50051,shard-2:50052,shard-3:50053"
# Set in docker-compose or .env
def parse_shard_addresses() -> dict:
    raw = os.getenv(
        "SHARD_ADDRESSES",
        "shard-1:50051,shard-2:50052,shard-3:50053"
    )
    shards = {}
    for entry in raw.split(","):
        name, port = entry.strip().split(":")
        # In Docker: hostname = service name (e.g. "shard-1")
        # Locally: hostname = "localhost"
        host = name if os.getenv("DOCKER_ENV") else "localhost"
        shards[name] = f"{host}:{port}"
    return shards


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup:
      1. Connect to Redis
      2. Create gRPC clients for all shards
      3. Build consistent hash ring
      4. Start health monitor

    Shutdown:
      5. Stop health monitor
      6. Close all gRPC connections
      7. Close Redis
    """
    print("Router starting up...")
    # Redis for caching + personal history
    await init_redis()

    # No DB connection needed in router anymore —
    # word loading moved to bk_tree_service
    # DB writes (upsert_word) still happen in routes
    # so we still need init_db for those
    await init_db()

    shard_addresses = parse_shard_addresses()
    bk_tree_address = os.getenv(
        "BK_TREE_ADDRESS",
        "bk-tree-service:50060"
    )
    if not os.getenv("DOCKER_ENV"):
        bk_tree_address = "localhost:50060"

    print(f"Configured shards: {shard_addresses}")
    print(f"BK-Tree service  : {bk_tree_address}")

    clients   = {
        name: ShardGRPCClient(name, address)
        for name, address in shard_addresses.items()
    }
    bk_client = BKTreeGRPCClient(bk_tree_address)

    ring     = ConsistentHashRing(
        list(shard_addresses.keys()),
        virtual_nodes=150
    )
    breakers = CircuitBreakerRegistry()
    for name in shard_addresses:
        breakers.get(name)

    monitor = HealthMonitor(
        clients  = clients,
        ring     = ring,
        breakers = breakers,
    )
    await monitor.start()

    app.state.clients   = clients
    app.state.bk_client = bk_client
    app.state.ring      = ring
    app.state.breakers  = breakers
    app.state.monitor   = monitor

    print(f"✅ Router ready — {len(clients)} shards + BK-Tree service")

    yield

    print("Router shutting down...")
    await monitor.stop()

    for client in clients.values():
        await client.close()

    await bk_client.close()
    await close_db()
    await close_redis()

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title      = "Autocomplete Router Service",
    description= "Consistent hashing router for autocomplete shards",
    version    = "1.0.0",
    lifespan   = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(LoggingMiddleware)
app.include_router(api_router)
