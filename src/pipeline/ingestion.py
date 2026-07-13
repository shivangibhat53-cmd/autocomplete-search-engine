"""
Ingestion Pipeline — right-sized for portfolio scale.

What this simulates:
  Real system   → Kafka streams + Spark batch jobs
  This system   → CSV log file + scheduled Python job

The algorithm is identical — only the infrastructure differs.
For 100k+ queries/day you'd swap CSV → Kafka topic and
pandas → Spark DataFrame. The scoring formula stays the same.

Pipeline stages:
  1. Ingest    — read raw search logs from CSV
  2. Clean     — normalise text, remove noise
  3. Score     — compute popularity + recency + CTR
  4. Index     — update Postgres + notify shards + BK-Tree
  5. Report    — log what changed
"""
import os
import csv
import math
import time
import asyncio
import aiohttp
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ── Scoring weights ───────────────────────────────────────────
# From the article's formula:
# score = α·popularity + β·recency + γ·CTR
ALPHA = 0.5   # popularity weight
BETA  = 0.3   # recency weight
GAMMA = 0.2   # click-through rate weight

# Recency half-life — score halves every 7 days
HALF_LIFE_DAYS = 7.0


# ── Stage 1: Ingest ───────────────────────────────────────────
def read_logs(filepath: str) -> list[dict]:
    """
    Read raw search logs from CSV.

    In production this would be:
      Kafka consumer reading from search_events topic
      or Spark job reading from S3/HDFS log files

    CSV format:
      timestamp, query, user_session, clicked_result, time_spent_ms
    """
    if not os.path.exists(filepath):
        print(f"  Log file not found: {filepath}")
        return []

    logs = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            logs.append(row)

    print(f"  Ingested {len(logs)} log entries from {filepath}")
    return logs


# ── Stage 2: Clean ────────────────────────────────────────────
def clean_query(query: str) -> str | None:
    """
    Normalise a raw search query.

    Steps:
      - Lowercase
      - Strip whitespace
      - Remove special characters
      - Skip empty, too short, or too long queries
      - Skip queries that look like URLs or code

    Returns None if the query should be discarded.
    """
    if not query:
        return None

    # Lowercase and strip
    cleaned = query.lower().strip()

    # Remove special characters except spaces and hyphens
    cleaned = "".join(
        c for c in cleaned
        if c.isalnum() or c in " -"
    )
    cleaned = cleaned.strip()

    # Skip if too short or too long
    if len(cleaned) < 2 or len(cleaned) > 50:
        return None

    # Skip if looks like a URL or code
    if any(c in cleaned for c in ["http", "www", "//", ".py"]):
        return None

    return cleaned


def clean_logs(logs: list[dict]) -> list[dict]:
    """
    Clean all log entries and filter out noise.
    Returns only valid, normalised log entries.
    """
    cleaned = []
    skipped = 0

    for log in logs:
        query         = clean_query(log.get("query", ""))
        clicked_result= clean_query(log.get("clicked_result", ""))

        if query is None:
            skipped += 1
            continue

        cleaned.append({
            "query"        : query,
            "clicked_result": clicked_result,
            "timestamp"    : log.get("timestamp", ""),
            "time_spent_ms": int(log.get("time_spent_ms", 0) or 0),
        })

    print(f"  Cleaned: {len(cleaned)} valid, {skipped} skipped")
    return cleaned


