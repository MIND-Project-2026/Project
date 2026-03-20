# ── core/chess_utils.py ───────────────────────────────────────────────────────
# Pure helper functions for chess logic.
# No API calls, no file I/O — just conversions and classification.
# ─────────────────────────────────────────────────────────────────────────────

import chess
from settings import INACCURACY_THRESHOLD, MISTAKE_THRESHOLD, BLUNDER_THRESHOLD

PIECE_NAMES = {
    chess.PAWN:   "Pawn",
    chess.KNIGHT: "Knight",
    chess.BISHOP: "Bishop",
    chess.ROOK:   "Rook",
    chess.QUEEN:  "Queen",
    chess.KING:   "King",
}

PROMO_NAMES = {
    chess.QUEEN:  "Q",
    chess.ROOK:   "R",
    chess.BISHOP: "B",
    chess.KNIGHT: "N",
}


def piece_name(piece: chess.Piece) -> str:
    return PIECE_NAMES.get(piece.piece_type, "Unknown")


def classify_move(cp_loss: int) -> str:
    """
    Bucket a centipawn loss into a quality label.
    cp_loss should already be clipped to >= 0 before calling this.
    """
    if cp_loss < INACCURACY_THRESHOLD:
        return "Good"
    elif cp_loss < MISTAKE_THRESHOLD:
        return "Inaccuracy"
    elif cp_loss < BLUNDER_THRESHOLD:
        return "Mistake"
    return "Blunder"


def infer_phase(board: chess.Board) -> str:
    """
    Simple heuristic: opening / middlegame / endgame.
    Based on move number and remaining heavy pieces.
    """
    heavy = sum(
        len(board.pieces(pt, color))
        for pt in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]
        for color in [chess.WHITE, chess.BLACK]
    )
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + \
             len(board.pieces(chess.QUEEN, chess.BLACK))

    if board.fullmove_number <= 10 and heavy >= 12:
        return "opening"
    if queens == 0 and heavy <= 6:
        return "endgame"
    return "middlegame"


def extract_cp(eval_entry) -> int:
    """
    Convert a Lichess eval entry to a centipawn integer (white's perspective).

    Lichess returns evals in several shapes depending on the endpoint:
      - plain int                    → use directly
      - {"eval": int}                → unwrap and recurse
      - {"cp": int}                  → centipawns
      - {"mate": int}                → encode as ±(10000 - abs(mate))
    """
    if eval_entry is None:
        return 0
    if isinstance(eval_entry, (int, float)):
        return int(eval_entry)
    if not isinstance(eval_entry, dict):
        return 0
    if "eval" in eval_entry:
        return extract_cp(eval_entry["eval"])
    if "mate" in eval_entry and eval_entry["mate"] is not None:
        m = int(eval_entry["mate"])
        return (10000 - m) if m > 0 else (-10000 - m)
    if "cp" in eval_entry and eval_entry["cp"] is not None:
        return int(eval_entry["cp"])
    return 0


def best_move_san(eval_entry: dict, board: chess.Board) -> str:
    """
    Extract the best move UCI from a Lichess eval entry and convert to SAN.
    Returns empty string if not available.
    """
    if not isinstance(eval_entry, dict):
        return ""
    uci = eval_entry.get("best", "")
    if not uci:
        return ""
    try:
        return board.san(chess.Move.from_uci(uci))
    except Exception:
        return uci
