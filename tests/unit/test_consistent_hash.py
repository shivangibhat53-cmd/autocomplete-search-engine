"""
Tests for consistent hashing ring.
Verifies even distribution, minimal key movement, and fault tolerance.
"""
import pytest
from src.sharding.consistent_hash import ConsistentHashRing


class TestConsistentHashRing:

    def setup_method(self):
        self.shards = ["shard-1", "shard-2", "shard-3"]
        self.ring   = ConsistentHashRing(
            self.shards, virtual_nodes=150
        )

    def test_ring_has_correct_virtual_nodes(self):
        expected = len(self.shards) * 150
        assert len(self.ring.ring) == expected

    def test_get_shard_returns_valid_shard(self):
        shard = self.ring.get_shard("python")
        assert shard in self.shards

    def test_same_key_always_same_shard(self):
        shard1 = self.ring.get_shard("python")
        shard2 = self.ring.get_shard("python")
        assert shard1 == shard2

    def test_prefix_locality(self):
        """
        Words with same 2-char prefix must route to same shard.
        This is critical for autocomplete correctness.
        """
        shard_py     = self.ring.get_shard_for_prefix("py")
        shard_python = self.ring.get_shard_for_prefix("python")
        shard_pytorch= self.ring.get_shard_for_prefix("pytorch")
        assert shard_py == shard_python == shard_pytorch

    def test_distribution_is_roughly_even(self):
        """Each shard should get roughly 1/n of keys."""
        import string
        counts = {s: 0 for s in self.shards}
        for c1 in string.ascii_lowercase:
            for c2 in string.ascii_lowercase:
                shard = self.ring.get_shard_for_prefix(c1 + c2)
                counts[shard] += 1

        total    = sum(counts.values())
        expected = total / len(self.shards)

        for shard, count in counts.items():
            # Allow 50% deviation from ideal
            assert abs(count - expected) < expected * 0.5, \
                f"{shard} has {count} keys, expected ~{expected:.0f}"

    def test_add_shard_minimal_movement(self):
        """Adding a shard should move ~1/n keys."""
        prefixes = [
            c1 + c2
            for c1 in "abcdefghij"
            for c2 in "abcdefghij"
        ]
        before = {p: self.ring.get_shard_for_prefix(p)
                  for p in prefixes}

        self.ring.add_shard("shard-4")

        moved = sum(
            1 for p in prefixes
            if self.ring.get_shard_for_prefix(p) != before[p]
        )
        # Should move roughly 1/4 of keys, allow generous range
        assert moved < len(prefixes) * 0.5

    def test_remove_shard_minimal_movement(self):
        """Removing a shard should only move its keys."""
        prefixes = [
            c1 + c2
            for c1 in "abcdefghij"
            for c2 in "abcdefghij"
        ]
        before = {p: self.ring.get_shard_for_prefix(p)
                  for p in prefixes}

        self.ring.remove_shard("shard-2")

        for prefix in prefixes:
            after = self.ring.get_shard_for_prefix(prefix)
            if before[prefix] != "shard-2":
                # Keys not on shard-2 must not move
                assert after == before[prefix], \
                    f"'{prefix}' moved from {before[prefix]} to {after}"

    def test_remove_shard_keys_go_to_valid_shard(self):
        """After removal, all keys must still route somewhere."""
        self.ring.remove_shard("shard-2")
        remaining = ["shard-1", "shard-3"]
        shard     = self.ring.get_shard("python")
        assert shard in remaining

    def test_get_all_shards(self):
        shards = self.ring.get_all_shards()
        assert set(shards) == set(self.shards)

    def test_routing_table_covers_all_prefixes(self):
        table = self.ring.routing_table()
        total = sum(len(v) for v in table.values())
        assert total == 26 * 26   # all aa-zz combinations

    def test_empty_ring_raises(self):
        ring = ConsistentHashRing([], virtual_nodes=10)
        with pytest.raises(ValueError):
            ring.get_shard("anything")