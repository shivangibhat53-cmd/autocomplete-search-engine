import random
from src.trie import Trie


# A curated list of common search terms across different domains.
# In a real product this would come from search logs, but for a
# portfolio project we simulate realistic frequency distributions.
SAMPLE_WORDS = [
    # Programming languages & tools
    "python", "java", "javascript", "typescript", "golang", "rust",
    "kotlin", "swift", "ruby", "php", "scala", "perl",
    "react", "angular", "vue", "svelte", "django", "flask",
    "fastapi", "spring", "express", "nodejs", "docker", "kubernetes",

    # Data & AI
    "pandas", "numpy", "tensorflow", "pytorch", "scikit-learn",
    "matplotlib", "huggingface", "transformers", "keras",
    "machine learning", "deep learning", "neural network",
    "data science", "data analysis", "data engineer",
    "artificial intelligence", "natural language processing",

    # Algorithms & DSA
    "algorithm", "array", "linked list", "binary tree", "binary search",
    "hash table", "hash map", "trie", "graph", "dynamic programming",
    "greedy algorithm", "sorting algorithm", "merge sort", "quick sort",
    "depth first search", "breadth first search", "recursion",

    # General tech
    "github", "git", "api", "rest api", "database", "sql", "nosql",
    "mongodb", "postgresql", "mysql", "redis", "linux", "windows",
    "macos", "vscode", "pycharm", "jupyter notebook",

    # Common words (for realistic prefix collisions)
    "cat", "car", "card", "care", "cart", "carbon", "career", "careful",
    "dog", "door", "down", "download", "downtown",
    "test", "testing", "tester", "text", "texture",
    "app", "apple", "application", "apply", "approach", "appropriate",
    "computer", "computing", "compute", "company", "complete",
]


def load_sample_data(trie: Trie, seed: int = 42) -> int:
    """
    Load sample words into the Trie with realistic frequency
    distributions — popular topics (python, javascript, react)
    get higher frequencies than niche ones.

    Uses a fixed seed so frequencies are reproducible across runs
    (important for testing and demos).

    Returns the number of words loaded.
    """
    random.seed(seed)

    for word in SAMPLE_WORDS:
        # Simulate realistic search frequency:
        # most words are searched rarely (1-20 times),
        # a few "popular" words are searched very often (50-500)
        if random.random() < 0.15:        # 15% chance of being "popular"
            frequency = random.randint(50, 500)
        else:
            frequency = random.randint(1, 20)

        trie.insert(word, frequency)

    return len(SAMPLE_WORDS)


def load_from_file(trie: Trie, filepath: str) -> int:
    """
    Load words from a text file — one word per line.
    Optional format: "word,frequency" (comma-separated).

    Example file content:
        python,150
        java,120
        javascript

    Words without a frequency default to 1.

    Returns the number of words loaded.
    """
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if "," in line:
                word, freq_str = line.split(",", 1)
                frequency = int(freq_str.strip())
            else:
                word      = line
                frequency = 1

            trie.insert(word.strip(), frequency)
            count += 1

    return count


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    trie  = Trie()
    count = load_sample_data(trie)

    print(f"Loaded {count} words")
    print(f"Trie size: {trie.size()} unique words\n")

    # Show top words by frequency
    print("── Top 10 most frequent words ───────────────────────")
    all_words = trie.all_words()
    for word in all_words[:10]:
        freq = trie.get_frequency(word)
        print(f"  {word:<25} freq={freq}")

    # Test autocomplete on a few prefixes
    print("\n── Sample Autocomplete ──────────────────────────────")
    for prefix in ["py", "data", "j", "co", "ca"]:
        results = trie.autocomplete(prefix, limit=5)
        print(f"  '{prefix}' -> {results}")