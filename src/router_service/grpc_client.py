"""
gRPC client used by the Router to call Shard services.

Each shard exposes a gRPC server (AutocompleteService).
The router calls it using this client.
"""
import grpc
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.grpc_generated import autocomplete_pb2, autocomplete_pb2_grpc


class ShardGRPCClient:
    """
    Wraps gRPC calls to a single shard.
    One instance per shard in the router.
    """

    def __init__(self, shard_name: str, address: str):
        """
        address: "hostname:port" e.g. "shard-1:50051"
        """
        self.shard_name = shard_name
        self.address    = address
        # Insecure channel for internal Docker network communication
        # In production: use TLS with grpc.secure_channel()
        self.channel    = grpc.aio.insecure_channel(address)
        self.stub       = autocomplete_pb2_grpc.AutocompleteServiceStub(
            self.channel
        )

    async def search(self, prefix: str,
                     limit: int = 10,
                     fuzzy: bool = False) -> dict:
        """Call the shard's Search RPC."""
        request = autocomplete_pb2.SearchRequest(
            prefix=prefix,
            limit=limit,
            fuzzy=fuzzy,
        )
        response = await self.stub.Search(request, timeout=3.0)
        return {
            "query"     : response.query,
            "shard"     : response.shard_name,
            "results"   : [
                {
                    "word"  : s.word,
                    "score" : s.score,
                    "source": s.source,
                }
                for s in response.results
            ],
            "total"     : response.total,
        }

    async def health(self) -> dict:
        """Call the shard's Health RPC."""
        request  = autocomplete_pb2.HealthRequest()
        response = await self.stub.Health(request, timeout=2.0)
        return {
            "shard_name": response.shard_name,
            "status"    : response.status,
            "word_count": response.word_count,
        }

    async def insert_word(self, word: str,
                          frequency: int = 1) -> dict:
        """Call the shard's InsertWord RPC."""
        request  = autocomplete_pb2.WordRequest(
            word=word, frequency=frequency
        )
        response = await self.stub.InsertWord(request, timeout=3.0)
        return {"success": response.success, "message": response.message}

    async def delete_word(self, word: str) -> dict:
        """Call the shard's DeleteWord RPC."""
        request  = autocomplete_pb2.WordRequest(word=word)
        response = await self.stub.DeleteWord(request, timeout=3.0)
        return {"success": response.success, "message": response.message}

    async def get_stats(self) -> dict:
        """Call the shard's GetStats RPC."""
        request  = autocomplete_pb2.StatsRequest()
        response = await self.stub.GetStats(request, timeout=3.0)
        return {
            "shard_name": response.shard_name,
            "word_count": response.word_count,
            "top_words" : [
                {"word": s.word, "score": s.score}
                for s in response.top_words
            ],
        }

    async def close(self) -> None:
        await self.channel.close()

class BKTreeGRPCClient:
    """
    gRPC client for the BK-Tree service.
    Used by the router to make fuzzy search requests.
    """

    def __init__(self, address: str):
        """address: 'hostname:port' e.g. 'bk-tree-service:50060'"""
        self.address = address
        self.channel = grpc.aio.insecure_channel(address)
        self.stub    = autocomplete_pb2_grpc.BKTreeServiceStub(
            self.channel
        )

    async def fuzzy_search(self,
                           query       : str,
                           max_distance: int = 2,
                           limit       : int = 10) -> dict:
        """Call BK-Tree service's FuzzySearch RPC."""
        request  = autocomplete_pb2.FuzzySearchRequest(
            query        = query,
            max_distance = max_distance,
            limit        = limit,
        )
        response = await self.stub.FuzzySearch(
            request, timeout=3.0
        )
        return {
            "query"  : response.query,
            "results": [
                {
                    "word"     : r.word,
                    "distance" : r.distance,
                    "frequency": r.frequency,
                }
                for r in response.results
            ],
            "total"  : response.total,
        }

    async def insert_word(self,
                          word     : str,
                          frequency: int = 1) -> dict:
        """Keep BK-Tree in sync when new words are added."""
        request  = autocomplete_pb2.WordRequest(
            word=word, frequency=frequency
        )
        response = await self.stub.InsertWord(
            request, timeout=3.0
        )
        return {
            "success": response.success,
            "message": response.message,
        }

    async def health(self) -> dict:
        """Health check for the health monitor."""
        request  = autocomplete_pb2.HealthRequest()
        response = await self.stub.Health(request, timeout=2.0)
        return {
            "status"    : response.status,
            "word_count": response.word_count,
        }

    async def close(self) -> None:
        await self.channel.close()