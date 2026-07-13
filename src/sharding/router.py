##This file is not required it is a Simulation file 
"""
Router service — sits between Nginx and the shard instances.

Responsibilities:
  1. Receive an autocomplete request with a prefix
  2. Use the consistent hash ring to find which shard owns that prefix
  3. Forward the request to that specific shard
  4. Return the shard's response to the caller

In production this would be a separate FastAPI service running on its
own port, with each shard being a separate container. For local
development we simulate multiple shards as separate Trie instances
in the same process — the routing logic is identical either way.

Real production flow:
  Client → Nginx → Router (this service) → Shard container → response

Local simulation flow:
  Client → Router → Shard Trie instance → response
"""
import httpx
from src.sharding.consistent_hash import ConsistentHashRing


# ── Shard registry ────────────────────────────────────────────
# In production these would be container URLs:
#   "shard-1": "http://autocomplete_shard1:8001"
#   "shard-2": "http://autocomplete_shard2:8002"
# For local simulation we map to localhost ports
SHARD_URLS = {
    "shard-1": "http://localhost:8001",
    "shard-2": "http://localhost:8002",
    "shard-3": "http://localhost:8003",
}


class ShardRouter:
    """
    Routes autocomplete requests to the correct shard using
    consistent hashing on the first 2 characters of the prefix.

    All words starting with the same 2 characters live on the same
    shard — so "py", "python", "pytorch", "pycharm" all route to
    whichever shard owns the "py" hash key. This means one shard
    holds the complete Trie subtree for those prefixes, and the
    router never needs to fan out to multiple shards for a single
    prefix query.

    The tradeoff: global operations (top words overall, fuzzy search
    across all words) must query ALL shards and merge results.
    """

    def __init__(self, shard_urls: dict = None):
        shards      = list((shard_urls or SHARD_URLS).keys())
        self.urls   = shard_urls or SHARD_URLS
        self.ring   = ConsistentHashRing(shards, virtual_nodes=150)

    def get_shard_for_prefix(self, prefix: str) -> tuple[str, str]:
        """
        Returns (shard_name, shard_url) for a given prefix.
        Uses only first 2 chars to preserve prefix locality.
        """
        shard_name = self.ring.get_shard_for_prefix(prefix)
        shard_url  = self.urls[shard_name]
        return shard_name, shard_url

    async def search(self, prefix: str, limit: int = 10,
                     fuzzy: bool = False) -> dict:
        """
        Route a search request to the correct shard.
        Returns the shard's response plus metadata showing
        which shard handled the request.
        """
        shard_name, shard_url = self.get_shard_for_prefix(prefix)

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{shard_url}/search",
                params={"q": prefix, "limit": limit, "fuzzy": fuzzy}
            )
            response.raise_for_status()
            data = response.json()

        # Add routing metadata so the caller can see which shard responded
        data["shard"] = shard_name
        return data

    async def search_all_shards(self, prefix: str,
                                limit: int = 10) -> dict:
        """
        Fan out to ALL shards — used for global operations like
        "top words overall" or fuzzy search that might span shards.

        Merges results from all shards and re-ranks by score.
        This is more expensive (N network calls) but necessary
        when you can't know which shard has the best results.
        """
        all_results = []

        async with httpx.AsyncClient(timeout=5.0) as client:
            for shard_name, shard_url in self.urls.items():
                try:
                    response = await client.get(
                        f"{shard_url}/search",
                        params={"q": prefix, "limit": limit}
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for r in data.get("results", []):
                            r["shard"] = shard_name
                            all_results.append(r)
                except httpx.RequestError:
                    # One shard being down shouldn't kill the whole request
                    continue

        # Re-rank merged results by score
        all_results.sort(key=lambda x: x.get("score") or 0, reverse=True)

        return {
            "query"  : prefix,
            "results": all_results[:limit],
            "total"  : len(all_results[:limit]),
            "shards" : list(self.urls.keys()),
        }

    def add_shard(self, shard_name: str, shard_url: str) -> None:
        """
        Add a new shard to the ring at runtime.
        Only ~1/n of keys will be reassigned to the new shard.
        """
        self.urls[shard_name] = shard_url
        self.ring.add_shard(shard_name)
        print(f"Added {shard_name} at {shard_url}")

    def remove_shard(self, shard_name: str) -> None:
        """
        Remove a shard from the ring.
        Its keys are reassigned to the next clockwise shard.
        """
        self.ring.remove_shard(shard_name)
        del self.urls[shard_name]
        print(f"Removed {shard_name}")

    def routing_table(self) -> dict:  ##Moved this function to consitent_hash.py
        """
        Show which shard handles which 2-char prefixes.
        Useful for debugging and monitoring.
        """
        import string
        chars   = string.ascii_lowercase
        table   = {}
        try:
            for c1 in chars:
                for c2 in chars:
                    prefix     = c1 + c2
                    shard_name = self.ring.get_shard_for_prefix(prefix)
                    if shard_name not in table:
                        table[shard_name] = []
                    table[shard_name].append(prefix)

            return table
        except Exception as e:
            print(e)


# ── Simulation (no real shard servers needed) ─────────────────
class SimulatedShardRouter:
    """
    Simulates the router + shards in a single process.

    Instead of HTTP calls to separate containers, each shard is
    a separate Trie instance in memory. The routing logic is
    identical — only the "forwarding" step is simulated.

    This lets you demo and test consistent hashing without needing
    3 separate running servers. The production version just swaps
    the simulated Trie lookup for a real HTTP call.
    """
    from src.trie import Trie

    def __init__(self, shard_names: list[str]):
        from src.trie import Trie
        self.ring   = ConsistentHashRing(shard_names, virtual_nodes=150)
        self.shards = {name: Trie() for name in shard_names}

    def insert(self, word: str, frequency: int = 1) -> str:
        """Insert a word into the correct shard's Trie."""
        shard_name = self.ring.get_shard_for_prefix(word)
        self.shards[shard_name].insert(word, frequency)
        return shard_name

    def search(self, prefix: str, limit: int = 10) -> dict:
        """Route search to the correct shard."""
        shard_name = self.ring.get_shard_for_prefix(prefix)
        trie       = self.shards[shard_name]
        results    = trie.autocomplete_with_scores(prefix, limit=limit)

        return {
            "query"  : prefix,
            "shard"  : shard_name,
            "results": [{"word": w, "score": round(s, 4)}
                        for w, s in results],
            "total"  : len(results),
        }

    def shard_sizes(self) -> dict:
        """Show how many words each shard holds."""
        return {name: trie.size()
                for name, trie in self.shards.items()}


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    from src.data_loader import SAMPLE_WORDS
    import random

    print("── Simulated ShardRouter ────────────────────────────")
    router = SimulatedShardRouter(["shard-1", "shard-2", "shard-3"])

    # Insert all sample words into their correct shards
    random.seed(42)
    for word in SAMPLE_WORDS:
        freq  = random.randint(1, 500)
        shard = router.insert(word, freq)

    print(f"\nShard sizes after inserting {len(SAMPLE_WORDS)} words:")
    for shard, size in router.shard_sizes().items():
        bar = "█" * size
        print(f"  {shard}: {size:>3} words  {bar}")

    print("\n── Routing queries to correct shards ────────────────")
    for prefix in ["py", "ja", "ca", "da", "re", "sp"]:
        result = router.search(prefix, limit=3)
        words  = [r["word"] for r in result["results"]]
        print(f"  '{prefix}' → {result['shard']:<10} results={words}")

    print("\n── Consistent hashing demo: adding shard-4 ──────────")
    print("Before:")
    before = {p: router.ring.get_shard_for_prefix(p)
              for p in ["py", "ja", "ca", "da", "re", "sp"]}
    for p, s in before.items():
        print(f"  '{p}' → {s}")

    router.ring.add_shard("shard-4")
    router.shards["shard-4"] = router.Trie()

    print("\nAfter adding shard-4:")
    moved = 0
    for prefix in ["py", "ja", "ca", "da", "re", "sp"]:
        after = router.ring.get_shard_for_prefix(prefix)
        tag   = " ← MOVED" if before[prefix] != after else ""
        if tag:
            moved += 1
        print(f"  '{prefix}' → {after}{tag}")

    print(f"\n  {moved}/6 prefixes moved to shard-4")