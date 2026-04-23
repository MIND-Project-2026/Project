from __future__ import annotations

import importlib.util
import io
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn
import pandas as pd

PHASES = ["opening", "middlegame", "endgame"]
PIECES = ["Pawn", "Knight", "Bishop", "Rook", "Queen", "King"]
TACTICS = ["capture", "check", "castle", "promotion", "quiet"]

INACCURACY_THRESHOLD = 50
MISTAKE_THRESHOLD = 100
BLUNDER_THRESHOLD = 200
QUALITY_TO_CP = {
    "Good": 15,
    "Inaccuracy": 70,
    "Mistake": 140,
    "Blunder": 260,
}


def _find_file(filename: str) -> Optional[Path]:
    env_root = os.environ.get("CHESS_PROJECT_ROOT", "").strip()
    candidates: List[Path] = []

    if env_root:
        candidates.append(Path(env_root) / filename)

    here = Path(__file__).resolve()
    for parent in [Path.cwd(), here.parent, *here.parents]:
        candidates.append(parent / filename)
        candidates.append(parent / "output" / filename)
        candidates.append(parent / "src" / filename)

    candidates.append(Path("/mnt/data") / filename)

    seen = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path
    return None


def _load_module(alias: str, filename: str):
    path = _find_file(filename)
    if path is None:
        return None

    spec = importlib.util.spec_from_file_location(alias, str(path))
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(alias, None)
        raise

    return module


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
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


def _normalize_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def default_profile(source: str = "general", username: str = "") -> Dict[str, Any]:
    profile: Dict[str, Any] = {
        "source": source,
        "username": username,
        "games_count": 0,
        "moves_analyzed": 0,
        "avg_rating": 1500,
        "avg_target_elo": 1500,
        "recommended_difficulty_bucket": "medium",
        "profile_quality": "general",
        "primary_weak_phase": "middlegame",
        "primary_weak_piece": "Knight",
        "primary_weak_tactic": "quiet",
        "message": "Profil général activé.",
        "error_frequency": {
            "quiet": 5,
            "check": 4,
            "capture": 3,
            "promotion": 1,
            "castle": 1,
        },
        "time_trouble_weakness_score": 1.0,
        "good_rate": 0.0,
        "inaccuracy_rate": 0.0,
        "mistake_rate": 0.0,
        "blunder_rate": 0.0,
    }

    for phase in PHASES:
        profile[f"weakness_{phase}_score"] = 1.0
    for piece in PIECES:
        profile[f"weakness_{piece}_score"] = 1.0
        profile[f"weakness_{piece.lower()}_score"] = 1.0
    for tactic in TACTICS:
        profile[f"weakness_{tactic}_score"] = 1.0

    return profile


def _classify_move(cp_loss: int) -> str:
    if cp_loss < INACCURACY_THRESHOLD:
        return "Good"
    if cp_loss < MISTAKE_THRESHOLD:
        return "Inaccuracy"
    if cp_loss < BLUNDER_THRESHOLD:
        return "Mistake"
    return "Blunder"


def _extract_cp(eval_entry: Any) -> int:
    if eval_entry is None:
        return 0
    if isinstance(eval_entry, (int, float)):
        return int(eval_entry)
    if not isinstance(eval_entry, dict):
        return 0
    if "eval" in eval_entry:
        return _extract_cp(eval_entry["eval"])
    if "mate" in eval_entry and eval_entry["mate"] is not None:
        mate = int(eval_entry["mate"])
        return (10000 - mate) if mate > 0 else (-10000 - mate)
    if "cp" in eval_entry and eval_entry["cp"] is not None:
        return int(eval_entry["cp"])
    return 0


def _infer_phase(board: chess.Board) -> str:
    heavy = sum(
        len(board.pieces(pt, color))
        for pt in [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]
        for color in [chess.WHITE, chess.BLACK]
    )
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))

    if board.fullmove_number <= 10 and heavy >= 12:
        return "opening"
    if queens == 0 and heavy <= 6:
        return "endgame"
    return "middlegame"


def _piece_name(piece: Optional[chess.Piece]) -> str:
    if piece is None:
        return "Pawn"
    names = {
        chess.PAWN: "Pawn",
        chess.KNIGHT: "Knight",
        chess.BISHOP: "Bishop",
        chess.ROOK: "Rook",
        chess.QUEEN: "Queen",
        chess.KING: "King",
    }
    return names.get(piece.piece_type, "Pawn")


