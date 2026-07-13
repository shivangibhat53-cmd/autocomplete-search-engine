"""
gRPC server implementing BKTreeService.

Handles:
  FuzzySearch — the core operation, O(log n) via BK-Tree
  InsertWord  — keeps BK-Tree in sync when new words are added
  Health      — liveness check for the router's health monitor
  GetStats    — tree statistics for monitoring
"""
import grpc
import asyncio
from src.bk_tree import BKTree
from src.grpc_generated import (
    autocomplete_pb2,
    autocomplete_pb2_grpc,
)


class BKTreeServicer(
    autocomplete_pb2_grpc.BKTreeServiceServicer
):
    """
    Implements every RPC defined in the BKTreeService proto.
    Holds the BK-Tree in memory — one instance for the service.
    """

    def __init__(self, bk_tree: BKTree):
        self.bk_tree = bk_tree

    async def FuzzySearch(self, request, context):
        """
        Find words within max_distance edits of the query.

        This is the critical path — called by the router on
        every fuzzy search request. Must be fast.

        The BK-Tree gives us O(log n) average case via
        triangle inequality pruning — most of the tree is
        never visited.
        """
        query        = request.query.lower().strip()
        max_distance = request.max_distance or 2
        limit        = request.limit or 10

        if not query:
            return autocomplete_pb2.FuzzySearchResponse(
                query   = query,
                results = [],
                total   = 0,
            )

        # BK-Tree search — O(log n)
        raw     = self.bk_tree.search(query,
                                      max_distance=max_distance)
        results = []

        for word, dist, freq in raw[:limit]:
            results.append(
                autocomplete_pb2.FuzzySearchResult(
                    word      = word,
                    distance  = dist,
                    frequency = freq,
                )
            )

        return autocomplete_pb2.FuzzySearchResponse(
            query   = query,
            results = results,
            total   = len(results),
        )

    async def InsertWord(self, request, context):
        """
        Insert or update a word in the BK-Tree.
        Called when new words are added via the API.
        """
        try:
            word = request.word.lower().strip()
            self.bk_tree.insert(word, request.frequency or 1)
            return autocomplete_pb2.WordResponse(
                success = True,
                message = f"Inserted '{word}' into BK-Tree"
            )
        except Exception as e:
            return autocomplete_pb2.WordResponse(
                success = False,
                message = str(e)
            )

    async def Health(self, request, context):
        """Liveness check — confirms service is running."""
        return autocomplete_pb2.HealthResponse(
            shard_name = "bk-tree-service",
            status     = "healthy",
            word_count = self.bk_tree.size(),
        )

    async def GetStats(self, request, context):
        """Return BK-Tree statistics."""
        stats = self.bk_tree.stats()
        return autocomplete_pb2.BKStatsResponse(
            size       = stats["size"],
            depth      = stats["depth"],
            word_count = self.bk_tree.size(),
            status     = "healthy",
        )


async def serve(bk_tree: BKTree, port: int) -> None:
    """Start the gRPC server for the BK-Tree service."""
    server = grpc.aio.server()

    autocomplete_pb2_grpc.add_BKTreeServiceServicer_to_server(
        BKTreeServicer(bk_tree),
        server
    )

    listen_addr = f"0.0.0.0:{port}"
    server.add_insecure_port(listen_addr)

    print(f"✅ BK-Tree gRPC server listening on {listen_addr}")
    await server.start()
    await server.wait_for_termination()