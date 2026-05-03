from __future__ import annotations
import chess
import chess.svg

def board_svg(fen: str, size: int = 420) -> str:
    return chess.svg.board(board=chess.Board(fen), size=size)

def _parse_move(board: chess.Board, text: str):
    text = (text or "").strip()
    if not text:
        return None, "Entre un coup en UCI (ex: e2e4) ou SAN (ex: Qe8#)."
    try:
        if len(text) in (4, 5):
            move = chess.Move.from_uci(text.lower())
            if move in board.legal_moves:
                return move, ""
        return board.parse_san(text), ""
    except Exception:
        return None, "Coup invalide pour cette position."

def evaluate_attempt(fen: str, expected_uci: str, user_input: str):
    board = chess.Board(fen)
    move, error = _parse_move(board, user_input)

    if error:
        return {
            "status": "invalid",
            "message": error,
            "board_fen": fen,
            "solved": False,
        }

    expected = chess.Move.from_uci(expected_uci)

    if move == expected:
        san = board.san(move)
        board.push(move)
        return {
            "status": "correct",
            "message": f"Correct : {san}.",
            "board_fen": board.fen(),
            "solved": True,
        }

    played_san = board.san(move)
    expected_san = board.san(expected)
    board.push(move)          # advance so the player sees the resulting position
    return {
        "status": "wrong",
        "message": f"Tu as joué {played_san}. Le meilleur coup était {expected_san}.",
        "board_fen": board.fen(),
        "solved": False,
    }