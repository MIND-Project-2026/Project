#!/usr/bin/env python3
"""Build puzzles_final.csv from validated puzzle candidates."""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from typing import Dict, List, Optional, Tuple


DEFAULT_INPUT = "output/puzzles_validated.csv"
DEFAULT_OUTPUT = "output/puzzles_final.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final puzzle dataset from validated puzzles")
    parser.add_argument("--validated-csv", default=DEFAULT_INPUT, help="Path to puzzles_validated.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument(
        "--keep-only-valid",
        action="store_true",
        default=True,
        help="Keep only rows where is_valid_puzzle is true (default: true)",
    )
    parser.add_argument(
        "--include-invalid",
        action="store_true",
        help="Override --keep-only-valid and keep all rows",
    )
    parser.add_argument(
        "--dedupe-key",
        choices=["fen_solution", "fen_only", "none"],
        default="fen_solution",
        help="Deduplication key (default: fen_solution)",
    )
    parser.add_argument(
        "--min-gap-cp",
        type=int,
        default=0,
        help="Optional post-filter: keep only rows with best_vs_second_gap_cp >= this value when available",
    )
    parser.add_argument(
        "--require-engine-move",
        action="store_true",
        help="Keep only rows with a non-empty engine_best_move_uci",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=0,
        help="Write at most this many rows (0 = unlimited)",
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


def _normalize_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _coalesce(*values: object) -> str:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


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


def _is_forcing(solution_san: str) -> bool:
    return any(tag in {"mate", "check", "capture", "promotion"} for tag in _solution_tags(solution_san))


def _final_theme(row: Dict[str, str], final_solution_san: str, phase: str) -> str:
    engine_theme = (row.get("engine_theme_guess") or "").strip()
    if engine_theme:
        return engine_theme

    tags = _solution_tags(final_solution_san)
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
    fallback = (row.get("theme_guess") or "").strip()
    return fallback if fallback else "improvement"


def _estimate_difficulty(row: Dict[str, str], final_solution_san: str) -> Tuple[int, str]:
    """Estimate puzzle difficulty score and bucket."""
    score = 0

    best_mate = _safe_int(row.get("engine_best_mate"))
    best_cp = _safe_int(row.get("engine_best_eval_cp"), 0) or 0
    gap = _safe_int(row.get("best_vs_second_gap_cp"), 0) or 0
    avg_elo = _safe_int(row.get("avg_player_elo"))
    phase = (row.get("phase") or "").strip()
    forcing = _is_forcing(final_solution_san)
    pv_san = (row.get("engine_best_pv_san") or "").strip()
    pv_len = len(pv_san.split()) if pv_san else 0

    if best_mate is not None and best_mate > 0:
        if best_mate <= 2:
            score += 20
        elif best_mate <= 4:
            score += 35
        elif best_mate <= 8:
            score += 50
        else:
            score += 65

    if gap >= 400:
        score += 10
    elif gap >= 250:
        score += 20
    elif gap >= 120:
        score += 30
    elif gap > 0:
        score += 40
    else:
        score += 50

    if abs(best_cp) >= 800:
        score += 5
    elif abs(best_cp) >= 300:
        score += 15
    else:
        score += 25

    if forcing:
        score -= 10
    else:
        score += 10

    if phase == "endgame":
        score += 10
    elif phase == "middlegame":
        score += 5

    if pv_len >= 8:
        score += 15
    elif pv_len >= 4:
        score += 8

    if avg_elo is not None:
        if avg_elo < 1400:
            score -= 10
        elif avg_elo < 1800:
            score += 0
        elif avg_elo < 2200:
            score += 10
        else:
            score += 20

    score = max(1, min(100, score))

    if score <= 25:
        bucket = "easy"
    elif score <= 50:
        bucket = "medium"
    elif score <= 75:
        bucket = "hard"
    else:
        bucket = "expert"

    return score, bucket


def _dedupe_key(row: Dict[str, object], mode: str) -> Optional[Tuple[str, ...]]:
    if mode == "none":
        return None

    fen = str(row.get("fen") or "").strip()
    solution = str(row.get("final_solution_uci") or "").strip()

    if mode == "fen_only":
        return (fen,)
    return (fen, solution)


FINAL_FIELDS = [
    "puzzle_id",
    "puzzle_key",
    "fen",
    "side_to_move",
    "final_solution_uci",
    "final_solution_san",
    "final_solution_source",
    "final_solution_tags",
    "final_theme",
    "difficulty_score",
    "difficulty_bucket",
    "is_forcing",
    "engine_best_move_uci",
    "engine_best_move_san",
    "engine_best_pv_uci",
    "engine_best_pv_san",
    "engine_best_eval_cp",
    "engine_best_mate",
    "engine_second_move_uci",
    "engine_second_move_san",
    "engine_second_pv_uci",
    "engine_second_pv_san",
    "engine_second_eval_cp",
    "engine_second_mate",
    "best_vs_second_gap_cp",
    "engine_solution_tags",
    "engine_theme_guess",
    "engine_matches_existing_solution",
    "is_valid_puzzle",
    "validation_reason",
    "validation_depth",
    "validation_multipv",
    "analysis_error",
    "game_id",
    "trigger_ply",
    "puzzle_ply",
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


def build_final_rows(
    validated_rows: List[Dict[str, str]],
    keep_only_valid: bool,
    dedupe_mode: str,
    min_gap_cp: int,
    require_engine_move: bool,
    max_output: int,
) -> List[Dict[str, object]]:
    accepted: List[Dict[str, object]] = []
    seen = set()

    for row in validated_rows:
        if keep_only_valid and not _normalize_bool(row.get("is_valid_puzzle")):
            continue

        if require_engine_move and not (row.get("engine_best_move_uci") or "").strip():
            continue

        if min_gap_cp > 0:
            gap = _safe_int(row.get("best_vs_second_gap_cp"))
            if gap is not None and gap < min_gap_cp:
                continue

        final_solution_uci = _coalesce(
            row.get("engine_best_move_uci"),
            row.get("primary_solution_uci"),
            row.get("solution_uci"),
            row.get("fallback_reply_uci"),
        )
        final_solution_san = _coalesce(
            row.get("engine_best_move_san"),
            row.get("primary_solution_san"),
            row.get("solution_san"),
            row.get("fallback_reply_san"),
        )
        final_solution_source = "engine" if (row.get("engine_best_move_uci") or "").strip() else "fallback"

        final_tags = _solution_tags(final_solution_san)
        phase = (row.get("phase") or "").strip()
        final_theme = _final_theme(row, final_solution_san, phase)
        difficulty_score, difficulty_bucket = _estimate_difficulty(row, final_solution_san)

        built: Dict[str, object] = dict(row)
        built["final_solution_uci"] = final_solution_uci
        built["final_solution_san"] = final_solution_san
        built["final_solution_source"] = final_solution_source
        built["final_solution_tags"] = "|".join(final_tags)
        built["final_theme"] = final_theme
        built["difficulty_score"] = difficulty_score
        built["difficulty_bucket"] = difficulty_bucket
        built["is_forcing"] = _is_forcing(final_solution_san)
        built["puzzle_key"] = f"{(row.get('fen') or '').strip()}||{final_solution_uci}"

        key = _dedupe_key(built, dedupe_mode)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)

        accepted.append(built)
        if max_output > 0 and len(accepted) >= max_output:
            break

    return accepted


def write_csv(rows: List[Dict[str, object]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FINAL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: List[Dict[str, object]]) -> None:
    total = len(rows)
    by_theme = Counter(str(r.get("final_theme") or "") for r in rows)
    by_difficulty = Counter(str(r.get("difficulty_bucket") or "") for r in rows)
    by_source = Counter(str(r.get("final_solution_source") or "") for r in rows)

    print("Final puzzle dataset summary")
    print("-" * 60)
    print(f"Total final puzzles: {total:,}")
    print()

    if by_theme:
        print("By theme:")
        for key, value in by_theme.most_common():
            print(f"  {key:<24} {value:>8,}")
        print()

    if by_difficulty:
        print("By difficulty:")
        for key, value in by_difficulty.most_common():
            print(f"  {key:<24} {value:>8,}")
        print()

    if by_source:
        print("By final solution source:")
        for key, value in by_source.most_common():
            print(f"  {key:<24} {value:>8,}")


def main() -> None:
    args = parse_args()
    validated_rows = _load_csv(args.validated_csv)

    final_rows = build_final_rows(
        validated_rows=validated_rows,
        keep_only_valid=(args.keep_only_valid and not args.include_invalid),
        dedupe_mode=args.dedupe_key,
        min_gap_cp=args.min_gap_cp,
        require_engine_move=args.require_engine_move,
        max_output=args.max_output,
    )

    write_csv(final_rows, args.output)
    print_summary(final_rows)
    print()
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
