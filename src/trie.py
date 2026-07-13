import time
import math


class TrieNode:
    """
    One node in the Trie.

    NEW in this stage:
      last_updated : unix timestamp of the most recent search/insert
                      for the word at this node — used for recency scoring
      suggestions  : cached list of (word, score) tuples — the top-N
                      best completions reachable from this node.
                      Read by autocomplete() in O(1) instead of running
                      a fresh DFS every single request.
    """
    def __init__(self):
        self.children      : dict  = {}
        self.is_end        : bool  = False
        self.word          : str   = None
        self.frequency     : int   = 0
        self.last_updated  : float = time.time()
        self.suggestions   : list  = []   # [(word, score), ...] sorted desc

    def __repr__(self):
        return (f"TrieNode(children={list(self.children.keys())}, "
                f"is_end={self.is_end}, word={self.word!r}, "
                f"freq={self.frequency})")


# ── Scoring ──────────────────────────────────────────────────
ALPHA = 0.7   # weight for popularity (frequency)
BETA  = 0.3   # weight for recency

# Recency uses exponential decay — a word searched today scores
# close to 1.0, a word searched a year ago decays toward 0.
# HALF_LIFE_DAYS controls how fast that decay happens.
HALF_LIFE_DAYS = 30.0


def compute_score(frequency: int, last_updated: float) -> float:
    """
    Combine popularity and recency into a single ranking score.

    score = ALPHA * normalized_frequency + BETA * recency_score

    Frequency is log-scaled because raw frequency can vary wildly
    (1 vs 10,000) — log compresses that range so one viral word
    doesn't completely dominate every ranking forever.

    Recency uses exponential decay:
      recency_score = 0.5 ^ (days_since_update / HALF_LIFE_DAYS)
      - searched today        -> recency_score ≈ 1.0
      - searched 30 days ago  -> recency_score = 0.5  (one half-life)
      - searched 60 days ago  -> recency_score = 0.25 (two half-lives)
    """
    # Log-scaled frequency — log(1 + freq) avoids log(0) for freq=0
    popularity_score = math.log1p(frequency)

    # Exponential recency decay
    days_since_update = (time.time() - last_updated) / 86400  # seconds -> days
    recency_score      = 0.5 ** (days_since_update / HALF_LIFE_DAYS)

    return ALPHA * popularity_score + BETA * recency_score


