"""
Request and response shapes for every endpoint.
Pydantic validates incoming JSON automatically —
wrong types or missing fields return a 422 error.
"""
from pydantic import BaseModel, Field



# ── Search ────────────────────────────────────────────────────

class SearchResult(BaseModel):
    word     : str
    source   : str                  #"personal"|"global"|"fuzzy"
    score    : float|None= None


class SearchResponse(BaseModel):
    query      : str
    results    : list[SearchResult]
    total      : int
    from_cache : bool = False    # tells client if result was cached


# ── Words ─────────────────────────────────────────────────────

class WordInsertRequest(BaseModel):
    word     : str  = Field(..., min_length=1, max_length=100)
    frequency: int  = Field(default=1, ge=1, le=10000)


class WordInsertResponse(BaseModel):
    word     : str
    frequency: int
    message  : str


class WordDeleteResponse(BaseModel):
    word   : str
    deleted: bool
    message: str


# ── Stats ─────────────────────────────────────────────────────

class TrieStatsResponse(BaseModel):
    total_words  : int
    top_words    : list[SearchResult]
    bk_tree_size : int | None = None
    bk_tree_depth: int | None = None


# ── Health ────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status  : str
    database: str
    redis   : str
    trie    : dict