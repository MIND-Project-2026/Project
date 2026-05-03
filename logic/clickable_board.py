from __future__ import annotations

from typing import Optional
import chess
import streamlit as st

UNICODE_PIECES = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

FILES = "abcdefgh"


def square_name(file_idx: int, rank_idx: int) -> str:
    return f"{FILES[file_idx]}{8 - rank_idx}"


def piece_symbol(piece: chess.Piece | None) -> str:
    if piece is None:
        return "·"
    return UNICODE_PIECES.get(piece.symbol(), "·")


def render_clickable_board(fen: str, key_prefix: str = "board") -> Optional[str]:
    board = chess.Board(fen)

    if f"{key_prefix}_selected" not in st.session_state:
        st.session_state[f"{key_prefix}_selected"] = None

    selected = st.session_state[f"{key_prefix}_selected"]
    played_move = None

    st.markdown(
        """
        <style>
        div[data-testid="column"] button {
            height: 3rem;
            width: 100%;
            font-size: 1.5rem;
            padding: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for rank_idx in range(8):
        cols = st.columns(8, gap="small")
        for file_idx in range(8):
            sq = chess.parse_square(square_name(file_idx, rank_idx))
            sq_name = chess.square_name(sq)
            piece = board.piece_at(sq)
            label = piece_symbol(piece)

            if selected == sq_name:
                label = f"[{label}]"

            if cols[file_idx].button(label, key=f"{key_prefix}_{sq_name}"):
                if selected is None:
                    # first click: choose source square
                    if piece is not None and piece.color == board.turn:
                        st.session_state[f"{key_prefix}_selected"] = sq_name
                        st.rerun()
                else:
                    # clicking same square deselects
                    if selected == sq_name:
                        st.session_state[f"{key_prefix}_selected"] = None
                        st.rerun()

                    move_uci = selected + sq_name

                    # simple auto-queen promotion
                    source_piece = board.piece_at(chess.parse_square(selected))
                    if (
                        source_piece is not None
                        and source_piece.piece_type == chess.PAWN
                        and sq_name[1] in {"1", "8"}
                    ):
                        move_uci += "q"

                    played_move = move_uci
                    st.session_state[f"{key_prefix}_selected"] = None

    if selected:
        st.caption(f"Case sélectionnée : {selected}")

    return played_move