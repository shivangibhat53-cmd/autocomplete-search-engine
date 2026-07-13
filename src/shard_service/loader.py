"""
Loads only this shard's words from PostgreSQL at startup.

Each shard container knows its own name (from SHARD_NAME env var).
It uses the consistent hash ring to determine which words belong
to it, then loads only those into its Trie.
"""
from src.sharding.consistent_hash import ConsistentHashRing
from src.db.models import get_all_words
from src.trie import Trie
import os


async def load_shard_words(trie: Trie,
                           shard_name: str,
                           all_shard_names: list[str]) -> int:
    """
    Load only the words that belong to this shard.

    Steps:
      1. Fetch all words from Postgres
      2. Build the same hash ring all shards use
      3. Keep only words where ring.get_shard_for_prefix(word) == my name
      4. Insert them into the local Trie
      5. Rebuild all suggestion caches

    Returns the number of words loaded.
    """
    ring      = ConsistentHashRing(all_shard_names, virtual_nodes=150)
    all_words = await get_all_words()

    my_words = [
        row for row in all_words
        if ring.get_shard_for_prefix(row["word"]) == shard_name
    ]

    for row in my_words:
        trie.insert(row["word"], row["frequency"])

    # Rebuild suggestion caches after bulk insert
    trie.rebuild_all_suggestions()

    print(f"  {shard_name}: loaded {len(my_words)}/{len(all_words)} "
          f"words from Postgres")
    return len(my_words)