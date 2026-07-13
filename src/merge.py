"""
Merges personal search history with global Trie suggestions.

Personal matches are prioritized — they appear first, since they
represent what THIS user has actually searched for before.
Global suggestions fill any remaining slots.
"""


def merge_personal_and_global(personal: list,
                              global_results: list,
                              limit: int = 10) -> list:
    """
    personal       : list of words (strings) from this user's history
    global_results : list of (word, score) tuples from the Trie cache
    limit          : max total results to return

    Returns a list of dicts:
      [{"word": "python", "source": "personal"},
       {"word": "pytorch", "source": "global", "score": 3.91}, ...]
    """
    seen   = set()
    merged = []
    # Personal history — ranked by recency (Redis LIST order)
    # No score needed — position IS the ranking

    # Personal history first — already filtered to match the prefix
    for word in personal:
        if word not in seen and len(merged) < limit:
            merged.append({"word": word, "source": "personal","score" : None }) 
            seen.add(word)

    # Fill remaining slots with global suggestions
    for word, score in global_results:
        if word not in seen and len(merged) < limit:
            merged.append({"word": word, "source": "global", "score": round(score, 4)})
            seen.add(word)

    return merged