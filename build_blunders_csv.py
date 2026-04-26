#!/usr/bin/env python3
"""Build blunders.csv from games.csv and moves.csv."""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import chess


DEFAULT_GAMES = "output/games.csv"
DEFAULT_MOVES = "output/moves.csv"
DEFAULT_OUTPUT = "output/blunders.csv"
DEFAULT_QUALITIES = ("Mistake", "Blunder")

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

PIECE_NAMES = {
    chess.PAWN: "Pawn",
    chess.KNIGHT: "Knight",
    chess.BISHOP: "Bishop",
    chess.ROOK: "Rook",
    chess.QUEEN: "Queen",
    chess.KING: "King",
}

HOME_RANK = {
    chess.WHITE: 0,
    chess.BLACK: 7,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build blunders.csv from games.csv and moves.csv")
    parser.add_argument("--games-csv", default=DEFAULT_GAMES, help="Path to games.csv")
    parser.add_argument("--moves-csv", default=DEFAULT_MOVES, help="Path to moves.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to output blunders.csv")
    parser.add_argument(
        "--qualities",
        nargs="+",
        default=list(DEFAULT_QUALITIES),
        help="Move qualities to keep (default: Mistake Blunder)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap on output rows after filtering (0 = all)",
    )
    return parser.parse_args()


def _load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _safe_int(value: object, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _safe_float(value: object, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _normalize_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _orientation(color_text: str) -> chess.Color:
    return chess.WHITE if str(color_text).strip().lower() == "white" else chess.BLACK


def _cp_from_white_pov(white_cp: Optional[float], player_color: chess.Color) -> Optional[float]:
    if white_cp is None:
        return None
    return white_cp if player_color == chess.WHITE else -white_cp


def _bucket_eval_state(cp: Optional[float]) -> str:
    if cp is None:
        return ""
    if cp >= 250:
        return "winning"
    if cp >= 80:
        return "better"
    if cp > -80:
        return "equal"
    if cp > -250:
        return "worse"
    return "losing"


def _transition_label(before: str, after: str) -> str:
    if not before or not after:
        return ""
    return f"{before}_to_{after}"

def _material_balance(board: chess.Board, perspective: chess.Color) -> int:
    white_total = 0
    black_total = 0
    for piece_type, value in PIECE_VALUES.items():
        white_total += len(board.pieces(piece_type, chess.WHITE)) * value
        black_total += len(board.pieces(piece_type, chess.BLACK)) * value
    score = white_total - black_total
    return score if perspective == chess.WHITE else -score


def _piece_squares(board: chess.Board, color: chess.Color, *, include_king: bool = False) -> Iterable[chess.Square]:
    for square, piece in board.piece_map().items():
        if piece.color != color:
            continue
        if not include_king and piece.piece_type == chess.KING:
            continue
        yield square


def _count_attackers(board: chess.Board, square: chess.Square, color: chess.Color) -> int:
    return len(board.attackers(color, square))


def _hanging_pieces(board: chess.Board, color: chess.Color) -> List[Tuple[int, str, str]]:
    opp = not color
    rows: List[Tuple[int, str, str]] = []
    for square in _piece_squares(board, color, include_king=False):
        piece = board.piece_at(square)
        if piece is None:
            continue
        attacked = _count_attackers(board, square, opp)
        defended = _count_attackers(board, square, color)
        if attacked > 0 and defended < attacked:
            rows.append((PIECE_VALUES[piece.piece_type], PIECE_NAMES[piece.piece_type], chess.square_name(square)))
    rows.sort(reverse=True)
    return rows


def _king_ring(board: chess.Board, color: chess.Color) -> set[chess.Square]:
    king_square = board.king(color)
    if king_square is None:
        return set()
    ring = {king_square}
    file_idx = chess.square_file(king_square)
    rank_idx = chess.square_rank(king_square)
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            nf = file_idx + df
            nr = rank_idx + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                ring.add(chess.square(nf, nr))
    return ring


def _enemy_attacks_on_ring(board: chess.Board, color: chess.Color) -> int:
    opp = not color
    return sum(len(board.attackers(opp, sq)) for sq in _king_ring(board, color))


def _open_file_near_king(board: chess.Board, color: chess.Color) -> int:
    king_square = board.king(color)
    if king_square is None:
        return 0
    file_idx = chess.square_file(king_square)
    files = [f for f in (file_idx - 1, file_idx, file_idx + 1) if 0 <= f < 8]
    count = 0
    for file_no in files:
        own_pawns = [sq for sq in board.pieces(chess.PAWN, color) if chess.square_file(sq) == file_no]
        if not own_pawns:
            count += 1
    return count


def _diagonal_pressure_on_ring(board: chess.Board, color: chess.Color) -> int:
    opp = not color
    ring = _king_ring(board, color)
    attackers = 0
    for square, piece in board.piece_map().items():
        if piece.color != opp or piece.piece_type not in {chess.BISHOP, chess.QUEEN}:
            continue
        attacks = board.attacks(square)
        attackers += sum(1 for target in ring if target in attacks)
    return attackers


def _king_danger(board: chess.Board, color: chess.Color) -> float:
    king_square = board.king(color)
    if king_square is None:
        return 9999.0

    ring_attacks = _enemy_attacks_on_ring(board, color)
    open_files = _open_file_near_king(board, color)
    diagonal_pressure = _diagonal_pressure_on_ring(board, color)
    in_check = 1 if board.is_check() and board.turn == color else 0
    castled_bonus = 0.0
    if chess.square_rank(king_square) == HOME_RANK[color] and chess.square_file(king_square) in {2, 6}:
        castled_bonus = -0.6

    return round(0.45 * ring_attacks + 1.2 * open_files + 0.35 * diagonal_pressure + 2.0 * in_check + castled_bonus, 3)


def _lost_castling_rights(before: chess.Board, after: chess.Board, color: chess.Color) -> bool:
    before_any = before.has_kingside_castling_rights(color) or before.has_queenside_castling_rights(color)
    after_any = after.has_kingside_castling_rights(color) or after.has_queenside_castling_rights(color)
    return before_any and not after_any


def _back_rank_weak(board: chess.Board, color: chess.Color) -> bool:
    king_square = board.king(color)
    if king_square is None:
        return False
    if chess.square_rank(king_square) != HOME_RANK[color]:
        return False

    next_rank = 1 if color == chess.WHITE else 6
    blocked_or_bad = 0
    file_idx = chess.square_file(king_square)
    for nf in (file_idx - 1, file_idx, file_idx + 1):
        if not (0 <= nf < 8):
            continue
        sq = chess.square(nf, next_rank)
        occupant = board.piece_at(sq)
        occupied_by_own = occupant is not None and occupant.color == color
        attacked = board.is_attacked_by(not color, sq)
        if occupied_by_own or attacked:
            blocked_or_bad += 1
    enemy_heavy = len(board.pieces(chess.ROOK, not color)) + len(board.pieces(chess.QUEEN, not color))
    return blocked_or_bad >= 2 and enemy_heavy > 0


def _king_escape_squares(board: chess.Board, color: chess.Color) -> int:
    king_square = board.king(color)
    if king_square is None:
        return 0
    count = 0
    file_idx = chess.square_file(king_square)
    rank_idx = chess.square_rank(king_square)
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            nf = file_idx + df
            nr = rank_idx + dr
            if not (0 <= nf < 8 and 0 <= nr < 8):
                continue
            sq = chess.square(nf, nr)
            occupant = board.piece_at(sq)
            if occupant is not None and occupant.color == color:
                continue
            if board.is_attacked_by(not color, sq):
                continue
            count += 1
    return count


def _checks_available(board: chess.Board) -> int:
    count = 0
    for move in board.legal_moves:
        try:
            if board.gives_check(move):
                count += 1
        except Exception:
            continue
    return count


def _is_en_passant_move(board: chess.Board, move: chess.Move) -> bool:
    try:
        return board.is_en_passant(move)
    except Exception:
        return False


def _has_en_passant(board: chess.Board) -> bool:
    return any(_is_en_passant_move(board, move) for move in board.legal_moves)


def _attacked_valuable_enemy_squares(board: chess.Board, color: chess.Color, from_square: chess.Square) -> List[chess.Square]:
    piece = board.piece_at(from_square)
    if piece is None or piece.color != color:
        return []
    attacks = board.attacks(from_square)
    result: List[chess.Square] = []
    for target in attacks:
        victim = board.piece_at(target)
        if victim is None or victim.color == color or victim.piece_type == chess.KING:
            continue
        result.append(target)
    return result


def _fork_flags(board: chess.Board) -> Dict[str, bool]:
    color = board.turn
    has_double_attack = False
    has_fork = False
    has_knight_fork = False
    has_pawn_fork = False

    for move in board.legal_moves:
        if _is_en_passant_move(board, move):
            continue
        piece = board.piece_at(move.from_square)
        if piece is None or piece.color != color:
            continue

        after = board.copy(stack=False)
        after.push(move)
        targets = _attacked_valuable_enemy_squares(after, color, move.to_square)
        if len(targets) >= 2:
            has_double_attack = True
            values = sorted((PIECE_VALUES[after.piece_at(sq).piece_type] for sq in targets if after.piece_at(sq) is not None), reverse=True)
            if len(values) >= 2 and values[1] >= 300:
                has_fork = True
                if piece.piece_type == chess.KNIGHT:
                    has_knight_fork = True
                if piece.piece_type == chess.PAWN:
                    has_pawn_fork = True

    return {
        "opponent_has_double_attack_after": has_double_attack,
        "opponent_has_fork_after": has_fork,
        "opponent_has_knight_fork_after": has_knight_fork,
        "opponent_has_pawn_fork_after": has_pawn_fork,
    }


def _discovered_attack_exists(board: chess.Board) -> bool:
    color = board.turn
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece is None or piece.color != color:
            continue
        if piece.piece_type not in {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.PAWN}:
            continue

        before_targets = set(_attacked_valuable_enemy_squares(board, color, move.from_square))
        after = board.copy(stack=False)
        after.push(move)

        for square, other_piece in after.piece_map().items():
            if other_piece.color != color or square == move.to_square:
                continue
            after_targets = set(_attacked_valuable_enemy_squares(after, color, square))
            new_targets = after_targets - before_targets
            if new_targets:
                return True
    return False


def _trap_piece_exists(board: chess.Board) -> bool:
    color = board.turn
    enemy = not color

    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)

        for square in _piece_squares(after, enemy, include_king=False):
            piece = after.piece_at(square)
            if piece is None:
                continue
            if piece.piece_type == chess.PAWN:
                continue
            temp = after.copy(stack=False)
            temp.turn = enemy
            escape_count = 0
            for reply in temp.legal_moves:
                if reply.from_square != square:
                    continue
                escape_count += 1
                if escape_count >= 2:
                    break
            attacked = after.is_attacked_by(color, square)
            defended = after.is_attacked_by(enemy, square)
            if escape_count <= 1 and attacked and not defended:
                return True
    return False


def _smothered_mate_pattern(board: chess.Board) -> bool:
    color = board.turn
    enemy = not color
    enemy_king = board.king(enemy)
    if enemy_king is None:
        return False

    enemy_piece = board.piece_at(enemy_king)
    if enemy_piece is None or enemy_piece.piece_type != chess.KING:
        return False

    own_neighbors = 0
    file_idx = chess.square_file(enemy_king)
    rank_idx = chess.square_rank(enemy_king)
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            nf = file_idx + df
            nr = rank_idx + dr
            if not (0 <= nf < 8 and 0 <= nr < 8):
                continue
            sq = chess.square(nf, nr)
            occupant = board.piece_at(sq)
            if occupant is not None and occupant.color == enemy:
                own_neighbors += 1

    knight_checks = 0
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece is None or piece.color != color or piece.piece_type != chess.KNIGHT:
            continue
        try:
            gives_check = board.gives_check(move)
        except Exception:
            gives_check = False
        if not gives_check:
            continue
        knight_checks += 1

    return own_neighbors >= 3 and knight_checks > 0


def build_indexes(games_rows: List[Dict[str, str]], moves_rows: List[Dict[str, str]]):
    games_by_id: Dict[str, Dict[str, str]] = {}
    for row in games_rows:
        game_id = (row.get("game_id") or "").strip()
        if game_id:
            games_by_id[game_id] = row

    moves_by_game_ply: Dict[Tuple[str, int], Dict[str, str]] = {}
    for row in moves_rows:
        game_id = (row.get("game_id") or "").strip()
        ply = _safe_int(row.get("ply"))
        if not game_id or ply is None:
            continue
        moves_by_game_ply[(game_id, ply)] = row

    return games_by_id, moves_by_game_ply


def iter_candidate_rows(moves_rows: List[Dict[str, str]], qualities: Sequence[str]) -> Iterable[Dict[str, str]]:
    allowed = {q.strip() for q in qualities if q.strip()}
    for row in moves_rows:
        if not _normalize_bool(row.get("is_target_move")):
            continue
        quality = (row.get("move_quality") or "").strip()
        if quality not in allowed:
            continue
        yield row


def compute_row(move_row: Dict[str, str], games_by_id: Dict[str, Dict[str, str]]) -> Optional[Dict[str, object]]:
    game_id = (move_row.get("game_id") or "").strip()
    game_row = games_by_id.get(game_id)
    if game_row is None:
        return None

    fen_before = (move_row.get("fen_before") or "").strip()
    move_uci = (move_row.get("move_uci") or "").strip()
    if not fen_before or not move_uci:
        return None

    try:
        board_before = chess.Board(fen_before)
        played_move = chess.Move.from_uci(move_uci)
        board_after = board_before.copy(stack=False)
        board_after.push(played_move)
    except Exception:
        return None

    target_color = _orientation(move_row.get("player_color"))
    eval_white_before = _safe_float(move_row.get("eval_white_before"))
    eval_white_after = _safe_float(move_row.get("eval_white_after"))
    eval_player_before = _cp_from_white_pov(eval_white_before, target_color)
    eval_player_after = _cp_from_white_pov(eval_white_after, target_color)

    material_before = _material_balance(board_before, target_color)
    material_after = _material_balance(board_after, target_color)
    hanging_after = _hanging_pieces(board_after, target_color)

    # Opponent to move after this.
    tactical_flags = _fork_flags(board_after)

    result: Dict[str, object] = {
        "phase": (move_row.get("phase") or "").strip(),
        "speed": (game_row.get("speed") or "").strip(),
        "opening_name": (game_row.get("opening_name") or "").strip(),
        "target_elo": _safe_int(game_row.get("target_elo")),
        "opponent_elo": _safe_int(game_row.get("opponent_elo")),
        "elo_diff": (
            (_safe_int(game_row.get("target_elo"), 0) or 0) - (_safe_int(game_row.get("opponent_elo"), 0) or 0)
            if _safe_int(game_row.get("target_elo")) is not None and _safe_int(game_row.get("opponent_elo")) is not None
            else ""
        ),
        "target_result": (game_row.get("target_result") or "").strip(),
        "fen_before": fen_before,
        "fen_after_move": board_after.fen(),
        "move_san": (move_row.get("move_san") or "").strip(),
        "move_uci": move_uci,
        "is_capture": _normalize_bool(move_row.get("is_capture")),
        "is_check": _normalize_bool(move_row.get("is_check")),
        "is_castle": _normalize_bool(move_row.get("is_castle")),
        "is_promotion": _normalize_bool(move_row.get("is_promotion")),
        "promotion_piece": (move_row.get("promotion_piece") or "").strip(),
        "cp_loss": _safe_float(move_row.get("cp_loss")),
        "move_quality": (move_row.get("move_quality") or "").strip(),
        "eval_player_before_cp": eval_player_before,
        "eval_player_after_cp": eval_player_after,
        "eval_state_before": _bucket_eval_state(eval_player_before),
        "eval_state_after": _bucket_eval_state(eval_player_after),
        "eval_state_transition": _transition_label(_bucket_eval_state(eval_player_before), _bucket_eval_state(eval_player_after)),
        "material_balance_before_cp": material_before,
        "material_balance_after_move_cp": material_after,
        "material_balance_delta_cp": material_after - material_before,
        "hanging_pieces_count_after": len(hanging_after),
        "piece_hung_after_move": bool(hanging_after),
        "hung_piece_type": hanging_after[0][1] if hanging_after else "",
        "king_danger_before": _king_danger(board_before, target_color),
        "king_danger_after": _king_danger(board_after, target_color),
        "king_danger_delta": round(_king_danger(board_after, target_color) - _king_danger(board_before, target_color), 3),
        "lost_castling_rights": _lost_castling_rights(board_before, board_after, target_color),
        "back_rank_weak_after": _back_rank_weak(board_after, target_color),
        "king_escape_squares_after": _king_escape_squares(board_after, target_color),
        "checks_available_to_opponent_after": _checks_available(board_after),
        "opponent_has_en_passant_after": _has_en_passant(board_after),
        "opponent_has_discovered_attack_after": _discovered_attack_exists(board_after),
        "opponent_can_trap_piece_after_move": _trap_piece_exists(board_after),
        "opponent_has_smothered_mate_pattern_after": _smothered_mate_pattern(board_after),
    }
    result.update(tactical_flags)
    return result


FIELDNAMES = [
    "phase",
    "opening_name",
    "target_elo",
    "opponent_elo",
    "elo_diff",
    "target_result",
    "fen_before",
    "fen_after_move",
    "move_san",
    "move_uci",
    "is_capture",
    "is_check",
    "is_castle",
    "is_promotion",
    "promotion_piece",
    "cp_loss",
    "move_quality",
    "eval_player_before_cp",
    "eval_player_after_cp",
    "eval_state_before",
    "eval_state_after",
    "eval_state_transition",
    "material_balance_before_cp",
    "material_balance_after_move_cp",
    "material_balance_delta_cp",
    "hanging_pieces_count_after",
    "piece_hung_after_move",
    "hung_piece_type",
    "king_danger_before",
    "king_danger_after",
    "king_danger_delta",
    "lost_castling_rights",
    "back_rank_weak_after",
    "king_escape_squares_after",
    "checks_available_to_opponent_after",
    "opponent_has_en_passant_after",
    "opponent_has_double_attack_after",
    "opponent_has_fork_after",
    "opponent_has_knight_fork_after",
    "opponent_has_pawn_fork_after",
    "opponent_has_discovered_attack_after",
    "opponent_can_trap_piece_after_move",
    "opponent_has_smothered_mate_pattern_after",
]


def write_csv(rows: List[Dict[str, object]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    games_rows = _load_csv(args.games_csv)
    moves_rows = _load_csv(args.moves_csv)
    games_by_id, _ = build_indexes(games_rows, moves_rows)

    rows: List[Dict[str, object]] = []
    for move_row in iter_candidate_rows(moves_rows, args.qualities):
        built = compute_row(move_row, games_by_id)
        if built is None:
            continue
        rows.append(built)
        if args.max_rows > 0 and len(rows) >= args.max_rows:
            break

    write_csv(rows, args.output)
    print("Built blunders.csv")
    print("-" * 60)
    print(f"Rows:   {len(rows):,}")
    print(f"Saved:  {args.output}")


if __name__ == "__main__":
    main()