def _ensure_ui_profile_fields(profile: Dict[str, Any], source: str, username: str, message: str) -> Dict[str, Any]:
    out = dict(profile)
    out["source"] = source
    out["username"] = username
    out["message"] = message
    out["moves_analyzed"] = int(out.get("moves_analyzed", out.get("target_moves", 0)) or 0)
    out["games_count"] = int(out.get("games_count", 0) or 0)

    avg_elo = _safe_int(out.get("avg_target_elo"), 1500) or 1500
    out["avg_rating"] = avg_elo
    out["avg_target_elo"] = avg_elo

    primary_piece = str(out.get("primary_weak_piece", "Knight") or "Knight").strip()
    if primary_piece:
        out["primary_weak_piece"] = primary_piece[0].upper() + primary_piece[1:]

    for piece in PIECES:
        lower_key = f"weakness_{piece.lower()}_score"
        title_key = f"weakness_{piece}_score"
        if lower_key in out and title_key not in out:
            out[title_key] = out[lower_key]
        if title_key in out and lower_key not in out:
            out[lower_key] = out[title_key]
        if title_key not in out:
            out[title_key] = 1.0
        if lower_key not in out:
            out[lower_key] = 1.0

    if "error_frequency" not in out:
        out["error_frequency"] = {t: int(out.get(f"{t}_moves", 0) or 0) for t in TACTICS}

    return out


def _build_profile_with_original_scorer(
    username: str,
    user_games: Dict[str, Dict[str, Any]],
    user_moves: List[Dict[str, Any]],
    user_summaries: List[Dict[str, Any]],
    source: str,
    success_message: str,
):
    profiler_mod = _load_module("project_build_player_weakness_profile", "build_player_weakness_profile.py")
    if profiler_mod is None:
        profile = default_profile(source="general", username=username)
        profile["message"] = "Impossible de charger build_player_weakness_profile.py. Recommandations générales activées."
        return profile

    raw_profile = profiler_mod.build_profile_for_user(
        username=username or "uploaded_csv",
        user_games=user_games,
        user_moves=user_moves,
        user_summaries=user_summaries,
        time_trouble_threshold_cs=3000,
        min_category_moves=8,
    )

    move_count = int(raw_profile.get("target_moves", 0) or 0)
    if move_count <= 0:
        profile = default_profile(source="general", username=username)
        profile["message"] = "Pas assez de coups analysables pour personnaliser correctement. Recommandations générales activées."
        return profile

    return _ensure_ui_profile_fields(
        raw_profile,
        source=source,
        username=username,
        message=success_message,
    )


