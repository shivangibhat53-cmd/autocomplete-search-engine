"""
Tests for the BK-Tree fuzzy search data structure.
"""
import pytest
from src.bk_tree import BKTree
from src.fuzzy import levenshtein_distance


class TestLevenshtein:

    def test_identical_strings(self):
        assert levenshtein_distance("cat", "cat") == 0

    def test_one_substitution(self):
        assert levenshtein_distance("cat", "car") == 1

    def test_one_insertion(self):
        assert levenshtein_distance("ca", "cat") == 1

    def test_one_deletion(self):
        assert levenshtein_distance("cats", "cat") == 1

    def test_completely_different(self):
        assert levenshtein_distance("abc", "xyz") == 3

    def test_empty_strings(self):
        assert levenshtein_distance("", "")    == 0
        assert levenshtein_distance("abc", "") == 3
        assert levenshtein_distance("", "abc") == 3

    def test_symmetric(self):
        assert (levenshtein_distance("python", "pythn") ==
                levenshtein_distance("pythn",  "python"))


class TestBKTreeInsert:

    def setup_method(self):
        self.bk = BKTree()

    def test_insert_single_word(self):
        self.bk.insert("python")
        assert self.bk.size() == 1

    def test_insert_multiple_words(self):
        for word in ["python", "java", "react"]:
            self.bk.insert(word)
        assert self.bk.size() == 3

    def test_insert_duplicate_updates_frequency(self):
        self.bk.insert("python", 5)
        self.bk.insert("python", 3)
        # Size stays 1 but frequency increases
        assert self.bk.size() == 1

    def test_insert_builds_root(self):
        self.bk.insert("python")
        assert self.bk.root is not None
        assert self.bk.root.word == "python"

    def test_empty_string_ignored(self):
        self.bk.insert("")
        assert self.bk.size() == 0


class TestBKTreeSearch:

    def setup_method(self):
        self.bk = BKTree()
        words   = [
            ("python", 100), ("pytorch", 50),
            ("java",   90),  ("javascript", 70),
            ("cat",    40),  ("car", 30),
            ("pandas", 80),
        ]
        for word, freq in words:
            self.bk.insert(word, freq)

    def test_exact_match_distance_zero(self):
        results = self.bk.search("python", max_distance=2)
        words   = [r[0] for r in results]
        dists   = [r[1] for r in results]
        assert "python" in words
        assert dists[words.index("python")] == 0

    def test_finds_one_edit_typo(self):
        results = self.bk.search("pythn", max_distance=2)
        words   = [r[0] for r in results]
        assert "python" in words

    def test_excludes_words_beyond_distance(self):
        results = self.bk.search("cat", max_distance=1)
        words   = [r[0] for r in results]
        # "pandas" is 5 edits away — must not appear
        assert "pandas" not in words

    def test_returns_sorted_by_distance(self):
        results = self.bk.search("pythn", max_distance=2)
        dists   = [r[1] for r in results]
        assert dists == sorted(dists)

    def test_empty_query_returns_empty(self):
        assert self.bk.search("") == []

    def test_no_matches_returns_empty(self):
        results = self.bk.search("zzzzz", max_distance=1)
        assert results == []

    def test_max_distance_zero_exact_only(self):
        results = self.bk.search("python", max_distance=0)
        words   = [r[0] for r in results]
        assert words == ["python"]

    def test_triangle_inequality_pruning(self):
        """BK-Tree must never miss a valid result."""
        import random
        random.seed(42)
        bk = BKTree()
        words = ["apple", "apply", "apt", "ape",
                 "app",   "appeal", "appear"]
        for w in words:
            bk.insert(w, 1)

        query    = "appl"
        bk_res   = {r[0] for r in bk.search(query, max_distance=2)}
        brute_res= {w for w in words
                    if levenshtein_distance(query, w) <= 2}
        # BK-Tree must find everything brute force finds
        assert bk_res == brute_res


class TestBKTreeStats:

    def test_size_and_depth(self):
        bk = BKTree()
        for word in ["python", "java", "react", "pandas"]:
            bk.insert(word)
        stats = bk.stats()
        assert stats["size"]  == 4
        assert stats["depth"] >= 1

    def test_empty_tree_stats(self):
        bk    = BKTree()
        stats = bk.stats()
        assert stats["size"]  == 0
        assert stats["depth"] == 0