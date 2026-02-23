import streamlit as st
import random
import requests
import pandas as pd
import io
from typing import Dict, List, Optional

st.set_page_config(page_title="Word Learning & Spelling Game", page_icon="🧠", layout="centered")

# -----------------------
# Utilities
# -----------------------
def normalize(s: str) -> str:
    return ''.join((s or "").strip().lower())

def make_clue(word: str) -> str:
    """First & last letter shown, spaced underscores for the middle. Keeps separators visible."""
    w = (word or "").strip()
    if len(w) <= 2:
        return w
    middle = []
    for ch in w[1:-1]:
        if ch in {' ', '-', '’', "'", '.', ',', '/', '·', '–', '—'}:
            middle.append(ch)
        else:
            middle.append('_')
    return f"{w[0]} " + " ".join(middle) + f" {w[-1]}"

def clean_text(text: str, max_len: int = 240) -> str:
    t = ' '.join((text or '').split())
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"
    return t

# -----------------------
# Online meaning providers (with caching)
# -----------------------
@st.cache_data(show_spinner=False)
def fetch_from_free_dictionary(word: str, timeout: float = 4.0) -> Optional[str]:
    # https://dictionaryapi.dev/
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{requests.utils.quote(word)}"
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list):
            return None
        for entry in data:
            for m in entry.get("meanings", []):
                for d in m.get("definitions", []):
                    definition = d.get("definition")
                    if definition:
                        return clean_text(definition)
        return None
    except Exception:
        return None

@st.cache_data(show_spinner=False)
def fetch_from_datamuse(word: str, timeout: float = 4.0) -> Optional[str]:
    # https://www.datamuse.com/api/
    try:
        url = f"https://api.datamuse.com/words?sp={requests.utils.quote(word)}&md=d&max=1"
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        defs = data[0].get("defs")
        if not defs:
            return None
        first = defs[0]
        if "\t" in first:
            first = first.split("\t", 1)[1]
        return clean_text(first)
    except Exception:
        return None

@st.cache_data(show_spinner=False)
def fetch_from_wikipedia(word: str, timeout: float = 4.0) -> Optional[str]:
    # https://en.wikipedia.org/api/rest_v1/
    try:
        title = requests.utils.quote(word.replace(" ", "_"))
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        desc = data.get("description")
        if desc:
            return clean_text(desc)
        extract = data.get("extract")
        if extract:
            return clean_text(extract)
        return None
    except Exception:
        return None

@st.cache_data(show_spinner=False)
def fetch_meaning(word: str) -> Optional[str]:
    """Try providers fast and in order; return first good meaning."""
    for fn in (fetch_from_free_dictionary, fetch_from_datamuse, fetch_from_wikipedia):
        m = fn(word)
        if m:
            return m
    return None

# -----------------------
# Session state
# -----------------------
if "vocab" not in st.session_state:
    st.session_state.vocab: Dict[str, str] = {}  # {word: meaning}
if "order" not in st.session_state:
    st.session_state.order: List[str] = []
if "idx" not in st.session_state:
    st.session_state.idx = 0
if "correct" not in st.session_state:
    st.session_state.correct = 0
if "wrong" not in st.session_state:
    st.session_state.wrong = []  # list of dicts
if "started" not in st.session_state:
    st.session_state.started = False
if "auto_fetch" not in st.session_state:
    st.session_state.auto_fetch = True

def reset_game():
    st.session_state.order = []
    st.session_state.idx = 0
    st.session_state.correct = 0
    st.session_state.wrong = []
    st.session_state.started = False

def load_vocab_from_textarea_auto(text: str) -> Dict[str, str]:
    words = [w.strip() for w in text.splitlines() if w.strip()]
    return {w: "" for w in words}

def load_vocab_from_textarea_manual(text: str) -> Dict[str, str]:
    vocab: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        w, m = line.split(":", 1)
        w, m = w.strip(), m.strip()
        if w and m:
            vocab[w] = m
    return vocab

def load_vocab_from_csv(file, auto_fetch: bool) -> Dict[str, str]:
    # Accepts: word-only (auto) or word+meaning (manual)
    try:
        df = pd.read_csv(file)
    except Exception:
        # Try Excel as fallback if someone uploads xlsx
        try:
            file.seek(0)
            df = pd.read_excel(file)
        except Exception:
            st.error("Failed to read the file. Please upload CSV with header 'word' (and optional 'meaning').")
            return {}
    cols = {c.strip().lower(): c for c in df.columns}
    if "word" not in cols:
        st.error("CSV must contain a 'word' column.")
        return {}
    if auto_fetch:
        words = [str(x).strip() for x in df[cols["word"]].dropna().tolist()]
        return {w: "" for w in words if w}
    else:
        if "meaning" not in cols:
            st.error("Manual mode requires 'meaning' column.")
            return {}
        out = {}
        for _, row in df.iterrows():
            w = str(row[cols["word"]]).strip() if pd.notna(row[cols["word"]]) else ""
            m = str(row[cols["meaning"]]).strip() if pd.notna(row[cols["meaning"]]) else ""
            if w and m:
                out[w] = m
        return out

# -----------------------
# UI
# -----------------------
st.title("🧠 Word Learning & Spelling Game")

