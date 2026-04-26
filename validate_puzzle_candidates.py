#!/usr/bin/env python3
"""Validate puzzle candidates with Stockfish."""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

import chess
import chess.engine


DEFAULT_INPUT = "output/puzzle_candidates.csv"
DEFAULT_OUTPUT = "output/puzzles_validated.csv"
DEFAULT_ENGINE = "stockfish"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate puzzle candidates with Stockfish")
    parser.add_argument("--candidates-csv", default=DEFAULT_INPUT, help="Path to puzzle_candidates.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path")
    parser.add_argument("--engine-path", default=DEFAULT_ENGINE, help="Path to Stockfish binary")
    parser.add_argument("--depth", type=int, default=16, help="Engine search depth (default: 16)")
    parser.add_argument("--threads", type=int, default=1, help="Engine Threads option (default: 1)")
    parser.add_argument("--hash-mb", type=int, default=256, help="Engine Hash in MB (default: 256)")
    parser.add_argument("--multipv", type=int, default=2, help="How many candidate lines to request (default: 2)")
    parser.add_argument(
        "--mate-score",
        type=int,
        default=100000,
        help="Synthetic centipawn value used to convert mate scores (default: 100000)",
    )
    parser.add_argument(
        "--min-gap-cp",
        type=int,
        default=120,
        help="Minimum best-vs-second gap for non-mate puzzles (default: 120)",
    )
    parser.add_argument(
        "--min-winning-cp",
        type=int,
        default=150,
        help="Minimum best-line eval for non-mate puzzles (default: 150)",
    )
    parser.add_argument(
        "--max-mate-plies",
        type=int,
        default=8,
        help="Accept mate puzzles only if mate distance is within this many plies (default: 8)",
    )
    parser.add_argument(
        "--require-forcing",
        action="store_true",
        help="Require the best move SAN to look forcing (check, mate, capture, promotion)",
    )
    parser.add_argument(
        "--only-valid",
        action="store_true",
        help="Write only rows accepted by the validation rule",
    )
    parser.add_argument(
        "--max-input",
        type=int,
        default=0,
        help="Validate at most this many rows (0 = all)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=100,
        help="Print progress every N rows (default: 100)",
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


def _score_to_parts(score: chess.engine.PovScore, turn: chess.Color, mate_score: int) -> Tuple[Optional[int], Optional[int]]:
    """Return (cp, mate) from side-to-move POV."""
    pov = score.pov(turn)
    mate = pov.mate()
    if mate is not None:
        # Map mate scores into a big cp range.
        cp = mate_score - abs(mate)
        if mate < 0:
            cp = -cp
        return cp, int(mate)

    cp = pov.score(mate_score=mate_score)
    return (int(cp) if cp is not None else None), None


def _pv_to_text(board: chess.Board, pv: List[chess.Move]) -> Tuple[str, str]:
    if not pv:
        return "", ""

    uci_line = " ".join(move.uci() for move in pv)

    san_board = board.copy(stack=False)
    san_parts: List[str] = []
    for move in pv:
        try:
            san_parts.append(san_board.san(move))
            san_board.push(move)
        except Exception:
            san_parts.append(move.uci())
            try:
                san_board.push(move)
            except Exception:
                break

    return uci_line, " ".join(san_parts)


def _move_to_san(board: chess.Board, move: Optional[chess.Move]) -> str:
    if move is None:
        return ""
    try:
        return board.san(move)
    except Exception:
        return move.uci()


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


def _guess_theme(best_san: str, phase: str, mate: Optional[int]) -> str:
    tags = _solution_tags(best_san)
    if mate is not None and mate > 0:
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


def _coalesce(*values: object) -> str:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


def analyse_position(
    engine: chess.engine.SimpleEngine,
    row: Dict[str, str],
    depth: int,
    multipv: int,
    mate_score: int,
) -> Dict[str, object]:
    fen = (row.get("fen") or "").strip()
    if not fen:
        return {
            "analysis_error": "missing_fen",
        }

    try:
        board = chess.Board(fen)
    except Exception as exc:
        return {
            "analysis_error": f"invalid_fen: {exc}",
        }

    try:
        info = engine.analyse(
            board,
            chess.engine.Limit(depth=depth),
            multipv=max(1, multipv),
        )
    except Exception as exc:
        return {
            "analysis_error": f"engine_error: {exc}",
        }

    lines = info if isinstance(info, list) else [info]
    if not lines:
        return {
            "analysis_error": "no_engine_lines",
        }

    first = lines[0]
    best_pv = first.get("pv") or []
    best_move = best_pv[0] if best_pv else None
    best_move_uci = best_move.uci() if best_move is not None else ""
    best_move_san = _move_to_san(board, best_move)
    best_pv_uci, best_pv_san = _pv_to_text(board, best_pv)
    best_cp, best_mate = _score_to_parts(first["score"], board.turn, mate_score)

    second_move_uci = ""
    second_move_san = ""
    second_pv_uci = ""
    second_pv_san = ""
    second_cp = None
    second_mate = None

    if len(lines) >= 2:
        second = lines[1]
        second_pv = second.get("pv") or []
        second_move = second_pv[0] if second_pv else None
        second_move_uci = second_move.uci() if second_move is not None else ""
        second_move_san = _move_to_san(board, second_move)
        second_pv_uci, second_pv_san = _pv_to_text(board, second_pv)
        second_cp, second_mate = _score_to_parts(second["score"], board.turn, mate_score)

    best_vs_second_gap = None
    if best_cp is not None and second_cp is not None:
        best_vs_second_gap = best_cp - second_cp

    fallback_solution_uci = _coalesce(row.get("primary_solution_uci"), row.get("solution_uci"), row.get("fallback_reply_uci"))
    fallback_solution_san = _coalesce(row.get("primary_solution_san"), row.get("solution_san"), row.get("fallback_reply_san"))
    engine_matches_existing = False
    if fallback_solution_uci and best_move_uci:
        engine_matches_existing = best_move_uci == fallback_solution_uci

    phase = (row.get("phase") or "").strip()
    engine_tags = _solution_tags(best_move_san)
    theme = _guess_theme(best_move_san, phase, best_mate)

    return {
        "analysis_error": "",
        "engine_best_move_uci": best_move_uci,
        "engine_best_move_san": best_move_san,
        "engine_best_pv_uci": best_pv_uci,
        "engine_best_pv_san": best_pv_san,
        "engine_best_eval_cp": best_cp if best_cp is not None else "",
        "engine_best_mate": best_mate if best_mate is not None else "",
        "engine_second_move_uci": second_move_uci,
        "engine_second_move_san": second_move_san,
        "engine_second_pv_uci": second_pv_uci,
        "engine_second_pv_san": second_pv_san,
        "engine_second_eval_cp": second_cp if second_cp is not None else "",
        "engine_second_mate": second_mate if second_mate is not None else "",
        "best_vs_second_gap_cp": best_vs_second_gap if best_vs_second_gap is not None else "",
        "engine_solution_tags": "|".join(engine_tags),
        "engine_theme_guess": theme,
        "engine_matches_existing_solution": engine_matches_existing,
    }


def is_valid_puzzle(
    analysis: Dict[str, object],
    min_gap_cp: int,
    min_winning_cp: int,
    max_mate_plies: int,
    require_forcing: bool,
) -> Tuple[bool, str]:
    error = str(analysis.get("analysis_error") or "")
    if error:
        return False, error

    best_san = str(analysis.get("engine_best_move_san") or "")
    best_cp = _safe_int(analysis.get("engine_best_eval_cp"))
    best_mate = _safe_int(analysis.get("engine_best_mate"))
    gap = _safe_int(analysis.get("best_vs_second_gap_cp"))

    forcing = _looks_forcing(best_san)

    if require_forcing and not forcing:
        return False, "non_forcing_best_move"

    if best_mate is not None and best_mate > 0:
        if best_mate <= max_mate_plies:
            return True, "mate"
        return False, "mate_too_long"

    if best_cp is None:
        return False, "missing_eval"

    if gap is None:
        if forcing and best_cp >= min_winning_cp:
            return True, "winning_forcing_move_no_second_line"
        return False, "missing_second_line"

    if forcing and gap >= min_gap_cp:
        return True, "forcing_clear_best"

    if gap >= min_gap_cp and best_cp >= min_winning_cp:
        return True, "clear_best_move"

    if forcing and best_cp >= (min_winning_cp + 100):
        return True, "strong_forcing_move"

    return False, "insufficient_gap_or_advantage"


def validate_candidates(
    candidate_rows: List[Dict[str, str]],
    engine_path: str,
    depth: int,
    threads: int,
    hash_mb: int,
    multipv: int,
    mate_score: int,
    min_gap_cp: int,
    min_winning_cp: int,
    max_mate_plies: int,
    require_forcing: bool,
    max_input: int,
    progress_every: int,
) -> List[Dict[str, object]]:
    rows = candidate_rows[:max_input] if max_input > 0 else candidate_rows
    results: List[Dict[str, object]] = []

    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        try:
            engine.configure({"Threads": threads, "Hash": hash_mb})
        except Exception:
            # Some engines ignore these options.
            pass

        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            analysis = analyse_position(
                engine=engine,
                row=row,
                depth=depth,
                multipv=multipv,
                mate_score=mate_score,
            )
            keep, reason = is_valid_puzzle(
                analysis=analysis,
                min_gap_cp=min_gap_cp,
                min_winning_cp=min_winning_cp,
                max_mate_plies=max_mate_plies,
                require_forcing=require_forcing,
            )

            merged: Dict[str, object] = dict(row)
            merged.update(analysis)
            merged["is_valid_puzzle"] = keep
            merged["validation_reason"] = reason
            merged["validation_depth"] = depth
            merged["validation_multipv"] = multipv
            results.append(merged)

            if progress_every > 0 and (idx % progress_every == 0 or idx == total):
                print(f"Validated {idx:,}/{total:,}")

    return results


OUTPUT_FIELDS = [
    # Candidate fields
    "puzzle_id",
    "game_id",
    "trigger_ply",
    "puzzle_ply",
    "fen",
    "side_to_move",
    "has_engine_solution",
    "solution_uci",
    "solution_san",
    "fallback_reply_uci",
    "fallback_reply_san",
    "primary_solution_uci",
    "primary_solution_san",
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
    # Validation fields
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
]


def write_csv(rows: List[Dict[str, object]], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: List[Dict[str, object]]) -> None:
    total = len(rows)
    valid = sum(1 for r in rows if _normalize_bool(r.get("is_valid_puzzle")))
    invalid = total - valid
    reasons = Counter(str(r.get("validation_reason") or "") for r in rows)
    themes = Counter(str(r.get("engine_theme_guess") or "") for r in rows if _normalize_bool(r.get("is_valid_puzzle")))

    print("Validation summary")
    print("-" * 60)
    print(f"Total analysed: {total:,}")
    print(f"Accepted:       {valid:,}")
    print(f"Rejected:       {invalid:,}")
    print()

    if reasons:
        print("By validation reason:")
        for key, value in reasons.most_common():
            print(f"  {key:<30} {value:>8,}")
        print()

    if themes:
        print("Accepted by engine theme:")
        for key, value in themes.most_common():
            print(f"  {key:<30} {value:>8,}")


def main() -> None:
    args = parse_args()
    candidate_rows = _load_csv(args.candidates_csv)

    validated_rows = validate_candidates(
        candidate_rows=candidate_rows,
        engine_path=args.engine_path,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
        multipv=args.multipv,
        mate_score=args.mate_score,
        min_gap_cp=args.min_gap_cp,
        min_winning_cp=args.min_winning_cp,
        max_mate_plies=args.max_mate_plies,
        require_forcing=args.require_forcing,
        max_input=args.max_input,
        progress_every=args.progress_every,
    )

    rows_to_write = [r for r in validated_rows if _normalize_bool(r.get("is_valid_puzzle"))] if args.only_valid else validated_rows
    write_csv(rows_to_write, args.output)
    print_summary(validated_rows)
    print()
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