def _raw_game_to_profile_rows(game_data: Dict[str, Any], username: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    try:
        pgn_text = game_data.get("pgn", "")
        pgn_game = chess.pgn.read_game(io.StringIO(pgn_text))
        if pgn_game is None:
            return None, []

        analysis = game_data.get("analysis", [])
        if not analysis:
            return None, []

        players = game_data.get("players", {}) or {}
        white_info = players.get("white", {}) or {}
        black_info = players.get("black", {}) or {}

        white_name = ((white_info.get("user") or {}).get("name") or "").strip()
        black_name = ((black_info.get("user") or {}).get("name") or "").strip()
        wanted = username.strip().lower()

        if white_name.lower() == wanted:
            target_color = chess.WHITE
            target_elo = white_info.get("rating")
            target_color_text = "white"
        elif black_name.lower() == wanted:
            target_color = chess.BLACK
            target_elo = black_info.get("rating")
            target_color_text = "black"
        else:
            return None, []

        opening = game_data.get("opening") or {}
        game_row = {
            "game_id": game_data.get("id", ""),
            "opening_name": opening.get("name", ""),
            "target_elo": target_elo if target_elo is not None else "",
            "target_color": target_color_text,
        }

        board = pgn_game.board()
        clocks = game_data.get("clocks") if isinstance(game_data.get("clocks"), list) else None
        clock_initial = None
        if isinstance(game_data.get("clock"), dict):
            try:
                clock_initial = int(game_data["clock"]["initial"]) * 100
            except Exception:
                clock_initial = None

        move_rows: List[Dict[str, Any]] = []
        ply_idx = 0

        for node in pgn_game.mainline():
            move = node.move
            side = board.turn
            is_target = side == target_color

            if ply_idx + 1 >= len(analysis):
                board.push(move)
                ply_idx += 1
                continue

            entry_before = analysis[ply_idx]
            entry_after = analysis[ply_idx + 1]

            cp_before_white = _extract_cp(entry_before)
            cp_after_white = _extract_cp(entry_after)

            cp_before_target = cp_before_white if target_color == chess.WHITE else -cp_before_white
            cp_after_target = cp_after_white if target_color == chess.WHITE else -cp_after_white

            if is_target:
                cp_loss = max(0, int(cp_before_target - cp_after_target))
                phase = _infer_phase(board)
                piece_type = _piece_name(board.piece_at(move.from_square))
                is_capture = board.is_capture(move)
                is_castle = board.is_castling(move)
                is_promotion = move.promotion is not None
                try:
                    is_check = board.gives_check(move)
                except Exception:
                    is_check = False

                clock_before = ""
                if clocks:
                    ply = ply_idx + 1
                    try:
                        prev_idx = ply - 3
                        clock_before = int(clocks[prev_idx]) if prev_idx >= 0 else (
                            clock_initial if clock_initial is not None else ""
                        )
                    except Exception:
                        clock_before = ""

                move_rows.append({
                    "game_id": game_row["game_id"],
                    "ply": ply_idx + 1,
                    "player_color": target_color_text,
                    "phase": phase,
                    "piece_type": piece_type,
                    "is_capture": is_capture,
                    "is_check": is_check,
                    "is_castle": is_castle,
                    "is_promotion": is_promotion,
                    "move_quality": _classify_move(cp_loss),
                    "cp_loss": cp_loss,
                    "clock_before_cs": clock_before,
                })

            board.push(move)
            ply_idx += 1

        return game_row, move_rows

    except Exception:
        return None, []


def build_profile_from_lichess_games(username: str, games: List[Dict[str, Any]]):
    username = (username or "").strip()

    if not games:
        profile = default_profile(source="general", username=username)
        profile["message"] = "Aucune partie Lichess exploitable. Recommandations générales activées."
        return profile

    user_games: Dict[str, Dict[str, Any]] = {}
    user_moves: List[Dict[str, Any]] = []
    usable_games = 0

    for raw_game in games:
        game_row, move_rows = _raw_game_to_profile_rows(raw_game, username)
        if game_row is None or not move_rows:
            continue
        usable_games += 1
        user_games[str(game_row["game_id"])] = game_row
        user_moves.extend(move_rows)

    if not user_moves:
        profile = default_profile(source="general", username=username)
        profile["message"] = "Aucune partie Lichess analysée avec évaluations moteur exploitables. Recommandations générales activées."
        return profile

    return _build_profile_with_original_scorer(
        username=username,
        user_games=user_games,
        user_moves=user_moves,
        user_summaries=[],
        source="lichess",
        success_message=f"Profil personnalisé construit sur {usable_games} parties et {len(user_moves)} coups analysés.",
    )


def _normalize_csv_rows(df: pd.DataFrame) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    user_games: Dict[str, Dict[str, Any]] = {}
    user_moves: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        game_id = str(row.get("game_id", f"csv_game_{idx // 80 + 1}") or f"csv_game_{idx // 80 + 1}").strip()

        piece_type = str(row.get("piece_type", row.get("source_piece_type", "Pawn")) or "Pawn").strip().title()
        if piece_type not in PIECES:
            piece_type = "Pawn"

        phase = str(row.get("phase", "middlegame") or "middlegame").strip().lower()
        if phase not in PHASES:
            phase = "middlegame"

        quality = str(row.get("move_quality", "") or "").strip().title()
        if quality not in QUALITY_TO_CP:
            cp_loss = _safe_int(row.get("cp_loss"), None)
            if cp_loss is None:
                quality = "Good"
            elif cp_loss < INACCURACY_THRESHOLD:
                quality = "Good"
            elif cp_loss < MISTAKE_THRESHOLD:
                quality = "Inaccuracy"
            elif cp_loss < BLUNDER_THRESHOLD:
                quality = "Mistake"
            else:
                quality = "Blunder"

        cp_loss = _safe_int(row.get("cp_loss"), QUALITY_TO_CP.get(quality, 15)) or QUALITY_TO_CP.get(quality, 15)

        user_games.setdefault(
            game_id,
            {
                "game_id": game_id,
                "opening_name": str(row.get("opening_name", "") or "").strip(),
                "target_elo": _safe_int(
                    row.get("target_elo", row.get("avg_target_elo", row.get("avg_rating", ""))),
                    "",
                ) or "",
                "target_color": str(row.get("target_color", row.get("player_color", "white")) or "white").strip().lower(),
            },
        )

        user_moves.append(
            {
                "game_id": game_id,
                "phase": phase,
                "piece_type": piece_type,
                "move_quality": quality,
                "cp_loss": cp_loss,
                "clock_before_cs": _safe_int(row.get("clock_before_cs"), 9999),
                "is_capture": _normalize_bool(row.get("is_capture")),
                "is_check": _normalize_bool(row.get("is_check")),
                "is_castle": _normalize_bool(row.get("is_castle")),
                "is_promotion": _normalize_bool(row.get("is_promotion")),
            }
        )

    return user_games, user_moves


def build_profile_from_csv(df: pd.DataFrame):
    if df is None or df.empty:
        profile = default_profile(source="general", username="")
        profile["message"] = "CSV vide. Recommandations générales activées."
        return profile

    user_games, user_moves = _normalize_csv_rows(df)

    profile = _build_profile_with_original_scorer(
        username="uploaded_csv",
        user_games=user_games,
        user_moves=user_moves,
        user_summaries=[],
        source="csv",
        success_message=f"Profil personnalisé construit sur {len(user_games)} parties et {len(user_moves)} coups CSV.",
    )

    if profile.get("source") == "general":
        profile["message"] = "CSV insuffisant pour personnaliser correctement. Recommandations générales activées."

    return profile