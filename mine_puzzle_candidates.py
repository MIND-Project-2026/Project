#!/usr/bin/env python3
"""Mine puzzle candidates from moves.csv."""

from __future__ import annotations

import argparse
import csv
import math
import os
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple


DEFAULT_QUALITIES = ("Mistake", "Blunder")
DEFAULT_OUTPUT = "output/puzzle_candidates.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine puzzle candidates from moves.csv")
    parser.add_argument("--moves-csv", default="output/moves.csv", help="Path to moves.csv")
    parser.add_argument("--games-csv", default="output/games.csv", help="Optional path to games.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument(
        "--qualities",
        nargs="+",
        default=list(DEFAULT_QUALITIES),
        help="Trigger move qualities to mine from (default: Mistake Blunder)",
    )
    parser.add_argument(
        "--min-cp-loss",
        type=int,
        default=100,
        help="Minimum cp_loss on the triggering move (default: 100)",
    )
    parser.add_argument(
        "--require-solution",
        action="store_true",
        help="Keep only candidates whose solution SAN looks forcing (check, mate, capture, promotion)",
    )
    parser.add_argument(
        "--dedupe-fen-solution",
        action="store_true",
        help="Deduplicate exact (fen, solution_uci) pairs in output",
    )
    parser.add_argument(
        "--max-per-game",
        type=int,
        default=0,
        help="Maximum candidates to keep per game (0 = unlimited)",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=0,
        help="Maximum total candidates to write (0 = unlimited)",
    )
    return parser.parse_args()


# Small helpers


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
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        result = float(text)
        if math.isnan(result):
            return default
        return result
    except ValueError:
        return default



def _normalize_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}



def _load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))



def _solution_tags(solution_san: str) -> List[str]:
    tags: List[str] = []
    san = (solution_san or "").strip()
    if not san:
        return tags
    if "#" in san:
        tags.append("mate")
    if "+" in san:
        tags.append("check")
    if "x" in san:
        tags.append("capture")
    if "=" in san:
        tags.append("promotion")
    if san in {"O-O", "O-O-O"}:
        tags.append("castle")
    return tags



def _looks_forcing(solution_san: str) -> bool:
    return any(tag in {"mate", "check", "capture", "promotion"} for tag in _solution_tags(solution_san))



def _guess_theme(solution_san: str, phase: str) -> str:
    tags = _solution_tags(solution_san)
    if "mate" in tags:
        return "mate"
    if "promotion" in tags:
        return "promotion"
    if "check" in tags and "capture" in tags:
        return "tactical-check"
    if "check" in tags:
        return "check"
    if "capture" in tags:
        return "capture"
    if phase == "endgame":
        return "endgame-technique"
    return "improvement"


# Core mining logic


