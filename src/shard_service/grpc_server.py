"""
gRPC server that runs on each shard.
Implements the AutocompleteService contract from autocomplete.proto.
"""
import grpc
import asyncio
from src.grpc_generated import autocomplete_pb2, autocomplete_pb2_grpc
from src.trie import Trie
from src.fuzzy import fuzzy_autocomplete


class AutocompleteServicer(
    autocomplete_pb2_grpc.AutocompleteServiceServicer
):
    """
    Implements every RPC defined in autocomplete.proto.
    One instance per shard, holds that shard's Trie in memory.
    """

    def __init__(self, shard_name: str, trie: Trie):
        self.shard_name = shard_name
        self.trie       = trie

    async def Search(self, request, context):
        """Handle a search request — return top suggestions."""
        prefix = request.prefix.lower().strip()
        limit  = request.limit or 10

        if request.fuzzy:
            raw     = fuzzy_autocomplete(
                self.trie, prefix,
                max_distance=2, limit=limit
            )
            results = [
                autocomplete_pb2.Suggestion(
                    word   = word,
                    score  = float(freq),
                    source = match_type,
                )
                for word, match_type, freq in raw
            ]
        else:
            raw     = self.trie.autocomplete_with_scores(
                prefix, limit=limit
            )
            results = [
                autocomplete_pb2.Suggestion(
                    word   = word,
                    score  = float(score),
                    source = "exact",
                )
                for word, score in raw
            ]

        return autocomplete_pb2.SearchResponse(
            query      = prefix,
            results    = results,
            total      = len(results),
            shard_name = self.shard_name,
        )

    async def Health(self, request, context):
        """Health check — confirms this shard is alive and responsive."""
        return autocomplete_pb2.HealthResponse(
            shard_name = self.shard_name,
            status     = "healthy",
            word_count = self.trie.size(),
        )

    async def InsertWord(self, request, context):
        """Insert a word into this shard's Trie."""
        try:
            self.trie.insert(request.word, request.frequency)
            return autocomplete_pb2.WordResponse(
                success = True,
                message = f"Inserted '{request.word}'"
            )
        except Exception as e:
            return autocomplete_pb2.WordResponse(
                success = False,
                message = str(e)
            )

    async def DeleteWord(self, request, context):
        """Delete a word from this shard's Trie."""
        deleted = self.trie.delete(request.word)
        return autocomplete_pb2.WordResponse(
            success = deleted,
            message = (f"Deleted '{request.word}'"
                       if deleted else
                       f"'{request.word}' not found")
        )

    async def GetStats(self, request, context):
        """Return stats about this shard's Trie."""
        top_raw = self.trie.autocomplete_with_scores("", limit=10)
        top     = [
            autocomplete_pb2.Suggestion(
                word  = w,
                score = float(s),
            )
            for w, s in top_raw
        ]
        return autocomplete_pb2.StatsResponse(
            shard_name = self.shard_name,
            word_count = self.trie.size(),
            top_words  = top,
        )


async def serve(shard_name: str, trie: Trie, port: int) -> None:
    """Start the gRPC server for this shard."""
    server = grpc.aio.server()

    autocomplete_pb2_grpc.add_AutocompleteServiceServicer_to_server(
        AutocompleteServicer(shard_name, trie),
        server
    )

    listen_addr = f"0.0.0.0:{port}"
    server.add_insecure_port(listen_addr)

    print(f"✅ gRPC server for {shard_name} listening on {listen_addr}")
    await server.start()
    await server.wait_for_termination()