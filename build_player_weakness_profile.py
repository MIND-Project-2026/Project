#!/usr/bin/env python3
"""Build player weakness profiles from collected game data."""

from __future__ import annotations

import argparse
import csv
import os
import statistics
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_GAMES = "output/games.csv"
DEFAULT_MOVES = "output/moves.csv"
DEFAULT_SUMMARY = "output/summary.csv"
DEFAULT_OUTPUT = "output/player_weakness_profiles.csv"
PHASES = ["opening", "middlegame", "endgame"]
PIECES = ["Pawn", "Knight", "Bishop", "Rook", "Queen", "King"]
TACTICS = ["capture", "check", "castle", "promotion", "quiet"]
QUALITY_LEVELS = ["Good", "Inaccuracy", "Mistake", "Blunder"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build player weakness profiles from games/moves/summary CSVs")
    parser.add_argument("--games-csv", default=DEFAULT_GAMES, help="Path to games.csv")
    parser.add_argument("--moves-csv", default=DEFAULT_MOVES, help="Path to moves.csv")
    parser.add_argument("--summary-csv", default=DEFAULT_SUMMARY, help="Optional path to summary.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--username", default="", help="Optional single username to profile")
    parser.add_argument(
        "--time-trouble-threshold-cs",
        type=int,
        default=3000,
        help="Clock-before threshold in centiseconds for time trouble (default: 3000 = 30s)",
    )
    parser.add_argument(
        "--min-category-moves",
        type=int,
        default=8,
        help="Minimum moves before a category gets a non-baseline weakness score (default: 8)",
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


def _safe_rate(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def _safe_mean(values: Sequence[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _safe_median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _safe_p90(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1)))))
    return float(ordered[idx])


def _quality_bucket(move_quality: str) -> str:
    q = (move_quality or "").strip()
    return q if q in QUALITY_LEVELS else ""


def _tactic_bucket(row: Dict[str, str]) -> str:
    if _normalize_bool(row.get("is_promotion")):
        return "promotion"
    if _normalize_bool(row.get("is_check")):
        return "check"
    if _normalize_bool(row.get("is_capture")):
        return "capture"
    if _normalize_bool(row.get("is_castle")):
        return "castle"
    return "quiet"


def _quality_bonus(move_quality: str) -> float:
    return {
        "Good": 0.0,
        "Inaccuracy": 0.35,
        "Mistake": 0.75,
        "Blunder": 1.25,
    }.get((move_quality or "").strip(), 0.0)


def _weakness_score(
    count: int,
    mean_cp_loss: float,
    blunder_rate: float,
    overall_mean_cp_loss: float,
    overall_blunder_rate: float,
    min_count: int,
) -> float:
    if count < min_count:
        return 1.0

    mean_ratio = mean_cp_loss / overall_mean_cp_loss if overall_mean_cp_loss > 0 else 1.0
    if overall_blunder_rate > 0:
        blunder_ratio = blunder_rate / overall_blunder_rate
    else:
        blunder_ratio = 1.0 + (2.5 * blunder_rate)

    score = 0.65 * mean_ratio + 0.35 * blunder_ratio
    return max(0.3, min(3.0, score))


def _difficulty_bucket(avg_target_elo: Optional[float], blunder_rate: float, move_count: int) -> str:
    if move_count < 60 or avg_target_elo is None:
        return "medium"
    if avg_target_elo < 1300 or blunder_rate >= 0.09:
        return "easy"
    if avg_target_elo < 1700 or blunder_rate >= 0.05:
        return "medium"
    if avg_target_elo < 2100 or blunder_rate >= 0.02:
        return "hard"
    return "expert"


def _profile_quality(move_count: int, game_count: int) -> str:
    if move_count >= 800 and game_count >= 15:
        return "high"
    if move_count >= 250 and game_count >= 8:
        return "medium"
    return "low"


def _top_key(score_map: Dict[str, float]) -> str:
    if not score_map:
        return ""
    return max(score_map.items(), key=lambda kv: kv[1])[0]


def _build_player_game_index(games_rows: Iterable[Dict[str, str]], username_filter: str = "") -> Dict[str, Dict[str, Dict[str, str]]]:
    by_user: Dict[str, Dict[str, Dict[str, str]]] = defaultdict(dict)
    wanted = username_filter.strip().lower()
    for row in games_rows:
        username = (row.get("target_name") or "").strip()
        if not username:
            continue
        if wanted and username.lower() != wanted:
            continue
        game_id = (row.get("game_id") or "").strip()
        if not game_id:
            continue
        by_user[username][game_id] = row
    return by_user


def _build_summary_index(summary_rows: Iterable[Dict[str, str]], username_filter: str = "") -> Dict[str, List[Dict[str, str]]]:
    by_user: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    wanted = username_filter.strip().lower()
    for row in summary_rows:
        username = (row.get("target_name") or "").strip()
        if not username:
            continue
        if wanted and username.lower() != wanted:
            continue
        by_user[username].append(row)
    return by_user


def _dedup_target_moves_for_user(
    moves_rows: Iterable[Dict[str, str]],
    user_games: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    if not user_games:
        return []

    color_by_game = {
        game_id: (row.get("target_color") or "").strip().lower()
        for game_id, row in user_games.items()
    }

    dedup: Dict[Tuple[str, int], Dict[str, str]] = {}
    for row in moves_rows:
        game_id = (row.get("game_id") or "").strip()
        if game_id not in color_by_game:
            continue
        ply = _safe_int(row.get("ply"))
        if ply is None:
            continue
        player_color = (row.get("player_color") or "").strip().lower()
        if player_color != color_by_game[game_id]:
            continue
        key = (game_id, ply)
        if key not in dedup:
            dedup[key] = row

    return sorted(dedup.values(), key=lambda r: ((r.get("game_id") or ""), _safe_int(r.get("ply"), -1) or -1))


def build_profile_for_user(
    username: str,
    user_games: Dict[str, Dict[str, str]],
    user_moves: List[Dict[str, str]],
    user_summaries: List[Dict[str, str]],
    time_trouble_threshold_cs: int,
    min_category_moves: int,
) -> Dict[str, object]:
    cp_losses: List[float] = []
    target_elos: List[float] = []

    quality_counts: Counter[str] = Counter()
    phase_moves: Dict[str, List[float]] = {phase: [] for phase in PHASES}
    phase_blunders: Dict[str, int] = {phase: 0 for phase in PHASES}
    piece_moves: Dict[str, List[float]] = {piece: [] for piece in PIECES}
    piece_blunders: Dict[str, int] = {piece: 0 for piece in PIECES}
    tactic_moves: Dict[str, List[float]] = {name: [] for name in TACTICS}
    tactic_blunders: Dict[str, int] = {name: 0 for name in TACTICS}

    low_time_cp: List[float] = []
    low_time_blunders = 0
    low_time_count = 0
    normal_time_cp: List[float] = []
    normal_time_blunders = 0
    normal_time_count = 0

    opening_by_game: Counter[str] = Counter()
    opening_cp_losses: Dict[str, List[float]] = defaultdict(list)

    opening_name_by_game = {
        game_id: (game_row.get("opening_name") or "").strip()
        for game_id, game_row in user_games.items()
    }

    for game_row in user_games.values():
        elo = _safe_float(game_row.get("target_elo"))
        if elo is not None:
            target_elos.append(elo)
        opening_name = (game_row.get("opening_name") or "").strip()
        if opening_name:
            opening_by_game[opening_name] += 1

    for row in user_summaries:
        elo = _safe_float(row.get("target_elo"))
        if elo is not None:
            target_elos.append(elo)

    for row in user_moves:
        cp_loss = _safe_float(row.get("cp_loss"))
        if cp_loss is None:
            continue
        cp = max(0.0, float(cp_loss))
        cp_losses.append(cp)

        quality = _quality_bucket(row.get("move_quality") or "")
        if quality:
            quality_counts[quality] += 1

        phase = (row.get("phase") or "").strip()
        if phase in phase_moves:
            phase_moves[phase].append(cp)
            if quality == "Blunder":
                phase_blunders[phase] += 1

        piece = (row.get("piece_type") or "").strip()
        if piece in piece_moves:
            piece_moves[piece].append(cp)
            if quality == "Blunder":
                piece_blunders[piece] += 1

        tactic = _tactic_bucket(row)
        tactic_moves[tactic].append(cp)
        if quality == "Blunder":
            tactic_blunders[tactic] += 1

        clk_before = _safe_int(row.get("clock_before_cs"))
        if clk_before is not None and clk_before <= time_trouble_threshold_cs:
            low_time_count += 1
            low_time_cp.append(cp)
            if quality == "Blunder":
                low_time_blunders += 1
        else:
            normal_time_count += 1
            normal_time_cp.append(cp)
            if quality == "Blunder":
                normal_time_blunders += 1

        opening_name = opening_name_by_game.get((row.get("game_id") or "").strip(), "")
        if opening_name:
            opening_cp_losses[opening_name].append(cp)

    move_count = len(cp_losses)
    game_count = len(user_games)
    avg_target_elo = _safe_mean(target_elos) if target_elos else None
    mean_cp_loss = _safe_mean(cp_losses)
    median_cp_loss = _safe_median(cp_losses)
    p90_cp_loss = _safe_p90(cp_losses)
    blunder_rate = _safe_rate(quality_counts["Blunder"], move_count)
    mistake_rate = _safe_rate(quality_counts["Mistake"], move_count)
    inaccuracy_rate = _safe_rate(quality_counts["Inaccuracy"], move_count)
    good_rate = _safe_rate(quality_counts["Good"], move_count)

    row: Dict[str, object] = {
        "username": username,
        "games_count": game_count,
        "target_moves": move_count,
        "avg_target_elo": round(avg_target_elo, 2) if avg_target_elo is not None else "",
        "mean_cp_loss": round(mean_cp_loss, 2),
        "median_cp_loss": round(median_cp_loss, 2),
        "p90_cp_loss": round(p90_cp_loss, 2),
        "good_rate": round(good_rate, 4),
        "inaccuracy_rate": round(inaccuracy_rate, 4),
        "mistake_rate": round(mistake_rate, 4),
        "blunder_rate": round(blunder_rate, 4),
        "recommended_difficulty_bucket": _difficulty_bucket(avg_target_elo, blunder_rate, move_count),
        "profile_quality": _profile_quality(move_count, game_count),
        "favorite_opening": opening_by_game.most_common(1)[0][0] if opening_by_game else "",
    }

    phase_scores: Dict[str, float] = {}
    for phase in PHASES:
        values = phase_moves[phase]
        phase_mean = _safe_mean(values)
        phase_blunder_rate = _safe_rate(phase_blunders[phase], len(values))
        score = _weakness_score(
            count=len(values),
            mean_cp_loss=phase_mean,
            blunder_rate=phase_blunder_rate,
            overall_mean_cp_loss=mean_cp_loss,
            overall_blunder_rate=blunder_rate,
            min_count=min_category_moves,
        )
        phase_scores[phase] = score
        row[f"{phase}_moves"] = len(values)
        row[f"{phase}_mean_cp_loss"] = round(phase_mean, 2)
        row[f"{phase}_blunder_rate"] = round(phase_blunder_rate, 4)
        row[f"weakness_{phase}_score"] = round(score, 4)

    piece_scores: Dict[str, float] = {}
    for piece in PIECES:
        values = piece_moves[piece]
        piece_mean = _safe_mean(values)
        piece_blunder_rate = _safe_rate(piece_blunders[piece], len(values))
        piece_key = piece.lower()
        score = _weakness_score(
            count=len(values),
            mean_cp_loss=piece_mean,
            blunder_rate=piece_blunder_rate,
            overall_mean_cp_loss=mean_cp_loss,
            overall_blunder_rate=blunder_rate,
            min_count=min_category_moves,
        )
        piece_scores[piece_key] = score
        row[f"{piece_key}_moves"] = len(values)
        row[f"{piece_key}_mean_cp_loss"] = round(piece_mean, 2)
        row[f"{piece_key}_blunder_rate"] = round(piece_blunder_rate, 4)
        row[f"weakness_{piece_key}_score"] = round(score, 4)

    tactic_scores: Dict[str, float] = {}
    for tactic in TACTICS:
        values = tactic_moves[tactic]
        tactic_mean = _safe_mean(values)
        tactic_blunder_rate = _safe_rate(tactic_blunders[tactic], len(values))
        score = _weakness_score(
            count=len(values),
            mean_cp_loss=tactic_mean,
            blunder_rate=tactic_blunder_rate,
            overall_mean_cp_loss=mean_cp_loss,
            overall_blunder_rate=blunder_rate,
            min_count=min_category_moves,
        )
        tactic_scores[tactic] = score
        row[f"{tactic}_moves"] = len(values)
        row[f"{tactic}_mean_cp_loss"] = round(tactic_mean, 2)
        row[f"{tactic}_blunder_rate"] = round(tactic_blunder_rate, 4)
        row[f"weakness_{tactic}_score"] = round(score, 4)

    low_time_mean = _safe_mean(low_time_cp)
    low_time_blunder_rate = _safe_rate(low_time_blunders, low_time_count)
    normal_time_mean = _safe_mean(normal_time_cp)
    normal_time_blunder_rate = _safe_rate(normal_time_blunders, normal_time_count)
    time_trouble_score = _weakness_score(
        count=low_time_count,
        mean_cp_loss=low_time_mean if low_time_count else mean_cp_loss,
        blunder_rate=low_time_blunder_rate if low_time_count else blunder_rate,
        overall_mean_cp_loss=normal_time_mean if normal_time_count else mean_cp_loss,
        overall_blunder_rate=normal_time_blunder_rate if normal_time_count else blunder_rate,
        min_count=min_category_moves,
    )
    row["low_time_moves"] = low_time_count
    row["low_time_mean_cp_loss"] = round(low_time_mean, 2)
    row["low_time_blunder_rate"] = round(low_time_blunder_rate, 4)
    row["normal_time_moves"] = normal_time_count
    row["normal_time_mean_cp_loss"] = round(normal_time_mean, 2)
    row["normal_time_blunder_rate"] = round(normal_time_blunder_rate, 4)
    row["time_trouble_weakness_score"] = round(time_trouble_score, 4)

    opening_weak = []
    for opening_name, values in opening_cp_losses.items():
        opening_weak.append((opening_name, _safe_mean(values), len(values)))
    opening_weak.sort(key=lambda x: (x[1], x[2]), reverse=True)
    row["weakest_opening"] = opening_weak[0][0] if opening_weak else ""
    row["weakest_opening_mean_cp_loss"] = round(opening_weak[0][1], 2) if opening_weak else 0.0

    row["primary_weak_phase"] = _top_key(phase_scores)
    row["primary_weak_piece"] = _top_key(piece_scores)
    row["primary_weak_tactic"] = _top_key(tactic_scores)

    return row


def collect_profiles(
    games_rows: List[Dict[str, str]],
    moves_rows: List[Dict[str, str]],
    summary_rows: List[Dict[str, str]],
    username_filter: str,
    time_trouble_threshold_cs: int,
    min_category_moves: int,
) -> List[Dict[str, object]]:
    games_by_user = _build_player_game_index(games_rows, username_filter)
    summaries_by_user = _build_summary_index(summary_rows, username_filter)

    profiles: List[Dict[str, object]] = []
    for username in sorted(games_by_user.keys()):
        user_games = games_by_user[username]
        user_moves = _dedup_target_moves_for_user(moves_rows, user_games)
        user_summaries = summaries_by_user.get(username, [])
        if not user_games:
            continue
        profiles.append(
            build_profile_for_user(
                username=username,
                user_games=user_games,
                user_moves=user_moves,
                user_summaries=user_summaries,
                time_trouble_threshold_cs=time_trouble_threshold_cs,
                min_category_moves=min_category_moves,
            )
        )
    return profiles


def _collect_fields(rows: List[Dict[str, object]]) -> List[str]:
    preferred = [
        "username",
        "games_count",
        "target_moves",
        "avg_target_elo",
        "mean_cp_loss",
        "median_cp_loss",
        "p90_cp_loss",
        "good_rate",
        "inaccuracy_rate",
        "mistake_rate",
        "blunder_rate",
        "recommended_difficulty_bucket",
        "profile_quality",
        "favorite_opening",
        "weakest_opening",
        "weakest_opening_mean_cp_loss",
        "primary_weak_phase",
        "primary_weak_piece",
        "primary_weak_tactic",
        "time_trouble_weakness_score",
    ]
    all_fields = set()
    for row in rows:
        all_fields.update(row.keys())
    ordered = [f for f in preferred if f in all_fields]
    ordered.extend(sorted(all_fields - set(ordered)))
    return ordered


def write_csv(rows: List[Dict[str, object]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fields = _collect_fields(rows)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: List[Dict[str, object]]) -> None:
    print("Player weakness profiles")
    print("-" * 60)
    print(f"Profiles built: {len(rows):,}")
    if not rows:
        return
    quality = Counter(str(r.get("profile_quality") or "") for r in rows)
    difficulty = Counter(str(r.get("recommended_difficulty_bucket") or "") for r in rows)
    print()
    print("By profile quality:")
    for key, value in quality.most_common():
        print(f"  {key:<12} {value:>8,}")
    print()
    print("Recommended difficulty:")
    for key, value in difficulty.most_common():
        print(f"  {key:<12} {value:>8,}")


def main() -> None:
    args = parse_args()
    games_rows = _load_csv(args.games_csv)
    moves_rows = _load_csv(args.moves_csv)
    summary_rows = _load_csv(args.summary_csv) if args.summary_csv and os.path.exists(args.summary_csv) else []

    rows = collect_profiles(
        games_rows=games_rows,
        moves_rows=moves_rows,
        summary_rows=summary_rows,
        username_filter=args.username,
        time_trouble_threshold_cs=args.time_trouble_threshold_cs,
        min_category_moves=args.min_category_moves,
    )

    write_csv(rows, args.output)
    print_summary(rows)
    print()
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
