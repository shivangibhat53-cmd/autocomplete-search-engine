"""
Consistent Hashing implementation for distributing Trie data
across multiple shard nodes.

Why consistent hashing over simple hash % num_shards:

  Simple modulo (hash("py") % 3 = shard 1):
    - Add a 4th shard → almost every key reassigns to a different shard
    - All cached data is now on the wrong shard — massive cache miss storm
    - In a distributed Trie this means rebuilding the wrong shard from scratch

  Consistent hashing:
    - Add a 4th shard → only ~25% of keys move (just the ones near it on the ring)
    - Everything else stays put — minimal disruption
    - This is why every major distributed system (DynamoDB, Cassandra,
      Redis Cluster) uses consistent hashing for data distribution

The ring concept:
  Imagine a circle (the "ring") with positions 0 to 2^128.
  Each shard gets multiple random positions on the ring (virtual nodes).
  To find which shard owns a key:
    1. Hash the key to a position on the ring
    2. Walk clockwise until you hit a shard's virtual node
    3. That shard owns the key

Virtual nodes:
  With only 3 physical shards, you'd get uneven distribution by chance.
  By giving each shard 150 virtual positions, the distribution evens out
  statistically — same reason a 6-sided die is fairer with more throws.
"""
import hashlib
import bisect


class ConsistentHashRing:

    def __init__(self, shards: list[str], virtual_nodes: int = 150):
        """
        shards        : list of shard identifiers e.g. ["shard-1", "shard-2", "shard-3"]
        virtual_nodes : how many positions each shard occupies on the ring
                        more = better distribution, slightly more memory
        """
        self.virtual_nodes = virtual_nodes
        self.ring          = {}    # position (int) → shard name
        self.sorted_keys   = []    # sorted list of positions for binary search

        for shard in shards:
            self.add_shard(shard)

    def _hash(self, key: str) -> int:
        """
        Hash a string to an integer using MD5.
        MD5 is fast and produces a uniform distribution —
        we don't need cryptographic security here, just good spread.
        Returns an integer in range [0, 2^128).
        """
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_shard(self, shard: str) -> None:
        """
        Add a shard to the ring by placing it at `virtual_nodes`
        different positions.

        Each virtual node is hashed as "{shard_name}#{index}" so
        the positions are spread across the ring rather than clustered.

        Example with virtual_nodes=3:
          "shard-1#0" → position 4829374...
          "shard-1#1" → position 9283746...
          "shard-1#2" → position 1827364...
        """
        for i in range(self.virtual_nodes):
            virtual_key = f"{shard}#{i}"
            position    = self._hash(virtual_key)
            # Skip if already in ring — prevents duplicates on re-add
            if position in self.ring:
                continue
            self.ring[position] = shard
            bisect.insort(self.sorted_keys, position)

    def remove_shard(self, shard: str) -> None:
        """
        Remove a shard from the ring.

        Only this shard's virtual nodes are removed.
        All other shards stay exactly where they were on the ring —
        this is the key property of consistent hashing.

        The keys that were on the removed shard get reassigned to
        the next clockwise shard — all other keys are unaffected.
        """
        for i in range(self.virtual_nodes):
            virtual_key = f"{shard}#{i}"
            position    = self._hash(virtual_key)

            if position not in self.ring:
                continue # already removed, skip

            del self.ring[position]

            idx = bisect.bisect_left(self.sorted_keys, position)
            if (idx < len(self.sorted_keys) and
                    self.sorted_keys[idx] == position):
                self.sorted_keys.pop(idx)

    def get_shard(self, key: str) -> str:
        """
        Find which shard owns this key.

        Algorithm:
          1. Hash the key to a ring position
          2. Binary search for the first virtual node position >= key's position
          3. If we're past the last virtual node, wrap around to position 0
             (the ring wraps — that's why it's called a ring)
          4. Return the shard that owns that virtual node

        Time complexity: O(log(n × v)) where n=shards, v=virtual_nodes
        Much faster than scanning all positions — binary search on sorted list.
        """
        if not self.ring:
            raise ValueError("No shards in ring — add shards before querying")

        position = self._hash(key)

        # Find the first ring position >= our key's position
        idx = bisect.bisect(self.sorted_keys, position)

        # Wrap around if we're past the last position
        if idx == len(self.sorted_keys):
            idx = 0

        return self.ring[self.sorted_keys[idx]]

    def get_shard_for_prefix(self, prefix: str) -> str:
        """
        Hash only the first 2 characters of the prefix.

        This preserves prefix locality — "py", "python", "pytorch"
        all hash as "py" and land on the same shard, so one shard
        holds the complete Trie subtree for "py..." words.

        Without this, "py" and "python" could land on different shards
        and a query for "py" would miss results stored under "python".
        """
        shard_key = prefix[:2].lower().strip()
        return self.get_shard(shard_key)

    def get_distribution(self) -> dict:
        """
        Show how many virtual nodes each shard owns.
        Useful for verifying even distribution.
        """
        distribution = {}
        for shard in self.ring.values():
            distribution[shard] = distribution.get(shard, 0) + 1
        return distribution

    def get_all_shards(self) -> list[str]:
        """Return list of unique shard names currently in the ring."""
        return list(set(self.ring.values()))
    
    def routing_table(self) -> dict:
        """
        Show which shard handles which 2-char prefixes.
        Useful for debugging and monitoring.
        """
        import string
        chars   = string.ascii_lowercase
        table   = {}
        
        for c1 in chars:
            for c2 in chars:
                prefix     = c1 + c2
                shard_name = self.get_shard_for_prefix(prefix)
                if shard_name not in table:
                    table[shard_name] = []
                table[shard_name].append(prefix)

        return table
        


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    shards = ["shard-1", "shard-2", "shard-3"]
    ring   = ConsistentHashRing(shards, virtual_nodes=150)

    print("── Distribution ─────────────────────────────────────")
    dist = ring.get_distribution()
    for shard, count in sorted(dist.items()):
        bar = "█" * (count // 10)
        print(f"  {shard}: {count:>4} virtual nodes  {bar}")

    print("\n── Prefix → Shard mapping ───────────────────────────")
    prefixes = ["py", "ja", "ca", "da", "re", "sp", "th", "wh",
                "python", "java", "react", "django"]
    for prefix in prefixes:
        shard = ring.get_shard_for_prefix(prefix)
        print(f"  '{prefix:<10}' → {shard}")

    print("\n── Adding a shard — minimal key movement ────────────")
    print("Before adding shard-4:")
    before = {p: ring.get_shard_for_prefix(p) for p in prefixes}
    for prefix, shard in before.items():
        print(f"  {repr(prefix):<14} → {shard}")

    ring.add_shard("shard-4")

    print("\nAfter adding shard-4:")
    moved = 0
    for prefix in prefixes:
        after_shard = ring.get_shard_for_prefix(prefix)
        changed     = before[prefix] != after_shard
        marker      = " ← MOVED" if changed else ""
        if changed:
            moved += 1
        print(f"  {repr(prefix):<14} → {after_shard}{marker}")

    print(f"\n  {moved}/{len(prefixes)} prefixes moved "
          f"(expected ~{len(prefixes) // (len(shards) + 1)}, "
          f"ideally 1/{len(shards)+1} of total)")

    print("\n── Removing shard-2 — only its keys reassign ────────")
    ring2   = ConsistentHashRing(shards, virtual_nodes=150)
    before2 = {p: ring2.get_shard_for_prefix(p) for p in prefixes}
    ring2.remove_shard("shard-2")

    moved2 = 0
    for prefix in prefixes:
        after = ring2.get_shard_for_prefix(prefix)
        if before2[prefix] != after:
            moved2 += 1
            print(f"  '{prefix}' moved: shard-2 → {after}")

    print(f"\n  {moved2}/{len(prefixes)} prefixes reassigned "
          f"(only the ones that were on shard-2)")