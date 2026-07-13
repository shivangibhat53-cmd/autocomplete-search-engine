"""
Loads ALL words from PostgreSQL into the BK-Tree.

Unlike shards (which load only their assigned words),
the BK-Tree service loads everything — it needs the complete
vocabulary to find fuzzy matches across all possible corrections.
"""
from src.bk_tree import BKTree
from src.db.models import get_all_words


async def load_all_words(bk_tree: BKTree) -> int:
    """
    Load every word from Postgres into the BK-Tree.
    Returns the number of words loaded.

    Called once at startup. The BK-Tree is then kept in sync
    via InsertWord gRPC calls whenever new words are added.
    """
    all_words = await get_all_words()

    for row in all_words:
        bk_tree.insert(row["word"], row["frequency"])

    print(f"  BK-Tree: loaded {len(all_words)} words from Postgres")
    return len(all_words)