# Parse raw Lichess games into game/move/summary rows.

import io
import math
import logging
import statistics
from settings import ALLOWED_SPEEDS, ALLOWED_VARIANTS, MIN_PLIES
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import chess
import chess.pgn

from chess_utils import (
    piece_name, classify_move, infer_phase,
    extract_cp, best_move_san,
)

logger = logging.getLogger(__name__)


# Small helpers

def _ms_to_utc(ms: Optional[int]) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _time_control_str(game_data: dict) -> str:
    clock = game_data.get("clock")
    if isinstance(clock, dict):
        try:
            return f"{int(clock['initial'])}+{int(clock['increment'])}"
        except Exception:
            pass
    return ""


def _safe_mean(xs: list) -> float:
    return float(sum(xs) / len(xs)) if xs else float("nan")

def _safe_median(xs: list) -> float:
    return float(statistics.median(xs)) if xs else float("nan")

def _safe_p90(xs: list) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(math.ceil(0.9 * len(s))) - 1))
    return float(s[k])


# Main parser

def parse_game(
    game_data: dict,
    target_player: str,
) -> Tuple[Optional[dict], List[dict], Optional[dict]]:
    """Parse one game for one target player."""
    move_rows: List[dict] = []

    try:
        # Parse PGN
        pgn_game = chess.pgn.read_game(io.StringIO(game_data.get("pgn", "")))
        if not pgn_game:
            return None, [], None

        analysis = game_data.get("analysis", [])
        if not analysis:
            return None, [], None

        # Identify players
        players     = game_data.get("players", {})
        white_info  = players.get("white", {})
        black_info  = players.get("black", {})
        white_name  = (white_info.get("user") or {}).get("name", "").strip()
        black_name  = (black_info.get("user") or {}).get("name", "").strip()
        white_elo   = white_info.get("rating")
        black_elo   = black_info.get("rating")
        white_diff  = white_info.get("ratingDiff")
        black_diff  = black_info.get("ratingDiff")

        tl = target_player.lower()
        if white_name.lower() == tl:
            target_color     = chess.WHITE
            opponent_name    = black_name
            target_elo       = white_elo
            opponent_elo     = black_elo
        elif black_name.lower() == tl:
            target_color     = chess.BLACK
            opponent_name    = white_name
            target_elo       = black_elo
            opponent_elo     = white_elo
        else:
            return None, [], None   # target not in this game

        # Game metadata
        game_id      = game_data.get("id", "")
        date_utc     = _ms_to_utc(game_data.get("createdAt"))
        time_control = _time_control_str(game_data)
        variant      = game_data.get("variant", "standard")
        if variant not in ALLOWED_VARIANTS:
            return None, [], None
        speed        = game_data.get("speed", "")
        if speed not in ALLOWED_SPEEDS:
            return None, [], None

        rated        = bool(game_data.get("rated"))
        status       = game_data.get("status", "")
        winner       = game_data.get("winner", "")   # "white" | "black" | ""

        opening      = game_data.get("opening") or {}
        opening_eco  = opening.get("eco", "")
        opening_name = opening.get("name", "")
        opening_ply  = opening.get("ply", "")

        # Target result
        if not winner:
            target_result, target_score = "draw", 0.5
        elif (winner == "white") == (target_color == chess.WHITE):
            target_result, target_score = "win", 1.0
        else:
            target_result, target_score = "loss", 0.0

        target_color_str   = "white" if target_color == chess.WHITE else "black"

        # Clocks
        clocks        = game_data.get("clocks") if isinstance(game_data.get("clocks"), list) else None
        clock_initial = None
        if isinstance(game_data.get("clock"), dict):
            try:
                clock_initial = int(game_data["clock"]["initial"]) * 100
            except Exception:
                pass

        # Ply loop
        board   = pgn_game.board()
        ply_idx = 0   # 0-based index into analysis[]

        # Summary accumulators
        target_cp_losses: List[int]        = []
        phase_cp: dict                     = {"opening": [], "middlegame": [], "endgame": []}
        quality_counts                     = {"Good": 0, "Inaccuracy": 0, "Mistake": 0, "Blunder": 0}

        for node in pgn_game.mainline():
            move       = node.move
            side       = board.turn          # who is moving
            ply        = ply_idx + 1         # 1-based ply number

            is_target  = (side == target_color)

            # Need two evals for cp_loss
            has_eval = ply_idx < len(analysis) and ply_idx + 1 < len(analysis)

            if has_eval:
                entry_before = analysis[ply_idx]
                entry_after  = analysis[ply_idx + 1]

                fen_before       = board.fen()
                phase            = infer_phase(board)

                # Evals from White POV
                cp_before_white  = extract_cp(entry_before)
                cp_after_white   = extract_cp(entry_after)

                # Flip if target is Black
                if target_color == chess.WHITE:
                    cp_before_target = cp_before_white
                    cp_after_target  = cp_after_white
                else:
                    cp_before_target = -cp_before_white
                    cp_after_target  = -cp_after_white

                # cp_loss only matters on target moves
                cp_loss   = None
                quality   = ""
                if is_target:
                    cp_loss = cp_before_target - cp_after_target
                    quality = classify_move(max(0, int(cp_loss)))
                    quality_counts[quality] += 1
                    target_cp_losses.append(int(cp_loss))
                    phase_cp[phase].append(int(cp_loss))

                # Move flags
                is_capture   = board.is_capture(move)
                is_castle    = board.is_castling(move)
                is_promotion = move.promotion is not None
                promo_piece  = {chess.QUEEN: "Q", chess.ROOK: "R",
                                chess.BISHOP: "B", chess.KNIGHT: "N"}.get(move.promotion, "") \
                               if is_promotion else ""
                try:
                    is_check = board.gives_check(move)
                except Exception:
                    is_check = False

                piece       = board.piece_at(move.from_square)
                ptype       = piece_name(piece) if piece else "Unknown"
                try:
                    move_san = board.san(move)
                except Exception:
                    move_san = move.uci()

                b_move_san = best_move_san(entry_before, board)
                b_move_uci = entry_before.get("best", "") if isinstance(entry_before, dict) else ""

                # Clock info
                clk_before = clk_after = time_spent = ""
                if clocks and ply - 1 < len(clocks):
                    try:
                        clk_after = int(clocks[ply - 1])
                        prev_idx  = ply - 3
                        clk_before = int(clocks[prev_idx]) if prev_idx >= 0 \
                                     else (clock_initial if clock_initial is not None else "")
                        if isinstance(clk_before, int):
                            time_spent = max(0, clk_before - clk_after)
                    except Exception:
                        pass

                move_rows.append({
                    # IDs
                    "game_id":          game_id,
                    "ply":              ply,
                    "player_color":     "white" if side == chess.WHITE else "black",
                    "is_target_move":   is_target,
                    # Position
                    "fen_before":       fen_before,
                    "phase":            phase,
                    # Move
                    "move_san":         move_san,
                    "move_uci":         move.uci(),
                    "piece_type":       ptype,
                    "is_capture":       is_capture,
                    "is_check":         is_check,
                    "is_castle":        is_castle,
                    "is_promotion":     is_promotion,
                    "promotion_piece":  promo_piece,
                    # Engine
                    "best_move_san":    b_move_san,
                    "best_move_uci":    b_move_uci,
                    "eval_white_before": cp_before_white,
                    "eval_white_after":  cp_after_white,
                    "cp_loss":          cp_loss if cp_loss is not None else "",
                    "move_quality":     quality,
                    # Clocks
                    "clock_before_cs":  clk_before,
                    "clock_after_cs":   clk_after,
                    "time_spent_cs":    time_spent,
                })

            board.push(move)
            ply_idx += 1

        # Game row
        game_row = {
            "game_id":        game_id,
            "date_utc":       date_utc,
            "time_control":   time_control,
            "speed":          speed,
            "rated":          rated,
            "status":         status,
            "ply_count":      ply_idx,
            # players
            "white_name":     white_name,
            "black_name":     black_name,
            "white_elo":      white_elo  if white_elo  is not None else "",
            "black_elo":      black_elo  if black_elo  is not None else "",
            "white_elo_diff": white_diff if white_diff is not None else "",
            "black_elo_diff": black_diff if black_diff is not None else "",
            # opening
            "opening_eco":    opening_eco,
            "opening_name":   opening_name,
            "opening_ply":    opening_ply,
            # target POV
            "target_name":    target_player,
            "target_color":   target_color_str,
            "opponent_name":  opponent_name,
            "target_elo":     target_elo    if target_elo    is not None else "",
            "opponent_elo":   opponent_elo  if opponent_elo  is not None else "",
            "target_result":  target_result,
            "target_score":   target_score,
        }

        # Summary row
        summary_row = {
            "target_name":              target_player,
            "game_id":                  game_id,
            "target_color":             target_color_str,
            "speed":                    speed,
            "time_control":             time_control,
            "rated":                    rated,
            "target_elo":               target_elo   if target_elo   is not None else "",
            "opponent_elo":             opponent_elo if opponent_elo is not None else "",
            "target_result":            target_result,
            "target_score":             target_score,
            # aggregate quality
            "total_moves":              len(target_cp_losses),
            "mean_cp_loss":             round(_safe_mean(target_cp_losses),   2),
            "median_cp_loss":           round(_safe_median(target_cp_losses), 2),
            "p90_cp_loss":              round(_safe_p90(target_cp_losses),    2),
            "good_moves":               quality_counts["Good"],
            "inaccuracies":             quality_counts["Inaccuracy"],
            "mistakes":                 quality_counts["Mistake"],
            "blunders":                 quality_counts["Blunder"],
            # per-phase averages
            "opening_mean_cp_loss":     round(_safe_mean(phase_cp["opening"]),     2),
            "middlegame_mean_cp_loss":  round(_safe_mean(phase_cp["middlegame"]),  2),
            "endgame_mean_cp_loss":     round(_safe_mean(phase_cp["endgame"]),     2),
        }

        return game_row, move_rows, summary_row

    except Exception as e:
        logger.error(f"parse_game({game_data.get('id', '?')}): {e}")
        return None, [], None
    
