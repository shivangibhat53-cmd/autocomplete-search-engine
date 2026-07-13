"""
Autocomplete Search Engine — Streamlit Frontend
"""
import streamlit as st
import requests
import pandas as pd
import time
import os
import uuid
API_BASE = os.getenv("API_BASE_URL", "http://localhost:80")

st.set_page_config(
    page_title = "Autocomplete Search Engine",
    page_icon  = "🔍",
    layout     = "wide",
)

# ── Session state ─────────────────────────────────────────────
if "search_history"   not in st.session_state:
    st.session_state.search_history   = []
if "session_cookie"   not in st.session_state:
    st.session_state.session_cookie   = str(uuid.uuid4())
if "selected_words" not in st.session_state:
    st.session_state.selected_words = []
    

# ── API helpers ───────────────────────────────────────────────

def get_session() -> requests.Session:
    """
    Create a requests.Session that always uses the same cookie.
    The cookie is generated once and stored permanently in
    st.session_state — it never changes for this browser tab.
    """
    session = requests.Session()

    # Always restore cookie from session_state if we have one
    # This is critical — without this, every rerun is a new session
    #if st.session_state.session_cookie:
    session.cookies.set(
            "session_id",
            st.session_state.session_cookie,
            domain   = "localhost",
            path     = "/",
        )

    return session
def get_headers() -> dict:
    """Return headers including our stable session ID."""
    headers = {"Content-Type": "application/json"}
    if st.session_state.session_cookie:
        headers["X-Session-ID"] = st.session_state.session_cookie
    return headers

def api_search(query: str,
               limit: int = 10,
               fuzzy: bool = False) -> dict | None:
    try:
        response = requests.get(
            f"{API_BASE}/search",
            params  = {
                "q"    : query,
                "limit": limit,
                "fuzzy": str(fuzzy).lower(),
            },
            headers = {"X-Session-ID": st.session_state.session_cookie},
            timeout = 5,
        )
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to API. Is Docker running?")
    except Exception as e:
        st.error(f"Search error: {e}")
    return None

def api_select(word: str) -> None:
    try:

        response = requests.post(
            f"{API_BASE}/select",
            json    = {"word": word},
            headers = {"X-Session-ID": st.session_state.session_cookie},
            timeout = 3,
        )
        print(f"SELECT '{word}' → "
              f"session={st.session_state.session_cookie[:8]} "
              f"status={response.status_code} "
              f"response={response.text}")
    except Exception as e:
        print(f"Select error: {e}")



