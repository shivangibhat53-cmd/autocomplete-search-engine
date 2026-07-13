"""
Shared application state.

The Trie is built once at startup and shared across all requests.
FastAPI is single-process (one Uvicorn worker = one Python process),
so this module-level singleton is safe — there's only one copy.

If you scale to multiple workers (--workers 4), each worker gets
its own copy of the Trie. For true sharing across workers you'd
move the Trie into Redis — documented in production considerations.
"""
from src.trie import Trie
"""
Shared application state.
Both the Trie and BK-Tree are built once at startup
and shared across all requests.
"""
from src.trie import Trie
from src.bk_tree import BKTree

# Module-level singleton — created once when Python imports this module
trie = Trie()
bk_tree = BKTree()