def index_games(games_rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for row in games_rows:
        game_id = (row.get("game_id") or "").strip()
        if game_id:
            result[game_id] = row
    return result



def build_candidate(
    trigger_row: Dict[str, str],
    reply_row: Dict[str, str],
    game_row: Optional[Dict[str, str]],
    puzzle_id: int,
) -> Optional[Dict[str, object]]:
    fen = (reply_row.get("fen_before") or "").strip()
    solution_uci = (reply_row.get("best_move_uci") or "").strip()
    solution_san = (reply_row.get("best_move_san") or "").strip()

    if not fen or not solution_uci:
        return None

    trigger_cp_loss = _safe_int(trigger_row.get("cp_loss"))
    trigger_eval_before = _safe_int(trigger_row.get("eval_white_before"))
    trigger_eval_after = _safe_int(trigger_row.get("eval_white_after"))
    reply_eval_before = _safe_int(reply_row.get("eval_white_before"))

    white_elo = _safe_int(game_row.get("white_elo")) if game_row else None
    black_elo = _safe_int(game_row.get("black_elo")) if game_row else None
    avg_elo = None
    if white_elo is not None and black_elo is not None:
        avg_elo = round((white_elo + black_elo) / 2)

    solution_tags = _solution_tags(solution_san)
    theme = _guess_theme(solution_san, (reply_row.get("phase") or "").strip())

    return {
        "puzzle_id": f"cand_{puzzle_id:07d}",
        "game_id": (reply_row.get("game_id") or "").strip(),
        "trigger_ply": _safe_int(trigger_row.get("ply")),
        "puzzle_ply": _safe_int(reply_row.get("ply")),
        "fen": fen,
        "side_to_move": (reply_row.get("player_color") or "").strip(),
        "solution_uci": solution_uci,
        "solution_san": solution_san,
        "solution_tags": "|".join(solution_tags),
        "theme_guess": theme,
        "phase": (reply_row.get("phase") or "").strip(),
        "source_move_quality": (trigger_row.get("move_quality") or "").strip(),
        "source_cp_loss": trigger_cp_loss,
        "source_eval_white_before": trigger_eval_before,
        "source_eval_white_after": trigger_eval_after,
        "puzzle_eval_white_before": reply_eval_before,
        "source_move_uci": (trigger_row.get("move_uci") or "").strip(),
        "source_move_san": (trigger_row.get("move_san") or "").strip(),
        "source_player_color": (trigger_row.get("player_color") or "").strip(),
        "source_is_target_move": _normalize_bool(trigger_row.get("is_target_move")),
        "source_piece_type": (trigger_row.get("piece_type") or "").strip(),
        "source_is_capture": _normalize_bool(trigger_row.get("is_capture")),
        "source_is_check": _normalize_bool(trigger_row.get("is_check")),
        "source_is_castle": _normalize_bool(trigger_row.get("is_castle")),
        "source_is_promotion": _normalize_bool(trigger_row.get("is_promotion")),
        "date_utc": (game_row.get("date_utc") or "").strip() if game_row else "",
        "speed": (game_row.get("speed") or "").strip() if game_row else "",
        "time_control": (game_row.get("time_control") or "").strip() if game_row else "",
        "rated": (game_row.get("rated") or "").strip() if game_row else "",
        "opening_eco": (game_row.get("opening_eco") or "").strip() if game_row else "",
        "opening_name": (game_row.get("opening_name") or "").strip() if game_row else "",
        "white_name": (game_row.get("white_name") or "").strip() if game_row else "",
        "black_name": (game_row.get("black_name") or "").strip() if game_row else "",
        "white_elo": white_elo if white_elo is not None else "",
        "black_elo": black_elo if black_elo is not None else "",
        "avg_player_elo": avg_elo if avg_elo is not None else "",
        "target_name": (game_row.get("target_name") or "").strip() if game_row else "",
        "target_elo": _safe_int(game_row.get("target_elo")) if game_row else "",
        "opponent_name": (game_row.get("opponent_name") or "").strip() if game_row else "",
        "opponent_elo": _safe_int(game_row.get("opponent_elo")) if game_row else "",
        "target_result": (game_row.get("target_result") or "").strip() if game_row else "",
    }



def mine_candidates(
    moves_rows: List[Dict[str, str]],
    games_by_id: Dict[str, Dict[str, str]],
    qualities: Tuple[str, ...],
    min_cp_loss: int,
    require_solution: bool,
    dedupe_fen_solution: bool,
    max_per_game: int,
    max_output: int,
) -> List[Dict[str, object]]:
    rows = sorted(
        moves_rows,
        key=lambda r: ((r.get("game_id") or ""), _safe_int(r.get("ply"), -1)),
    )

    accepted: List[Dict[str, object]] = []
    seen_pairs = set()
    per_game_counts: Counter[str] = Counter()
    next_id = 1

    for i, trigger_row in enumerate(rows[:-1]):
        reply_row = rows[i + 1]

        trigger_game_id = (trigger_row.get("game_id") or "").strip()
        reply_game_id = (reply_row.get("game_id") or "").strip()
        if not trigger_game_id or trigger_game_id != reply_game_id:
            continue

        trigger_ply = _safe_int(trigger_row.get("ply"), -1)
        reply_ply = _safe_int(reply_row.get("ply"), -1)
        if reply_ply != trigger_ply + 1:
            continue

        quality = (trigger_row.get("move_quality") or "").strip()
        if quality not in qualities:
            continue

        cp_loss = _safe_int(trigger_row.get("cp_loss"), 0) or 0
        if cp_loss < min_cp_loss:
            continue

        if max_per_game > 0 and per_game_counts[trigger_game_id] >= max_per_game:
            continue

        solution_san = (reply_row.get("best_move_san") or "").strip()
        if require_solution and not _looks_forcing(solution_san):
            continue

        candidate = build_candidate(
            trigger_row=trigger_row,
            reply_row=reply_row,
            game_row=games_by_id.get(trigger_game_id),
            puzzle_id=next_id,
        )
        if candidate is None:
            continue

        if dedupe_fen_solution:
            key = (candidate["fen"], candidate["solution_uci"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

        accepted.append(candidate)
        per_game_counts[trigger_game_id] += 1
        next_id += 1

        if max_output > 0 and len(accepted) >= max_output:
            break

    return accepted


# Output


OUTPUT_FIELDS = [
    "puzzle_id",
    "game_id",
    "trigger_ply",
    "puzzle_ply",
    "fen",
    "side_to_move",
    "solution_uci",
    "solution_san",
    "solution_tags",
    "theme_guess",
    "phase",
    "source_move_quality",
    "source_cp_loss",
    "source_eval_white_before",
    "source_eval_white_after",
    "puzzle_eval_white_before",
    "source_move_uci",
    "source_move_san",
    "source_player_color",
    "source_is_target_move",
    "source_piece_type",
    "source_is_capture",
    "source_is_check",
    "source_is_castle",
    "source_is_promotion",
    "date_utc",
    "speed",
    "time_control",
    "rated",
    "opening_eco",
    "opening_name",
    "white_name",
    "black_name",
    "white_elo",
    "black_elo",
    "avg_player_elo",
    "target_name",
    "target_elo",
    "opponent_name",
    "opponent_elo",
    "target_result",
]



def write_candidates(rows: List[Dict[str, object]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)



def print_summary(rows: List[Dict[str, object]]) -> None:
    by_quality = Counter(str(r.get("source_move_quality") or "") for r in rows)
    by_theme = Counter(str(r.get("theme_guess") or "") for r in rows)
    by_phase = Counter(str(r.get("phase") or "") for r in rows)

    print("Mined puzzle candidates")
    print("-" * 60)
    print(f"Total: {len(rows):,}")
    print()

    if rows:
        print("By trigger quality:")
        for key, value in by_quality.most_common():
            print(f"  {key:<15} {value:>8,}")
        print()

        print("By theme guess:")
        for key, value in by_theme.most_common():
            print(f"  {key:<15} {value:>8,}")
        print()

        print("By phase:")
        for key, value in by_phase.most_common():
            print(f"  {key:<15} {value:>8,}")



def main() -> None:
    args = parse_args()

    moves_rows = _load_csv(args.moves_csv)
    games_by_id: Dict[str, Dict[str, str]] = {}
    if args.games_csv and os.path.exists(args.games_csv):
        games_by_id = index_games(_load_csv(args.games_csv))

    rows = mine_candidates(
        moves_rows=moves_rows,
        games_by_id=games_by_id,
        qualities=tuple(args.qualities),
        min_cp_loss=args.min_cp_loss,
        require_solution=args.require_solution,
        dedupe_fen_solution=args.dedupe_fen_solution,
        max_per_game=args.max_per_game,
        max_output=args.max_output,
    )

    write_candidates(rows, args.output)
    print_summary(rows)
    print()
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