def api_stats() -> dict | None:
    try:
        r = requests.get(f"{API_BASE}/stats", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def api_health() -> dict | None:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def api_insert_word(word: str, frequency: int) -> dict | None:
    try:
        r = requests.post(
            f"{API_BASE}/words",
            json    = {"word": word, "frequency": frequency},
            timeout = 5,
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Insert failed: {r.json()}")
    except Exception as e:
        st.error(f"Insert error: {e}")
    return None


def api_delete_word(word: str) -> dict | None:
    try:
        r = requests.delete(
            f"{API_BASE}/words/{word}", timeout=5
        )
        if r.status_code == 200:
            return r.json()
        st.error(f"Delete failed: {r.json()}")
    except Exception as e:
        st.error(f"Delete error: {e}")
    return None


def api_admin_shards() -> dict | None:
    try:
        r = requests.get(
            f"{API_BASE}/admin/shards", timeout=5
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ── Page header ───────────────────────────────────────────────
st.title("🔍 Autocomplete Search Engine")
st.markdown(
    "Trie-based autocomplete · **Consistent hashing** · "
    "**BK-Tree fuzzy search** · **Redis caching** · "
    "**Personalization**"
)

# ── Layout ────────────────────────────────────────────────────
col_search, col_info = st.columns([2, 1])

# ── LEFT — Search ─────────────────────────────────────────────
with col_search:
    st.subheader("Search")

    ctrl1, ctrl2, ctrl3 = st.columns([3, 1, 1])
    with ctrl1:
        query = st.text_input(
            "Type to search",
            placeholder      = "e.g. python, java, mach...",
            label_visibility = "collapsed",
            key              = "search_query",
        )
    with ctrl2:
        fuzzy = st.toggle(
            "Fuzzy",
            value = False,
            help  = "BK-Tree fuzzy matching (handles typos)",
        )
    with ctrl3:
        limit = st.selectbox(
            "Limit", [5, 10, 20],
            index            = 1,
            label_visibility = "collapsed",
        )

    # ── Live results ───────────────────────────────────────────
    if query and len(query.strip()) >= 1:
        start   = time.perf_counter()
        #st.caption(f"Session cookie: {st.session_state.get('session_cookie', 'NONE')[:8] if st.session_state.get('session_cookie') else 'NONE'}")
        results = api_search(
            query.strip(), limit=limit, fuzzy=fuzzy
        )
        #st.write(f"DEBUG session_cookie: {st.session_state.session_cookie}")
        #st.write(f"DEBUG cookies in session: {dict(get_session().cookies)}")
        elapsed = (time.perf_counter() - start) * 1000

        if results:
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Results", results["total"])
            with m2:
                cached = results.get("from_cache", False)
                st.metric("Source",
                          "🔵 Cache" if cached else "🟢 Live")
            with m3:
                st.metric("Shard", results.get("shard", "?"))
            with m4:
                st.metric("Time", f"{elapsed:.0f}ms")

            items = results.get("results", [])
            if items:
                st.markdown("---")
                for i, item in enumerate(items):
                    word   = item["word"]
                    source = item.get("source", "global")
                    score  = item.get("score")

                    badge = {
                        "personal": "🟣 personal",
                        "fuzzy"   : "🟡 fuzzy",
                        "global"  : "🔵 global",
                    }.get(source, "🔵 global")

                    score_txt = (
                        f"  `{score:.2f}`" if score else ""
                    )

                    c1, c2 = st.columns([1, 5])
                    with c1:
                        if st.button("✓",
                                     key=f"sel_{i}_{word}",
                                     help=f"Select {word}"):
                            api_select(word)
                            if word not in \
                               st.session_state.selected_words:
                                st.session_state\
                                  .selected_words.append(word)
                            st.toast(
                                f"Selected: **{word}**",
                                icon="✅"
                            )
                            st.rerun()
                    with c2:
                        st.markdown(
                            f"**{word}** &nbsp; {badge}"
                            f"{score_txt}"
                        )
            else:
                if fuzzy:
                    st.info(
                        "No fuzzy matches within edit distance. "
                        "Try a longer query or disable fuzzy."
                    )
                else:
                    st.info("No prefix matches found.")

    elif not query:
        st.markdown(
            "> 💡 Start typing above — results appear "
            "automatically after each keystroke."
        )

    # ── Selected words ─────────────────────────────────────────
    if st.session_state.selected_words:
        st.divider()
        st.markdown("**Your selections** *(used for personalization)*:")
        cols = st.columns(min(
            len(st.session_state.selected_words[-8:]), 4
        ))
        for i, w in enumerate(
            st.session_state.selected_words[-8:]
        ):
            with cols[i % 4]:
                st.code(w)

        if st.button("🗑 Clear selections"):
            st.session_state.selected_words = []
            try:
                get_session().post(
                    f"{API_BASE}/history/clear", timeout=3
                )
            except Exception:
                pass
            st.rerun()

    # ── Word management ────────────────────────────────────────
    st.divider()
    st.subheader("Word Management")

    tab_add, tab_del = st.tabs(["➕ Add Word", "🗑 Delete Word"])

    with tab_add:
        a1, a2, a3 = st.columns([3, 1, 1])
        with a1:
            new_word = st.text_input(
                "Word", key="new_word",
                placeholder="e.g. streamlit"
            )
        with a2:
            new_freq = st.number_input(
                "Frequency", min_value=1,
                max_value=10000, value=10, key="new_freq"
            )
        with a3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Add", type="primary",
                         key="btn_add"):
                if new_word.strip():
                    res = api_insert_word(
                        new_word.strip().lower(), new_freq
                    )
                    if res:
                        st.success(
                            f"✅ Added '{res['word']}' "
                            f"(freq={res['frequency']})"
                        )
                else:
                    st.warning("Enter a word first")

    with tab_del:
        d1, d2 = st.columns([4, 1])
        with d1:
            del_word = st.text_input(
                "Word to delete", key="del_word",
                placeholder="e.g. pytorch"
            )
        with d2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Delete", type="primary",
                         key="btn_del"):
                if del_word.strip():
                    res = api_delete_word(
                        del_word.strip().lower()
                    )
                    if res:
                        st.success(
                            f"✅ Deleted '{del_word}'"
                        )
                else:
                    st.warning("Enter a word first")

# ── RIGHT — System info ───────────────────────────────────────
with col_info:

    # Health
    st.subheader("🏥 System Health")
    health = api_health()
    if health:
        ok      = health.get("status") == "ok"
        healthy = health.get("healthy_shards", 0)
        total   = health.get("total_shards", 0)

        st.markdown(
            f"{'🟢' if ok else '🔴'} "
            f"**{'Healthy' if ok else 'Degraded'}** — "
            f"{healthy}/{total} shards"
        )
        for shard, state in health.get("shards", {}).items():
            icon = "✅" if state == "closed" else "❌"
            st.markdown(f"{icon} `{shard}` — {state}")
    else:
        st.error("🔴 API unreachable")

    st.divider()

    # Stats
    st.subheader("📊 Stats")
    stats = api_stats()
    if stats:
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total words",
                      stats.get("total_words", 0))
        with c2:
            st.metric("BK-Tree size",
                      stats.get("bk_tree_size", "—"))

        bk_depth = stats.get("bk_tree_depth")
        if bk_depth:
            st.metric("BK-Tree depth", bk_depth)

        top = stats.get("top_words", [])
        if top:
            st.markdown("**Top words:**")
            df = pd.DataFrame([
                {"word" : w["word"],
                 "score": round(w.get("score", 0), 1)}
                for w in top[:10]
            ])
            if not df.empty:
                st.bar_chart(df.set_index("word")["score"])
    else:
        st.info("Stats unavailable")

    st.divider()

    # Shards
    st.subheader("🔀 Shards")
    shards_info = api_admin_shards()
    if shards_info:
        for s in shards_info.get("shards", []):
            ok   = s["status"] == "closed"
            ring = s["in_ring"]
            st.markdown(
                f"{'✅' if ok else '❌'} `{s['name']}` "
                f"{'🔵' if ring else '⭕'}"
            )
    else:
        st.info("Shard info unavailable")

    st.divider()

    # Pipeline
    st.subheader("⚙️ Ingestion Pipeline")
    st.caption(
        "Reads `data/search_logs.csv`, scores terms "
        "by popularity + recency + CTR, updates index."
    )

    if st.button("▶ Run Pipeline", type="primary"):
        with st.spinner("Running ingestion pipeline..."):
            try:
                import asyncio
                from src.pipeline.ingestion import run_pipeline

                result = asyncio.run(
                    run_pipeline(
                        log_filepath = "data/search_logs.csv",
                        api_base_url = API_BASE,
                    )
                )
                if result.get("status") == "success":
                    st.success(
                        f"✅ {result['terms_indexed']} terms "
                        f"indexed in {result['elapsed_s']}s"
                    )
                else:
                    st.warning(str(result))
            except Exception as e:
                st.error(f"Pipeline error: {e}")

    st.divider()

    # Architecture
    st.subheader("🏗 Architecture")
    st.code("""
Nginx :80
  └─ Router Service
      ├─ Consistent hash → Shard 1/2/3
      │   (each holds 1/3 of words)
      ├─ Fuzzy → BK-Tree Service
      ├─ Cache → Redis
      └─ Storage → PostgreSQL
    """, language="text")