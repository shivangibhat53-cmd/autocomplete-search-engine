"""
Tests for the Trie data structure.
Covers insert, search, delete, autocomplete, scoring, and edge cases.
"""
import pytest
import time
from src.trie import Trie, TrieNode, compute_score


class TestTrieNode:

    def test_default_values(self):
        node = TrieNode()
        assert node.children   == {}
        assert node.is_end     == False
        assert node.word       is None
        assert node.frequency  == 0
        assert node.suggestions == []

    def test_repr(self):
        node      = TrieNode()
        node.word = "test"
        assert "test" in repr(node)


class TestTrieInsert:

    def setup_method(self):
        self.trie = Trie()

    def test_insert_single_word(self):
        self.trie.insert("python")
        assert self.trie.search("python") is True
        assert self.trie.size() == 1

    def test_insert_increments_size(self):
        self.trie.insert("python")
        self.trie.insert("java")
        self.trie.insert("react")
        assert self.trie.size() == 3

    def test_insert_duplicate_does_not_increment_size(self):
        self.trie.insert("python")
        self.trie.insert("python")
        assert self.trie.size() == 1

    def test_insert_duplicate_increments_frequency(self):
        self.trie.insert("python", 5)
        self.trie.insert("python", 3)
        assert self.trie.get_frequency("python") == 8

    def test_insert_lowercase_normalisation(self):
        self.trie.insert("Python")
        assert self.trie.search("python") is True
        assert self.trie.search("Python") is True

    def test_insert_strips_whitespace(self):
        self.trie.insert("  python  ")
        assert self.trie.search("python") is True

    def test_insert_empty_string_ignored(self):
        self.trie.insert("")
        assert self.trie.size() == 0

    def test_insert_with_frequency(self):
        self.trie.insert("python", 100)
        assert self.trie.get_frequency("python") == 100


class TestTrieSearch:

    def setup_method(self):
        self.trie = Trie()
        self.trie.insert("cat",  5)
        self.trie.insert("car",  3)
        self.trie.insert("card", 2)
        self.trie.insert("care", 4)
        self.trie.insert("dog",  1)

    def test_search_existing_word(self):
        assert self.trie.search("cat")  is True
        assert self.trie.search("car")  is True
        assert self.trie.search("card") is True

    def test_search_nonexistent_word(self):
        assert self.trie.search("xyz")  is False
        assert self.trie.search("cats") is False

    def test_search_prefix_only_returns_false(self):
        # "ca" is a prefix of "cat" and "car" but not a word itself
        assert self.trie.search("ca") is False

    def test_starts_with_existing_prefix(self):
        assert self.trie.starts_with("ca")  is True
        assert self.trie.starts_with("car") is True
        assert self.trie.starts_with("dog") is True

    def test_starts_with_nonexistent_prefix(self):
        assert self.trie.starts_with("xyz") is False
        assert self.trie.starts_with("cat1") is False


class TestTrieAutocomplete:

    def setup_method(self):
        self.trie = Trie()
        self.trie.insert("python",  100)
        self.trie.insert("pytorch", 50)
        self.trie.insert("pycharm", 30)
        self.trie.insert("pandas",  80)
        self.trie.insert("java",    90)

    def test_autocomplete_returns_matches(self):
        results = self.trie.autocomplete("py")
        assert "python"  in results
        assert "pytorch" in results
        assert "pycharm" in results

    def test_autocomplete_sorted_by_score(self):
        results = self.trie.autocomplete("py")
        # python (100) should rank above pytorch (50) above pycharm (30)
        assert results.index("python") < results.index("pytorch")
        assert results.index("pytorch") < results.index("pycharm")

    def test_autocomplete_respects_limit(self):
        results = self.trie.autocomplete("py", limit=2)
        assert len(results) == 2

    def test_autocomplete_empty_prefix_returns_empty(self):
        assert self.trie.autocomplete("") == []

    def test_autocomplete_unknown_prefix_returns_empty(self):
        assert self.trie.autocomplete("xyz") == []

    def test_autocomplete_with_scores_returns_tuples(self):
        results = self.trie.autocomplete_with_scores("py")
        assert all(isinstance(r, tuple) for r in results)
        assert all(len(r) == 2 for r in results)
        words, scores = zip(*results)
        assert "python" in words

    def test_cached_suggestions_populated_after_insert(self):
        """Suggestions cache should be built after insert."""
        node = self.trie._find_node("py")
        assert node is not None
        assert len(node.suggestions) > 0


class TestTrieDelete:

    def setup_method(self):
        self.trie = Trie()
        self.trie.insert("cat",  5)
        self.trie.insert("car",  3)
        self.trie.insert("card", 2)
        self.trie.insert("care", 4)

    def test_delete_existing_word(self):
        assert self.trie.delete("card") is True
        assert self.trie.search("card") is False

    def test_delete_reduces_size(self):
        self.trie.delete("card")
        assert self.trie.size() == 3

    def test_delete_keeps_sibling_words(self):
        self.trie.delete("card")
        assert self.trie.search("car")  is True
        assert self.trie.search("care") is True
        assert self.trie.search("cat")  is True

    def test_delete_nonexistent_word_returns_false(self):
        assert self.trie.delete("xyz") is False

    def test_delete_removes_from_suggestions(self):
        self.trie.delete("card")
        results = self.trie.autocomplete("car")
        assert "card" not in results

    def test_delete_prefix_word_keeps_longer_words(self):
        """Deleting 'car' should not affect 'card' or 'care'."""
        self.trie.delete("car")
        assert self.trie.search("car")  is False
        assert self.trie.search("card") is True
        assert self.trie.search("care") is True


class TestTrieScoring:

    def test_compute_score_higher_frequency_wins(self):
        score_high = compute_score(100, __import__("time").time())
        score_low  = compute_score(10,  __import__("time").time())
        assert score_high > score_low

    def test_compute_score_recent_beats_old(self):
        now     = __import__("time").time()
        old     = now - (60 * 60 * 24 * 60)  # 60 days ago
        recent  = compute_score(10, now)
        stale   = compute_score(10, old)
        assert recent > stale

    def test_increment_frequency_updates_score(self):
        trie = Trie()
        trie.insert("python", 10)
        score_before = trie.autocomplete_with_scores("py")[0][1]
        trie.increment_frequency("python")
        score_after  = trie.autocomplete_with_scores("py")[0][1]
        assert score_after > score_before


class TestTrieEdgeCases:

    def test_empty_trie(self):
        trie = Trie()
        assert trie.size()              == 0
        assert trie.autocomplete("a")  == []
        assert trie.search("a")        is False

    def test_single_character_word(self):
        trie = Trie()
        trie.insert("a", 1)
        assert trie.search("a")           is True
        assert trie.autocomplete("a")     == ["a"]

    def test_very_long_word(self):
        trie  = Trie()
        word  = "a" * 50
        trie.insert(word)
        assert trie.search(word)  is True

    def test_rebuild_all_suggestions(self):
        trie = Trie()
        for word in ["python", "pytorch", "pycharm"]:
            trie.insert(word, 10)
        trie.rebuild_all_suggestions()
        results = trie.autocomplete("py")
        assert len(results) == 3