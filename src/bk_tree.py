"""
BK-Tree (Burkhard-Keller Tree) for efficient fuzzy string search.

Replaces the O(n) brute-force fuzzy search with O(log n) average
case by exploiting the triangle inequality of edit distance.

Structure:
  - Root node holds one word
  - Each node's children are indexed by edit distance from the parent
  - To search: compute dist(query, node), then only recurse into
    children with edge weight in [dist-k, dist+k] where k=max_distance

Example tree after inserting: "book", "books", "cook", "look", "took"

         "book" (root)
        /      \
    d=1          d=2
   "books"      "cook"
               /      \
           d=1          d=1
          "look"       "took"
"""
from src.fuzzy import levenshtein_distance


class BKNode:
    """One node in the BK-Tree."""

    def __init__(self, word: str, frequency: int = 1):
        self.word      = word
        self.frequency = frequency
        self.children  : dict[int, "BKNode"] = {}
        # key   = edit distance from this node to the child
        # value = child BKNode

    def __repr__(self):
        return (f"BKNode(word={self.word!r}, "
                f"freq={self.frequency}, "
                f"children={list(self.children.keys())})")


class BKTree:
    """
    BK-Tree for O(log n) fuzzy string search.

    Insert: O(depth) — typically O(log n)
    Search: O(n^(k/d)) where k=tolerance, d=avg distance between words
            Much faster than O(n) brute force for small k
    """

    def __init__(self):
        self.root  : BKNode | None = None
        self._size : int           = 0

    def insert(self, word: str, frequency: int = 1) -> None:
        """
        Insert a word into the BK-Tree.

        Algorithm:
          1. If tree is empty, word becomes the root
          2. Start at root, compute dist(word, current_node)
          3. If a child exists at that distance, recurse into it
          4. If no child at that distance, attach word as new child

        The distance to the parent IS the edge weight — this is what
        allows the triangle inequality pruning during search.
        """
        word = word.lower().strip()
        if not word:
            return

        if self.root is None:
            self.root  = BKNode(word, frequency)
            self._size = 1
            return

        current = self.root
        while True:
            dist = levenshtein_distance(word, current.word)

            if dist == 0:
                # Word already exists — update frequency
                current.frequency += frequency
                return

            if dist not in current.children:
                # No child at this distance — insert here
                current.children[dist] = BKNode(word, frequency)
                self._size += 1
                return

            # Child exists at this distance — go deeper
            current = current.children[dist]

    def search(self, query: str,
               max_distance: int = 2) -> list[tuple[str, int, int]]:
        """
        Find all words within max_distance edits of query.

        Returns list of (word, distance, frequency) tuples,
        sorted by distance ascending then frequency descending.

        Algorithm:
          1. Compute dist(query, current_node)
          2. If dist ≤ max_distance → include this node in results
          3. Recurse into children with edge weight in
             [dist - max_distance, dist + max_distance]
          4. Skip (prune) all other children — triangle inequality
             guarantees they can't be within max_distance of query

        This pruning is what makes BK-Tree fast — most branches
        are skipped without computing edit distance.
        """
        if self.root is None or not query:
            return []

        query   = query.lower().strip()
        results = []

        # Use an explicit stack instead of recursion to avoid
        # Python's recursion limit for very large trees
        stack   = [self.root]

        while stack:
            node = stack.pop()
            dist = levenshtein_distance(query, node.word)

            if dist <= max_distance:
                results.append((node.word, dist, node.frequency))

            # Triangle inequality pruning:
            # Only recurse into children with edge weight in
            # [dist - max_distance, dist + max_distance]
            low  = dist - max_distance
            high = dist + max_distance

            for edge_weight, child in node.children.items():
                if low <= edge_weight <= high:
                    stack.append(child)
                # else: PRUNE — skip this entire subtree

        results.sort(key=lambda x: (x[1], -x[2]))
        return results

    def search_with_prefix(self, query: str,
                           max_distance: int = 2,
                           limit: int = 10) -> list[dict]:
        """
        Combined prefix + fuzzy search.

        First checks if query is an exact prefix match (O(1) from Trie).
        Then supplements with BK-Tree fuzzy matches.

        This is what gets called from the API routes.
        Returns list of dicts with word, source, score fields.
        """
        results  = []
        seen     = set()
        raw      = self.search(query, max_distance=max_distance)

        for word, dist, freq in raw[:limit]:
            if word not in seen:
                results.append({
                    "word"    : word,
                    "distance": dist,
                    "frequency": freq,
                    "source"  : "exact" if dist == 0 else "fuzzy",
                })
                seen.add(word)

        return results

    def size(self) -> int:
        return self._size

    def depth(self) -> int:
        """Calculate tree depth — useful for understanding balance."""
        if self.root is None:
            return 0
        return self._depth_recursive(self.root)

    def _depth_recursive(self, node: BKNode) -> int:
        if not node.children:
            return 1
        return 1 + max(
            self._depth_recursive(child)
            for child in node.children.values()
        )

    def stats(self) -> dict:
        """Return tree statistics."""
        if self.root is None:
            return {"size": 0, "depth": 0}
        return {
            "size" : self._size,
            "depth": self.depth(),
        }


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    from src.data_loader import SAMPLE_WORDS, load_sample_data
    from src.trie import Trie
    import time
    import random

    # Build BK-Tree from sample words
    bk = BKTree()
    random.seed(42)
    for word in SAMPLE_WORDS:
        freq = random.randint(1, 500)
        bk.insert(word, freq)

    print(f"BK-Tree stats: {bk.stats()}\n")

    # ── Test fuzzy search ──────────────────────────────────
    print("── Fuzzy search (max_distance=2) ────────────────────")
    queries = [
        ("pythn",    "python"),
        ("jva",      "java"),
        ("panads",   "pandas"),
        ("reactt",   "react"),
        ("javascrpt","javascript"),
        ("crd",      "card/car/care"),
    ]

    for query, expected in queries:
        results = bk.search(query, max_distance=2)
        words   = [(w, d) for w, d, f in results]
        print(f"  '{query}' (expect ~{expected})")
        for word, dist in words:
            print(f"    dist={dist}  {word}")
        print()

    # ── Compare performance: BK-Tree vs brute force ────────
    print("── Performance comparison ───────────────────────────")

    # Build a larger dataset for meaningful comparison
    import string
    large_words = SAMPLE_WORDS * 10   # 990 words
    bk_large    = BKTree()
    for w in large_words:
        bk_large.insert(w, 1)

    query       = "pythn"
    iterations  = 100

    # BK-Tree timing
    start = time.perf_counter()
    for _ in range(iterations):
        bk_large.search(query, max_distance=2)
    bk_time = (time.perf_counter() - start) / iterations * 1000

    # Brute force timing
    from src.fuzzy import levenshtein_distance as lev
    all_w = large_words
    def brute_force(q, words, k):
        return [(w, lev(q, w)) for w in words if lev(q, w) <= k]

    start = time.perf_counter()
    for _ in range(iterations):
        brute_force(query, all_w, 2)
    bf_time = (time.perf_counter() - start) / iterations * 1000

    print(f"  Words in dataset : {bk_large.size()}")
    print(f"  BK-Tree search   : {bk_time:.3f}ms per query")
    print(f"  Brute force      : {bf_time:.3f}ms per query")
    print(f"  Speedup          : {bf_time/bk_time:.1f}x faster")

    # ── Show pruning effectiveness ─────────────────────────
    print(f"\n── Tree structure ───────────────────────────────────")
    print(f"  Size  : {bk_large.size()} nodes")
    print(f"  Depth : {bk_large.depth()} levels")
    print(f"  (deeper = more pruning opportunities)")