with st.sidebar:
    st.header("Settings")
    auto_fetch = st.toggle("Auto‑fetch meanings from the internet", value=st.session_state.auto_fetch,
                           help="If on, just enter words and the app will fetch meanings online.")
    st.session_state.auto_fetch = auto_fetch

    input_method = st.radio("How will you enter words?",
                            ["Type here", "Upload CSV"],
                            help="CSV: use column 'word' (and optional 'meaning' if not auto-fetch).")

    if input_method == "Type here":
        if auto_fetch:
            sample = "meticulous\ncandid\ntenacious"
            txt = st.text_area("Words (one per line)", height=140, value=sample)
        else:
            sample = "meticulous : showing great attention to detail\ncandid : truthful and straightforward\ntenacious : persistent; not easily giving up"
            txt = st.text_area("Pairs as 'word : meaning' (one per line)", height=180, value=sample)
    else:
        uploaded = st.file_uploader("Upload CSV", type=["csv", "txt", "tsv", "xlsx"])

    colA, colB = st.columns(2)
    with colA:
        if st.button("Load words", use_container_width=True):
            reset_game()
            if input_method == "Type here":
                vocab = load_vocab_from_textarea_auto(txt) if auto_fetch else load_vocab_from_textarea_manual(txt)
            else:
                if uploaded is None:
                    st.warning("Please upload a CSV first.")
                    vocab = {}
                else:
                    vocab = load_vocab_from_csv(uploaded, auto_fetch=auto_fetch)

            # Clean and deduplicate
            vocab = {w.strip(): (m.strip() if m else "") for w, m in vocab.items() if w.strip()}
            st.session_state.vocab = vocab
            if vocab:
                st.success(f"Loaded {len(vocab)} word(s).")
            else:
                st.warning("No valid words found.")
    with colB:
        if st.button("Reset", use_container_width=True):
            st.session_state.vocab = {}
            reset_game()
            st.experimental_rerun()

    if st.session_state.vocab:
        st.caption("Preview (first 20):")
        prev_rows = [{"word": w, "meaning": (m if m else "—")} for w, m in list(st.session_state.vocab.items())[:20]]
        st.dataframe(pd.DataFrame(prev_rows), use_container_width=True, hide_index=True)

        if auto_fetch:
            if st.button("Fetch/Refresh meanings now", use_container_width=True):
                with st.spinner("Fetching meanings…"):
                    updated = {}
                    for i, (w, m) in enumerate(st.session_state.vocab.items(), start=1):
                        st.write(f"Fetching {i}/{len(st.session_state.vocab)}: **{w}**")
                        meaning = fetch_meaning(w) or m
                        updated[w] = meaning or ""
                st.session_state.vocab = updated
                st.success("Done fetching meanings.")

# Main area
if not st.session_state.vocab:
    st.info("Load some words in the sidebar to begin.")
else:
    # Start game / continue
    if not st.session_state.started:
        st.subheader("Ready to start?")
        st.write("The game will randomize your words and test you one by one.")
        if st.button("Start Game ▶️", type="primary"):
            st.session_state.order = list(st.session_state.vocab.keys())
            random.shuffle(st.session_state.order)
            st.session_state.idx = 0
            st.session_state.correct = 0
            st.session_state.wrong = []
            st.session_state.started = True
            st.experimental_rerun()
    else:
        total = len(st.session_state.order)
        if st.session_state.idx >= total:
            # Results
            st.subheader("Results")
            attempted = st.session_state.correct + len(st.session_state.wrong)
            st.metric("Attempted", attempted)
            st.metric("Correct", st.session_state.correct)
            acc = (100.0 * st.session_state.correct / attempted) if attempted > 0 else 0.0
            st.metric("Accuracy", f"{acc:.1f}%")

            if st.session_state.wrong:
                st.write("### Incorrect answers")
                df_wrong = pd.DataFrame(st.session_state.wrong)
                st.dataframe(df_wrong, use_container_width=True, hide_index=True)
                csv = df_wrong.to_csv(index=False).encode("utf-8")
                st.download_button("Download wrong answers (CSV)", data=csv, file_name="wrong_answers.csv", mime="text/csv")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Play Again", type="primary", use_container_width=True):
                    # New random order, keep same vocab
                    st.session_state.order = list(st.session_state.vocab.keys())
                    random.shuffle(st.session_state.order)
                    st.session_state.idx = 0
                    st.session_state.correct = 0
                    st.session_state.wrong = []
                    st.experimental_rerun()
            with col2:
                if st.button("Finish & Reset", use_container_width=True):
                    reset_game()
                    st.experimental_rerun()
        else:
            # Current item
            word = st.session_state.order[st.session_state.idx]
            meaning = st.session_state.vocab.get(word, "")

            # Just-in-time fetch if auto and missing
            if st.session_state.auto_fetch and not meaning:
                with st.spinner(f"Looking up meaning for '{word}'…"):
                    meaning = fetch_meaning(word) or ""
                    st.session_state.vocab[word] = meaning

            if not meaning:
                meaning = st.text_input(f"No meaning found for '{word}'. Type a quick hint to use:", value="", key=f"hint_{st.session_state.idx}")

            clue = make_clue(word)

            st.write(f"**Word {st.session_state.idx + 1}/{total}**")
            st.info(f"**Meaning:** {meaning or '(no meaning)'}")
            st.code(f"Clue: {clue}", language=None)

            with st.form(key=f"form_{st.session_state.idx}", clear_on_submit=False):
                guess = st.text_input("Your answer", value="", key=f"guess_{st.session_state.idx}")
                submitted = st.form_submit_button("Submit")
                if submitted:
                    if normalize(guess) == normalize(word):
                        st.success("✅ Correct!")
                        st.session_state.correct += 1
                    else:
                        st.error(f"❌ Incorrect. Correct word: **{word}**")
                        st.session_state.wrong.append({
                            "clue": clue,
                            "meaning": meaning or "(no meaning)",
                            "your_answer": guess,
                            "correct": word
                        })
                    st.session_state.idx += 1
                    st.experimental_rerun()
