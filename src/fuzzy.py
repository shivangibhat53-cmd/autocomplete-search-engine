from src.trie import Trie

# ── Levenshtein Distance ──────────────────────────────────────
def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the minimum number of single-character edits
    (insertions, deletions, substitutions) needed to change s1 into s2.

    Uses dynamic programming — builds a 2D table where
    dp[i][j] = edit distance between s1[:i] and s2[:j]

    Example:
      s1 = "pythn"
      s2 = "python"
      distance = 1  (insert 'o' between h and n)

      s1 = "jvascript"
      s2 = "javascript"
      distance = 1  (insert 'a' after j)

    Time complexity : O(m * n) where m=len(s1), n=len(s2)
    Space complexity: O(m * n)
    """
    m, n = len(s1), len(s2)

    # dp table — (m+1) x (n+1)
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # Base cases:
    # Turning s1[:i] into "" costs i deletions
    for i in range(m + 1):
        dp[i][0] = i

    # Turning "" into s2[:j] costs j insertions
    for j in range(n + 1):
        dp[0][j] = j

    # Fill the table
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                # Characters match — no edit needed
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # deletion  from s1
                    dp[i][j - 1],      # insertion into s1
                    dp[i - 1][j - 1]   # substitution
                )

    return dp[m][n]


# ── Fuzzy Search ──────────────────────────────────────────────
def fuzzy_search(trie: Trie,
                 query: str,
                 max_distance: int = 2,
                 limit: int = 10) -> list:
    """
    Find words in the Trie that are within `max_distance` edits of query.
    Returns a list of (word, distance, frequency) tuples,
    sorted by distance first, then frequency descending.

    Strategy:
      1. Get all words from the Trie
      2. Compute Levenshtein distance between query and each word
      3. Keep only words within max_distance
      4. Sort by distance (closest first), then frequency (highest first)

    This is a brute-force approach — O(n * m * k) where n=words, m=query
    length, k=word length. Good enough for < 100k words.
    For production at scale, use BK-trees or SymSpell instead.

    Example:
      query="pythn", max_distance=2
      "python"  distance=1  ← included
      "pytorch" distance=3  ← excluded
      "pandas"  distance=5  ← excluded
    """
    query   = query.lower().strip()
    results = []

    for word in trie.all_words():
        dist = levenshtein_distance(query, word)
        if dist <= max_distance:
            freq = trie.get_frequency(word)
            results.append((word, dist, freq))

    # Sort: distance ascending, then frequency descending
    results.sort(key=lambda x: (x[0], -x[2]))
    return results[:limit]


def fuzzy_autocomplete(trie: Trie,
                       query: str,
                       max_distance: int = 1,
                       limit: int = 10) -> list:
    """
    Combined autocomplete + fuzzy search.

    First tries exact prefix match (fast, O(m+k)).
    If fewer than `limit` results found, supplements with
    fuzzy matches for the query.

    This mirrors how real search engines work:
      - Exact prefix matches shown first
      - Fuzzy matches shown as "Did you mean...?" suggestions

    Returns list of (word, match_type, frequency) where
    match_type is 'exact' or 'fuzzy'.
    """
    query   = query.lower().strip()
    results = []
    seen    = set()

    # Step 1: exact prefix matches
    exact = trie.autocomplete_with_scores(query, limit=limit)
    for word, freq in exact:
        results.append((word, 'exact', freq))
        seen.add(word)

    # Step 2: supplement with fuzzy if needed
    if len(results) < limit:
        fuzzy = fuzzy_search(trie, query,
                             max_distance=max_distance,
                             limit=limit)
        for word, dist, freq in fuzzy:
            if word not in seen:
                results.append((word, 'fuzzy', freq))
                seen.add(word)
                if len(results) >= limit:
                    break

    return results


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    trie = Trie()

    words = [
        ("python", 10), ("python3", 5), ("pytorch", 8),
        ("pandas", 12), ("panda", 3),
        ("javascript", 7), ("java", 15),
        ("cat", 4), ("car", 6), ("card", 2),
        ("care", 3), ("cart", 1), ("carbon", 5),
    ]

    for word, freq in words:
        trie.insert(word, freq)

    print(f"Trie size: {trie.size()} words")

    # ── Test delete ───────────────────────────────────────────
    print("\n── Delete ───────────────────────────────────────────")
    print(f"  Before: autocomplete('car') = {trie.autocomplete('car')}")
    print(f"  delete('card') = {trie.delete('card')}")
    print(f"  After : autocomplete('car') = {trie.autocomplete('car')}")
    print(f"  delete('xyz')  = {trie.delete('xyz')}")   # word not in trie
    print(f"  Trie size after deletes: {trie.size()}")

    # ── Test Levenshtein distance ─────────────────────────────
    print("\n── Levenshtein Distance ─────────────────────────────")
    pairs = [
        ("pythn",  "python"),
        ("jva",    "java"),
        ("cat",    "cat"),
        ("cat",    "car"),
        ("pandas", "panda"),
    ]
    for s1, s2 in pairs:
        print(f"  '{s1}' -> '{s2}' : {levenshtein_distance(s1, s2)}")

    # ── Test fuzzy search ─────────────────────────────────────
    print("\n── Fuzzy Search (max_distance=2) ────────────────────")
    for query in ["pythn", "jva", "crd", "panads"]:
        results = fuzzy_search(trie, query, max_distance=2, limit=5)
        print(f"  '{query}' ->")
        for word, dist, freq in results:
            print(f"    {word:<15} dist={dist}  freq={freq}")

    # ── Test combined autocomplete ────────────────────────────
    print("\n── Fuzzy Autocomplete ───────────────────────────────")
    for query in ["py", "pythn", "jva", "crd"]:
        results = fuzzy_autocomplete(trie, query, max_distance=2, limit=5)
        print(f"  '{query}' ->")
        for word, match_type, freq in results:
            tag = "[exact]" if match_type == "exact" else "[fuzzy]"
            print(f"    {tag:<8} {word:<15} freq={freq}")