class Trie:
    """
    Trie with cached suggestions and frequency+recency ranking.

    Key change from earlier stages: autocomplete() now reads from
    a pre-computed cache instead of running DFS on every call.
    The cache is kept fresh by propagating updates upward on
    every insert/delete.
    """

    SUGGESTION_CACHE_SIZE = 10   # how many results to cache per node

    def __init__(self):
        self.root  = TrieNode()
        self._size = 0

    # ── Core operations ───────────────────────────────────────

    def insert(self, word: str, frequency: int = 1) -> None:
        """
        Insert a word, then propagate cache updates upward.

        Two phases:
          1. Walk DOWN creating nodes as needed (same as before)
          2. Walk UP from the word's node to the root, refreshing
             the `suggestions` cache at every ancestor node along
             the way — so any prefix of this word can instantly
             return updated results.
        """
        if not word:
            return

        word    = word.lower().strip()
        current = self.root
        path    = [self.root]              # track the path for the upward pass

        for char in word:
            if char not in current.children:
                current.children[char] = TrieNode()
            current = current.children[char]
            path.append(current)

        if not current.is_end:
            self._size += 1
        current.is_end       = True
        current.word         = word
        current.frequency   += frequency
        current.last_updated = time.time()

        # Phase 2 — propagate the new/updated word's score up to every
        # ancestor node's suggestion cache, including the leaf itself.
        self._propagate_suggestions(path)

    def delete(self, word: str) -> bool:
        """Remove a word, then refresh suggestion caches along its path."""
        if not word:
            return False

        word  = word.lower().strip()
        found = [False]
        path  = []
        self._delete_helper(self.root, word, 0, found, path)

        if found[0]:
            self._size -= 1
            # Refresh caches for every node that was on the path
            # (the word might have been removed from their suggestions)
            self._propagate_suggestions(path)

        return found[0]

    def _delete_helper(self, node: TrieNode, word: str,
                       depth: int, found: list, path: list) -> bool:
        if node is None:
            return False

        path.append(node)   # record every node visited, for cache refresh

        if depth == len(word):
            if not node.is_end:
                return False
            node.is_end       = False
            node.word         = None
            node.frequency    = 0
            found[0]          = True
            return len(node.children) == 0

        char  = word[depth]
        child = node.children.get(char)
        if child is None:
            return False

        should_delete_child = self._delete_helper(child, word, depth + 1,
                                                   found, path)
        if should_delete_child:
            del node.children[char]
            return len(node.children) == 0 and not node.is_end

        return False

    def search(self, word: str) -> bool:
        node = self._find_node(word)
        return node is not None and node.is_end

    def starts_with(self, prefix: str) -> bool:
        return self._find_node(prefix) is not None

    def get_frequency(self, word: str) -> int:
        node = self._find_node(word)
        if node and node.is_end:
            return node.frequency
        return 0

    def increment_frequency(self, word: str) -> None:
        """
        Increment frequency AND refresh recency, then propagate
        the updated score up through every ancestor's cache.

        This is what gets called every time a user actually selects
        a suggestion — both the popularity and recency signals update.
        """
        word = word.lower().strip()
        node = self.root
        path = [node]

        for char in word:
            if char not in node.children:
                return   # word doesn't exist
            node = node.children[char]
            path.append(node)

        if node.is_end:
            node.frequency    += 1
            node.last_updated  = time.time()
            self._propagate_suggestions(path)

    # ── Autocomplete (now reads from cache) ───────────────────

    def autocomplete(self, prefix: str, limit: int = 10) -> list:
        """
        Return up to `limit` ranked suggestions for this prefix.

        This now reads directly from the prefix node's cached
        `suggestions` list — O(1) lookup instead of O(k) DFS.
        The cache is kept fresh by insert/delete/increment_frequency.
        """
        if not prefix:
            return []

        node = self._find_node(prefix.lower().strip())
        if node is None:
            return []

        return [word for word, score in node.suggestions[:limit]]

    def autocomplete_with_scores(self, prefix: str, limit: int = 10) -> list:
        """Same as autocomplete but returns (word, score) tuples."""
        if not prefix:
            return []

        node = self._find_node(prefix.lower().strip())
        if node is None:
            return []

        return node.suggestions[:limit]

    # ── Cache propagation (the new core logic) ────────────────

    def _propagate_suggestions(self, path: list) -> None:
        """
        Walk the path from leaf back to root, recomputing each
        node's `suggestions` cache.

        For each node on the path, we need "what are the top-N
        scored words reachable below this node?" We compute this
        bottom-up: a node's candidate suggestions are the union of
        its own word (if it's a word-end) plus all its direct
        children's cached suggestions — NOT a full DFS, since
        children already have their own cache computed.

        This is the key efficiency trick: each node only looks at
        its immediate children's cache, not the whole subtree.
        Time complexity: O(m * b * log(SUGGESTION_CACHE_SIZE))
        where m = path length, b = branching factor at each node.
        """
        # Walk from the leaf (end of path) back to the root
        for node in reversed(path):
            candidates = []

            # Include this node's own word if it's a complete word
            if node.is_end:
                score = compute_score(node.frequency, node.last_updated)
                candidates.append((node.word, score))

            # Include every child's already-updated suggestions
            # (children were processed first since we're going leaf->root)
            for child in node.children.values():
                candidates.extend(child.suggestions)

            # Sort by score descending, keep only top N
            candidates.sort(key=lambda x: x[1], reverse=True)
            node.suggestions = candidates[:self.SUGGESTION_CACHE_SIZE]

    def rebuild_all_suggestions(self) -> None:
        """
        Full rebuild of every node's suggestion cache from scratch.
        Used after bulk loading data (e.g. from a CSV) where calling
        insert() one word at a time would be wasteful — instead we
        insert all words first (skipping propagation), then call
        this once at the end to compute every cache in one pass.
        """
        self._rebuild_recursive(self.root)

    def _rebuild_recursive(self, node: TrieNode) -> list:
        """
        Post-order traversal: process all children first, then
        compute this node's cache from the now-fresh children.
        Returns this node's suggestions list (used by the parent).
        """
        candidates = []

        if node.is_end:
            score = compute_score(node.frequency, node.last_updated)
            candidates.append((node.word, score))

        for child in node.children.values():
            child_suggestions = self._rebuild_recursive(child)
            candidates.extend(child_suggestions)

        candidates.sort(key=lambda x: x[1], reverse=True)
        node.suggestions = candidates[:self.SUGGESTION_CACHE_SIZE]

        return node.suggestions

    # ── Size and stats ────────────────────────────────────────

    def size(self) -> int:
        return self._size

    def all_words(self) -> list:
        """Return all words via full DFS — used for fuzzy search,
        not for normal autocomplete (which uses the cache)."""
        results = []
        self._dfs_collect(self.root, results)
        results.sort(key=lambda x: x[1], reverse=True)
        return [word for word, freq in results]

    # ── Private helpers ───────────────────────────────────────

    def _find_node(self, prefix: str):
        if not prefix:
            return None
        current = self.root
        for char in prefix.lower().strip():
            if char not in current.children:
                return None
            current = current.children[char]
        return current

    def _dfs_collect(self, node: TrieNode, results: list) -> None:
        if node is None:
            return
        if node.is_end:
            results.append((node.word, node.frequency))
        for child in node.children.values():
            self._dfs_collect(child, results)


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    trie = Trie()

    words = [
        ("python", 300), ("python3", 20), ("pytorch", 150),
        ("pandas", 200), ("panda", 10),
        ("javascript", 180), ("java", 250),
        ("cat", 40), ("car", 60), ("card", 20), ("care", 30),
    ]

    for word, freq in words:
        trie.insert(word, freq)

    print(f"Trie size: {trie.size()} words\n")

    print("── Cached suggestions (O(1) read) ───────────────────")
    for prefix in ["py", "ja", "ca"]:
        results = trie.autocomplete(prefix, limit=5)
        print(f"  '{prefix}' -> {results}")

    print("\n── Scores with breakdown ─────────────────────────────")
    for prefix in ["py"]:
        results = trie.autocomplete_with_scores(prefix, limit=5)
        for word, score in results:
            print(f"  {word:<15} score={score:.4f}")

    # Simulate a word being searched again — recency refreshes
    print("\n── After incrementing 'python3' frequency ───────────")
    trie.increment_frequency("python3")
    trie.increment_frequency("python3")
    trie.increment_frequency("python3")
    results = trie.autocomplete_with_scores("py", limit=5)
    for word, score in results:
        print(f"  {word:<15} score={score:.4f}")