# ── Stage 3: Score ────────────────────────────────────────────
def compute_term_scores(logs: list[dict]) -> dict[str, dict]:
    """
    Compute a ranking score for each unique term.

    For each clicked result we compute:
      popularity = log(1 + click_count)
      recency    = exponential decay based on most recent click
      ctr        = clicks / total_searches for this term

    Final score = α·popularity + β·recency + γ·ctr

    This mirrors the article's formula:
      score = α·popularity + β·recency + γ·CTR
    """
    # Aggregate stats per clicked term
    term_stats = defaultdict(lambda: {
        "click_count"   : 0,
        "search_count"  : 0,
        "last_seen"     : None,
        "total_time_ms" : 0,
    })

    now = datetime.now(timezone.utc)

    for log in logs:
        query   = log["query"]
        clicked = log["clicked_result"]

        # Count searches for this query
        term_stats[query]["search_count"] += 1

        # Count clicks on the result
        if clicked:
            stats = term_stats[clicked]
            stats["click_count"]    += 1
            stats["total_time_ms"]  += log["time_spent_ms"]

            # Track most recent click for recency
            try:
                ts = datetime.fromisoformat(log["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if (stats["last_seen"] is None
                        or ts > stats["last_seen"]):
                    stats["last_seen"] = ts
            except (ValueError, TypeError):
                pass

    # Compute scores
    scored_terms = {}
    for term, stats in term_stats.items():
        clicks  = stats["click_count"]
        if clicks == 0:
            continue   # only score terms that were actually clicked

        # Popularity — log-scaled click count
        popularity = math.log1p(clicks)

        # Recency — exponential decay from last click
        if stats["last_seen"]:
            days_ago = (now - stats["last_seen"]).total_seconds() / 86400
            recency  = 0.5 ** (days_ago / HALF_LIFE_DAYS)
        else:
            recency  = 0.0

        # CTR — what fraction of searches led to a click
        searches = term_stats[term]["search_count"] or clicks
        ctr      = min(clicks / searches, 1.0)

        # Final weighted score
        score = (ALPHA * popularity +
                 BETA  * recency    +
                 GAMMA * ctr)

        scored_terms[term] = {
            "score"      : round(score, 4),
            "clicks"     : clicks,
            "searches"   : searches,
            "ctr"        : round(ctr, 4),
            "recency"    : round(recency, 4),
            "popularity" : round(popularity, 4),
            "frequency"  : clicks,   # use clicks as frequency signal
        }

    # Sort by score descending
    scored_terms = dict(
        sorted(scored_terms.items(),
               key=lambda x: x[1]["score"],
               reverse=True)
    )

    print(f"  Scored {len(scored_terms)} terms")
    return scored_terms


# ── Stage 4: Index ────────────────────────────────────────────
async def index_terms(scored_terms: dict,
                      api_base_url : str = "http://localhost:8000") -> dict:
    """
    Push scored terms to the API which handles:
      - Updating Postgres (durable storage)
      - Updating the correct shard's Trie (in-memory search)
      - Updating BK-Tree service (fuzzy search)
      - Invalidating Redis cache (so stale results are refreshed)

    In production with Kafka:
      Produce scored terms to an "indexed_terms" topic
      Each service consumes and updates itself

    Here we call the REST API directly — same effect,
    simpler infrastructure.
    """
    results = {
        "indexed"  : 0,
        "failed"   : 0,
        "top_terms": [],
    }

    async with aiohttp.ClientSession() as session:
        for term, stats in scored_terms.items():
            try:
                async with session.post(
                    f"{api_base_url}/words",
                    json={
                        "word"     : term,
                        "frequency": stats["frequency"],
                    },
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        results["indexed"] += 1
                        if len(results["top_terms"]) < 10:
                            results["top_terms"].append({
                                "word" : term,
                                "score": stats["score"],
                                "ctr"  : stats["ctr"],
                            })
                    else:
                        results["failed"] += 1

            except Exception as e:
                print(f"  Failed to index '{term}': {e}")
                results["failed"] += 1

    return results


# ── Stage 5: Report ───────────────────────────────────────────
def print_report(scored_terms: dict, index_results: dict,
                 elapsed: float) -> None:
    """Print a summary of the pipeline run."""
    print(f"\n{'='*55}")
    print(f"  INGESTION PIPELINE REPORT")
    print(f"{'='*55}")
    print(f"  Terms scored    : {len(scored_terms)}")
    print(f"  Terms indexed   : {index_results['indexed']}")
    print(f"  Failed          : {index_results['failed']}")
    print(f"  Time elapsed    : {elapsed:.2f}s")
    print(f"\n  Top terms by score:")
    print(f"  {'Term':<20} {'Score':<8} {'CTR':<8} {'Recency'}")
    print(f"  {'-'*50}")

    for item in index_results["top_terms"]:
        term  = item["word"]
        score = item["score"]
        ctr   = item["ctr"]
        stats = scored_terms.get(term, {})
        rec   = stats.get("recency", 0)
        print(f"  {term:<20} {score:<8.4f} {ctr:<8.4f} {rec:.4f}")

    print(f"{'='*55}\n")


# ── Full pipeline ─────────────────────────────────────────────
async def run_pipeline(log_filepath: str = "data/search_logs.csv",
                       api_base_url : str = "http://localhost:80"
                       ) -> dict:
    """
    Run the full ingestion pipeline end to end.

    In production:
      - Real-time mode: Kafka consumer, runs continuously
      - Batch mode: Spark job, runs nightly on S3 logs

    Here: reads CSV, processes, pushes to API.
    Same algorithm, right-sized infrastructure.
    """
    print(f"\n{'='*55}")
    print(f"  INGESTION PIPELINE STARTING")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}")

    start = time.perf_counter()

    # Stage 1 — Ingest
    print("\n[1/4] Ingesting logs...")
    logs = read_logs(log_filepath)
    if not logs:
        print("  No logs to process — exiting")
        return {"status": "no_data"}

    # Stage 2 — Clean
    print("\n[2/4] Cleaning and normalising...")
    cleaned = clean_logs(logs)
    if not cleaned:
        print("  No valid entries after cleaning — exiting")
        return {"status": "no_valid_data"}

    # Stage 3 — Score
    print("\n[3/4] Computing scores...")
    scored = compute_term_scores(cleaned)

    for term, stats in list(scored.items())[:5]:
        print(f"  {term:<20} score={stats['score']:.4f} "
              f"clicks={stats['clicks']} "
              f"ctr={stats['ctr']:.2f}")

    # Stage 4 — Index
    print("\n[4/4] Indexing into API...")
    index_results = await index_terms(scored, api_base_url)

    elapsed = time.perf_counter() - start

    # Stage 5 — Report
    print_report(scored, index_results, elapsed)

    return {
        "status"       : "success",
        "terms_scored" : len(scored),
        "terms_indexed": index_results["indexed"],
        "elapsed_s"    : round(elapsed, 2),
    }


if __name__ == "__main__":
    asyncio.run(run_pipeline())