def build_player_row(username: str, elo: int, elo_bucket: str,
                     player_summaries: List[dict]) -> dict:
    """Aggregate per-game summaries into one player row."""
    if not player_summaries:
        return {}

    games_collected    = len(player_summaries)
    mean_cp_losses     = [s["mean_cp_loss"]   for s in player_summaries if not math.isnan(s["mean_cp_loss"])]
    median_cp_losses   = [s["median_cp_loss"] for s in player_summaries if not math.isnan(s["median_cp_loss"])]
    total_moves        = sum(s["total_moves"]  for s in player_summaries)
    total_blunders     = sum(s["blunders"]     for s in player_summaries)
    total_mistakes     = sum(s["mistakes"]     for s in player_summaries)
    total_inaccuracies = sum(s["inaccuracies"] for s in player_summaries)
    scores             = [s["target_score"]    for s in player_summaries]

    return {
        "username":            username,
        "elo":                 elo,
        "elo_bucket":          elo_bucket,
        "games_collected":     games_collected,
        "mean_cp_loss":        round(_safe_mean(mean_cp_losses),   2),
        "median_cp_loss":      round(_safe_mean(median_cp_losses), 2),
        "blunder_rate":        round(total_blunders     / total_moves, 4) if total_moves else 0,
        "mistake_rate":        round(total_mistakes     / total_moves, 4) if total_moves else 0,
        "inaccuracy_rate":     round(total_inaccuracies / total_moves, 4) if total_moves else 0,
        "avg_blunders_per_game": round(total_blunders  / games_collected, 2),
        "avg_mistakes_per_game": round(total_mistakes  / games_collected, 2),
        "win_rate":            round(_safe_mean(scores), 3),
    }