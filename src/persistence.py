import json
from src.trie import Trie, TrieNode

def trie_to_dict(node: TrieNode)->dict:
    return {
        "is_end" : node.is_end,
        "word"   : node.word,
        "frequency":node.frequency,
        "children" : {
            char : trie_to_dict(child)
            for char, child in node.children.items()
        }
    }

def dict_to_trie(data: dict) ->TrieNode:
    node = TrieNode()
    node.is_end = data["is_end"]
    node.word  = data["word"]
    node.frequency = data["frequency"]

    for char, child_data in data["children"].items():
        node.children[char] = dict_to_trie(child_data)
    return node


def save_trie(trie:Trie, filepath : str) -> None:
    data = {
        "size" : trie.size(),
        "root" : trie_to_dict(trie.root)
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent =2)

def load_trie(filepath: str) -> Trie:
    with open(filepath, "r", encoding = "utf-8") as f:
        data = json.load(f)
    
    trie = Trie()
    trie.root = dict_to_trie(data["root"])
    trie._size = data["size"]

    return trie


# ── Run it ────────────────────────────────────────────────────
if __name__ == "__main__":
    from src.data_loader import load_sample_data

    # Build and populate a Trie
    trie = Trie()
    load_sample_data(trie)
    print(f"Original Trie size: {trie.size()}")

    # Save it
    save_trie(trie, "C:\\Users\\HP\\Desktop\\trie.json")
    print("Saved to File")

    # Load it back into a fresh Trie
    loaded_trie = load_trie("C:\\Users\\HP\\Desktop\\trie.json")
    print(f"\nLoaded Trie size: {loaded_trie.size()}")

    # Verify autocomplete works identically
    print("\n── Verification ─────────────────────────────────────")
    for prefix in ["py", "data", "ja"]:
        original = trie.autocomplete(prefix, limit=5)
        loaded   = loaded_trie.autocomplete(prefix, limit=5)
        match    = "Matching" if original == loaded else "No matching"
        print(f"  '{prefix}': original={original}")
        print(f"        loaded  ={loaded}  {match}")