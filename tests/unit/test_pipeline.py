"""
Tests for the ingestion pipeline.
"""
import pytest
import os
import tempfile
from src.pipeline.ingestion import (
    read_logs,
    clean_query,
    clean_logs,
    compute_term_scores,
)


class TestCleanQuery:

    def test_lowercases_input(self):
        assert clean_query("Python") == "python"

    def test_strips_whitespace(self):
        assert clean_query("  python  ") == "python"

    def test_removes_special_characters(self):
        result = clean_query("python!")
        assert "!" not in result

    def test_rejects_empty_string(self):
        assert clean_query("") is None

    def test_rejects_single_character(self):
        assert clean_query("a") is None

    def test_rejects_very_long_query(self):
        assert clean_query("a" * 51) is None

    def test_rejects_url(self):
        assert clean_query("http://example.com") is None

    def test_accepts_normal_query(self):
        assert clean_query("python") == "python"

    def test_accepts_multi_word(self):
        assert clean_query("machine learning") == "machine learning"

    def test_accepts_hyphenated(self):
        result = clean_query("machine-learning")
        assert result is not None


class TestReadLogs:

    def test_reads_valid_csv(self):
        content = (
            "timestamp,query,user_session,clicked_result,"
            "time_spent_ms\n"
            "2024-01-01 09:00:00,python,sess_001,python,1000\n"
            "2024-01-01 09:00:01,java,sess_002,java,900\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv",
            delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            path = f.name

        try:
            logs = read_logs(path)
            assert len(logs) == 2
            assert logs[0]["query"]   == "python"
            assert logs[1]["query"]   == "java"
        finally:
            os.unlink(path)

    def test_returns_empty_for_missing_file(self):
        logs = read_logs("nonexistent_file.csv")
        assert logs == []


class TestCleanLogs:

    def test_filters_invalid_queries(self):
        logs = [
            {"query": "python",    "clicked_result": "python",
             "timestamp": "", "time_spent_ms": "1000"},
            {"query": "a",         "clicked_result": "",
             "timestamp": "", "time_spent_ms": "100"},
            {"query": "http://x",  "clicked_result": "",
             "timestamp": "", "time_spent_ms": "100"},
        ]
        cleaned = clean_logs(logs)
        assert len(cleaned) == 1
        assert cleaned[0]["query"] == "python"

    def test_normalises_queries(self):
        logs = [
            {"query": "  Python  ", "clicked_result": "python",
             "timestamp": "", "time_spent_ms": "1000"},
        ]
        cleaned = clean_logs(logs)
        assert cleaned[0]["query"] == "python"


class TestComputeTermScores:

    def setup_method(self):
        self.logs = [
            {"query": "python", "clicked_result": "python",
             "timestamp": "2024-01-15 09:00:00",
             "time_spent_ms": 1000},
            {"query": "python", "clicked_result": "python",
             "timestamp": "2024-01-15 09:00:01",
             "time_spent_ms": 900},
            {"query": "java",   "clicked_result": "java",
             "timestamp": "2024-01-15 09:00:02",
             "time_spent_ms": 800},
        ]

    def test_returns_scores_for_clicked_terms(self):
        scores = compute_term_scores(self.logs)
        assert "python" in scores
        assert "java"   in scores

    def test_more_clicks_higher_score(self):
        scores = compute_term_scores(self.logs)
        # python clicked twice, java once
        assert scores["python"]["score"] > scores["java"]["score"]

    def test_score_has_required_fields(self):
        scores = compute_term_scores(self.logs)
        for term, stats in scores.items():
            assert "score"      in stats
            assert "clicks"     in stats
            assert "ctr"        in stats
            assert "frequency"  in stats

    def test_ctr_between_zero_and_one(self):
        scores = compute_term_scores(self.logs)
        for term, stats in scores.items():
            assert 0.0 <= stats["ctr"] <= 1.0

    def test_empty_logs_returns_empty(self):
        scores = compute_term_scores([])
        assert scores == {}

    def test_no_clicks_not_scored(self):
        logs = [
            {"query": "python", "clicked_result": None,
             "timestamp": "", "time_spent_ms": 0},
        ]
        scores = compute_term_scores(logs)
        assert "python" not in scores