# ── core/writer.py ────────────────────────────────────────────────────────────
# Writes collected rows to CSV files.
# Each function knows exactly which columns belong to which file.
# ─────────────────────────────────────────────────────────────────────────────

import csv
import os
import logging
from typing import List

logger = logging.getLogger(__name__)


# Column order for each output file
GAMES_FIELDS = [
    "game_id", "date_utc", "time_control", "speed", "rated",
    "status", "ply_count",
    "white_name", "black_name",
    "white_elo", "black_elo", "white_elo_diff", "black_elo_diff",
    "opening_eco", "opening_name", "opening_ply",
    "target_name", "target_color", "opponent_name",
    "target_elo", "opponent_elo", "target_result", "target_score",
]

MOVES_FIELDS = [
    "game_id", "ply", "player_color", "is_target_move",
    "fen_before", "phase",
    "move_san", "move_uci", "piece_type",
    "is_capture", "is_check", "is_castle", "is_promotion", "promotion_piece",
    "best_move_san", "best_move_uci",
    "eval_white_before", "eval_white_after",
    "cp_loss", "move_quality",
    "clock_before_cs", "clock_after_cs", "time_spent_cs",
]

SUMMARY_FIELDS = [
    "target_name", "game_id", "target_color",
    "speed", "time_control", "rated",
    "target_elo", "opponent_elo", "target_result", "target_score",
    "total_moves", "mean_cp_loss", "median_cp_loss", "p90_cp_loss",
    "good_moves", "inaccuracies", "mistakes", "blunders",
    "opening_mean_cp_loss", "middlegame_mean_cp_loss", "endgame_mean_cp_loss",
]

PLAYERS_FIELDS = [
    "username", "elo", "elo_bucket", "games_collected", "mean_cp_loss",
    "median_cp_loss", "blunder_rate", "mistake_rate", "inaccuracy_rate",
    "avg_blunders_per_game", "avg_mistakes_per_game", "win_rate"]

def write_players(rows: List[dict], path: str):
    """One row per player — identity, ELO bucket, aggregated quality stats."""
    _write_csv(rows, path, PLAYERS_FIELDS)
def _write_csv(rows: List[dict], path: str, fields: List[str]):
    if not rows:
        logger.warning(f"Nothing to write → {path}")
        return
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Saved {len(rows):,} rows → {path}")


def write_games(rows: List[dict], path: str):
    """One row per game — metadata, players, result, opening."""
    _write_csv(rows, path, GAMES_FIELDS)


def write_moves(rows: List[dict], path: str):
    """One row per ply — FEN, move, eval, cp_loss, clocks, tactical flags."""
    _write_csv(rows, path, MOVES_FIELDS)


def write_summary(rows: List[dict], path: str):
    """One row per (player × game) — aggregated quality stats by phase."""
    _write_csv(rows, path, SUMMARY_FIELDS)
