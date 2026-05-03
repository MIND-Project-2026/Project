from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

from logic.csv_logic import validate_history_csv
from logic.lichess_logic import check_lichess_username, fetch_games_as_pgn
from logic.model_logic import load_puzzles, rank_puzzles, train_or_load_model
from logic.profile_logic import (
    build_profile_from_csv,
    build_profile_from_lichess_games,
    default_profile,
)
from logic.clickable_chessboard import clickable_chessboard

BASE_DIR = Path(__file__).resolve().parent
PUZZLES_PATH = BASE_DIR / "data" / "puzzles.csv"
DEFAULT_TOP_N = 8
FIXED_LICHESS_GAMES = 50


st.set_page_config(
    page_title="Chess Trainer Complete",
    page_icon="♟️",
    layout="wide",
)

st.markdown(
    """
<style>
.block-container {
    max-width: 1250px;
    padding-top: 1rem;
    padding-bottom: 2rem;
}
.hero {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 18px;
    padding: 1.1rem 1.2rem;
    margin-bottom: 1rem;
}
.hero h1 {
    margin: 0;
    color: #0f172a;
    font-size: 1.9rem;
}
.hero p {
    margin: 0.35rem 0 0 0;
    color: #475569;
    font-size: 1rem;
}
.badge {
    display: inline-block;
    background: #eef2ff;
    color: #1e3a8a;
    border: 1px solid #c7d2fe;
    padding: 0.20rem 0.55rem;
    border-radius: 999px;
    margin-right: 0.35rem;
    margin-bottom: 0.35rem;
    font-size: 0.82rem;
}
.puzzle-board-center {
    max-width: 620px;
    margin: 0 auto;
}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data
def get_puzzles():
    return load_puzzles(PUZZLES_PATH)


@st.cache_resource
def warm_model():
    return train_or_load_model(get_puzzles())


puzzles_df = get_puzzles()
warm_model()


def init_state() -> None:
    if "profile" not in st.session_state:
        st.session_state.profile = default_profile()
    if "recommendations" not in st.session_state:
        st.session_state.recommendations = rank_puzzles(
            st.session_state.profile,
            puzzles_df,
            top_n=DEFAULT_TOP_N,
        )
    if "selected_puzzle_id" not in st.session_state:
        st.session_state.selected_puzzle_id = None
    if "puzzle_started_at" not in st.session_state:
        st.session_state.puzzle_started_at = None
    if "board_orientation" not in st.session_state:
        st.session_state.board_orientation = "white"
    if "profile_visible" not in st.session_state:
        st.session_state.profile_visible = False


def refresh_recommendations() -> None:
    st.session_state.recommendations = rank_puzzles(
        st.session_state.profile,
        puzzles_df,
        top_n=DEFAULT_TOP_N,
    )
    st.session_state.selected_puzzle_id = None
    st.session_state.puzzle_started_at = None


def choose_puzzle(puzzle_row) -> None:
    st.session_state.selected_puzzle_id = puzzle_row["puzzle_id"]
    st.session_state.board_orientation = "white" if " w " in puzzle_row["fen"] else "black"
    st.session_state.puzzle_started_at = time.time()


init_state()


def quality_label(score: float, high: str, medium: str, low: str) -> str:
    if score >= 0.95:
        return high
    if score >= 0.65:
        return medium
    return low


def prettify_reason(reason: str, fen: str) -> list[tuple[str, str]]:
    phase = None
    piece = None
    tactics: list[str] = []
    difficulty_score = None
    gap_score = None

    for raw_part in (reason or "").split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue

        left, value_text = part.split("=", 1)
        try:
            score = float(value_text.strip())
        except ValueError:
            score = 0.0

        if ":" in left:
            key, value = left.split(":", 1)
            key = key.strip()
            value = value.strip()
        else:
            key = left.strip()
            value = ""

        if key == "phase":
            phase = value.title()
        elif key == "piece":
            piece = value.title()
        elif key == "tactic":
            tactics.append(value.title())
        elif key == "difficulty_fit":
            difficulty_score = score
        elif key == "gap_bonus":
            gap_score = score

    pretty: list[tuple[str, str]] = []

    side_to_play = "Blancs" if " w " in fen else "Noirs"
    pretty.append(("À jouer", side_to_play))

    if phase:
        pretty.append(("Phase ciblée", phase))
    if piece:
        pretty.append(("Pièce ciblée", piece))
    if tactics:
        pretty.append(("Motifs ciblés", ", ".join(dict.fromkeys(tactics))))
    if difficulty_score is not None:
        pretty.append(
            (
                "Difficulté",
                quality_label(difficulty_score, "Très adaptée", "Adaptée", "Moins adaptée"),
            )
        )
    if gap_score is not None:
        pretty.append(
            (
                "Clarté du puzzle",
                quality_label(gap_score, "Très forte", "Bonne", "Plus faible"),
            )
        )

    if len(pretty) == 1 and reason:
        pretty.append(("Raison", reason))

    return pretty


def render_reason_block(reason: str, fen: str) -> None:
    items = prettify_reason(reason, fen)
    if not items:
        return

    html = "".join(
        f"<div style='margin:0; line-height:1.8; padding:0 0 2px 0;'><b>{label} :</b> {value}</div>"
        for label, value in items
    )
    st.markdown(html, unsafe_allow_html=True)


st.markdown(
    """
<div class="hero">
    <h1>♟️ Chess Trainer Complete</h1>
    <p>
        Profil joueur, recommandations ciblées, puis puzzle interactif.
    </p>
</div>
""",
    unsafe_allow_html=True,
)

st.subheader("Construire le profil")

tab1, tab2, tab3 = st.tabs(["Pseudo Lichess", "Importer CSV", "Mode général"])

with tab1:
    username = st.text_input("Pseudo Lichess", placeholder="ex: Hikaru")
    if st.button("Construire le profil depuis Lichess", use_container_width=True):
        ok, msg = check_lichess_username(username)
        if not ok:
            st.error(msg)
        else:
            with st.spinner("Récupération des parties et construction du profil..."):
                games, _ = fetch_games_as_pgn(username, max_games=FIXED_LICHESS_GAMES)

            if len(games) < FIXED_LICHESS_GAMES:
                st.error("Ce joueur doit avoir au moins 50 parties analysées disponibles sur Lichess.")
            else:
                profile = build_profile_from_lichess_games(username, games)
                if int(profile.get("games_count", 0)) < FIXED_LICHESS_GAMES:
                    st.error("Ce joueur doit avoir au moins 50 parties analysables pour construire le profil.")
                else:
                    st.session_state.profile = profile
                    st.session_state.profile_visible = True
                    refresh_recommendations()
                    st.success("Profil chargé.")

with tab2:
    uploaded = st.file_uploader("Historique CSV", type=["csv"])
    if uploaded is not None and st.button("Construire le profil depuis le CSV", use_container_width=True):
        valid, msg, df = validate_history_csv(uploaded)
        if not valid:
            st.error(msg)
        else:
            with st.spinner("Validation et construction du profil..."):
                st.session_state.profile = build_profile_from_csv(df)
                st.session_state.profile_visible = True
                refresh_recommendations()
            st.success("Profil CSV chargé.")

with tab3:
    if st.button("Activer le mode général", use_container_width=True):
        st.session_state.profile = default_profile()
        st.session_state.profile_visible = True
        refresh_recommendations()

st.subheader("Résumé du profil")

if not st.session_state.profile_visible:
    st.caption("Aucun profil chargé pour le moment.")
else:
    profile = st.session_state.profile

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Parties", profile.get("games_count", 0))
    m2.metric("Coups", profile.get("moves_analyzed", 0))
    m3.metric("Difficulté", profile.get("recommended_difficulty_bucket", "medium").title())
    m4.metric("Qualité", profile.get("profile_quality", "general").title())

    info1, info2 = st.columns(2)
    with info1:
        if profile.get("username"):
            st.write(f"**Pseudo :** {profile.get('username')}")
        if profile.get("source") == "general":
            st.write("**Mode :** général")
        elif profile.get("source"):
            st.write(f"**Source :** {profile.get('source')}")

    with info2:
        st.write(f"**Phase faible :** {profile.get('primary_weak_phase', '-')}")
        st.write(f"**Pièce faible :** {profile.get('primary_weak_piece', '-')}")
        st.write(f"**Motif faible :** {profile.get('primary_weak_tactic', '-')}")

    if st.button("Recalculer les recommandations"):
        refresh_recommendations()
        st.rerun()

recs = st.session_state.recommendations.copy()

st.subheader("Recommandations")
st.caption("Le puzzle choisi s’ouvre juste en dessous de sa carte.")

if recs.empty:
    st.warning("Aucune recommandation disponible.")
else:
    for idx, row in recs.iterrows():
        is_active = st.session_state.selected_puzzle_id == row["puzzle_id"]

        st.markdown(f"### {idx + 1}. {row['title']}")

        render_reason_block(row.get("recommendation_reason", ""),row["fen"])

        st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)
        if not is_active:
            if st.button("Choisir ce puzzle", key=f"choose_{row['puzzle_id']}"):
                choose_puzzle(row)
                st.rerun()
                
        if is_active:
            puzzle = row
            start_fen = puzzle["fen"]
            board_orientation = "white" if " w " in start_fen else "black"
            elapsed = int(time.time() - st.session_state.puzzle_started_at) if st.session_state.puzzle_started_at else 0
            st.markdown('<div class="puzzle-board-center">', unsafe_allow_html=True)
            clickable_chessboard(
                fen=start_fen,
                orientation=board_orientation,
                expected_uci=puzzle["solution_uci"],
                key=f"click_board_{puzzle['puzzle_id']}",
            )
            st.markdown("</div>", unsafe_allow_html=True)

        st.divider()