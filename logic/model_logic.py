from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd

DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2, "expert": 3}
PHASES = ["opening", "middlegame", "endgame"]
PIECES = ["pawn", "knight", "bishop", "rook", "queen", "king"]
TACTICS = ["capture", "check", "castle", "promotion", "quiet"]

PLAYER_FEATURES_NUMERIC = [
    "avg_target_elo",
    "mean_cp_loss",
    "median_cp_loss",
    "p90_cp_loss",
    "good_rate",
    "inaccuracy_rate",
    "mistake_rate",
    "blunder_rate",
    "time_trouble_weakness_score",
    "weakness_opening_score",
    "weakness_middlegame_score",
    "weakness_endgame_score",
    "weakness_pawn_score",
    "weakness_knight_score",
    "weakness_bishop_score",
    "weakness_rook_score",
    "weakness_queen_score",
    "weakness_king_score",
    "weakness_capture_score",
    "weakness_check_score",
    "weakness_castle_score",
    "weakness_promotion_score",
    "weakness_quiet_score",
]

PLAYER_FEATURES_CATEGORICAL = [
    "recommended_difficulty_bucket",
    "profile_quality",
    "favorite_opening",
    "weakest_opening",
    "primary_weak_phase",
    "primary_weak_piece",
    "primary_weak_tactic",
]

PUZZLE_FEATURES_NUMERIC = [
    "difficulty_score",
    "white_elo",
    "black_elo",
    "avg_player_elo",
    "target_elo",
    "opponent_elo",
    "source_cp_loss",
    "source_eval_white_before",
    "source_eval_white_after",
    "puzzle_eval_white_before",
    "engine_best_eval_cp",
    "engine_best_mate",
    "engine_second_eval_cp",
    "engine_second_mate",
    "best_vs_second_gap_cp",
    "validation_depth",
    "validation_multipv",
]

PUZZLE_FEATURES_CATEGORICAL = [
    "side_to_move",
    "final_theme",
    "phase",
    "source_move_quality",
    "source_player_color",
    "source_piece_type",
    "speed",
    "time_control",
    "rated",
    "opening_eco",
    "opening_name",
    "target_result",
    "difficulty_bucket",
    "final_solution_source",
]

PAIR_FEATURES_NUMERIC = [
    "phase_match_score",
    "piece_match_score",
    "tactic_match_score",
    "difficulty_fit_score",
    "gap_bonus",
    "engine_bonus",
    "time_component",
]

PAIR_FEATURES_CATEGORICAL = [
    "matched_phase",
    "matched_piece",
    "matched_tactic",
]

FEATURE_COLUMNS = (
    [f"player__{c}" for c in PLAYER_FEATURES_NUMERIC + PLAYER_FEATURES_CATEGORICAL]
    + [f"puzzle__{c}" for c in PUZZLE_FEATURES_NUMERIC + PUZZLE_FEATURES_CATEGORICAL]
    + PAIR_FEATURES_NUMERIC
    + PAIR_FEATURES_CATEGORICAL
)


def _find_file(filename: str) -> Optional[Path]:
    env_root = os.environ.get("CHESS_PROJECT_ROOT", "").strip()
    candidates: List[Path] = []

    if env_root:
        root = Path(env_root)
        candidates.extend([
            root / filename,
            root / "models" / filename,
            root / "output" / filename,
            root / "output" / "model_artifacts" / filename,
            root / "data" / filename,
        ])

    here = Path(__file__).resolve()
    for parent in [Path.cwd(), here.parent, *here.parents]:
        candidates.extend([
            parent / filename,
            parent / "models" / filename,
            parent / "output" / filename,
            parent / "output" / "model_artifacts" / filename,
            parent / "data" / filename,
        ])

    candidates.append(Path("/mnt/data") / filename)

    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path
    return None


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


def _coalesce(*values: object) -> str:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


def _difficulty_bucket_from_score(score: object) -> str:
    value = _safe_float(score, 45.0) or 45.0
    if value <= 25:
        return "easy"
    if value <= 50:
        return "medium"
    if value <= 75:
        return "hard"
    return "expert"


def _first_nonempty(df: pd.DataFrame, candidates: List[str], default: str = "") -> pd.Series:
    result = pd.Series([default] * len(df), index=df.index, dtype="object")
    for col in candidates:
        if col not in df.columns:
            continue
        series = df[col].fillna("").astype(str)
        mask = result.astype(str).str.strip().eq("") & series.str.strip().ne("")
        result.loc[mask] = series.loc[mask]
    return result.fillna(default)


def _nice_fallback_title(theme: str, phase: str, piece_type: str) -> str:
    theme = (theme or "").replace("-", " ").strip().title()
    phase = (phase or "").strip().title()
    piece_type = (piece_type or "").strip().title()

    if theme and theme != "Improvement":
        return f"{theme} puzzle"
    if phase and piece_type:
        return f"{phase} — {piece_type} puzzle"
    if phase:
        return f"{phase} puzzle"
    return "Training puzzle"


def _resolve_puzzles_path(csv_path: Any) -> Optional[Path]:
    env_path = os.environ.get("CHESS_PUZZLES_CSV", "").strip()
    candidates: List[Path] = []

    if csv_path:
        candidates.append(Path(str(csv_path)))

    if env_path:
        candidates.append(Path(env_path))

    for name in [
        "data/puzzles.csv",
        "puzzles.csv",
        "puzzles_final.csv",
        "output/puzzles_final.csv",
    ]:
        found = _find_file(name)
        if found is not None:
            candidates.append(found)

    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return path
    return None


def _normalize_puzzles(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["puzzle_id"] = _first_nonempty(out, ["puzzle_id"], default="")
    if out["puzzle_id"].astype(str).str.strip().eq("").any():
        missing_count = int(out["puzzle_id"].astype(str).str.strip().eq("").sum())
        out.loc[out["puzzle_id"].astype(str).str.strip().eq(""), "puzzle_id"] = [
            f"puzzle_{i+1:06d}" for i in range(missing_count)
        ]

    out["fen"] = _first_nonempty(out, ["fen"], default="")
    out["solution_uci"] = _first_nonempty(
        out,
        ["solution_uci", "final_solution_uci", "engine_best_move_uci", "primary_solution_uci"],
        default="",
    )
    out["theme"] = _first_nonempty(
        out,
        ["theme", "final_theme", "engine_theme_guess", "theme_guess"],
        default="improvement",
    )
    out["phase"] = _first_nonempty(out, ["phase"], default="middlegame").str.lower()
    out["piece_type"] = _first_nonempty(
        out,
        ["piece_type", "source_piece_type"],
        default="Pawn",
    ).str.title()
    out["explanation"] = _first_nonempty(
        out,
        ["explanation", "validation_reason"],
        default="Travaille ce motif ciblé.",
    )

    if "difficulty_score" not in out.columns:
        out["difficulty_score"] = np.nan
    out["difficulty_score"] = pd.to_numeric(out["difficulty_score"], errors="coerce")

    out["difficulty_bucket"] = _first_nonempty(out, ["difficulty_bucket"], default="")
    missing_bucket = out["difficulty_bucket"].astype(str).str.strip().eq("")
    out.loc[missing_bucket, "difficulty_bucket"] = (
        out.loc[missing_bucket, "difficulty_score"].apply(_difficulty_bucket_from_score)
    )

    # Prefer real titles, then opening_name, then fallback
    out["title"] = _first_nonempty(
        out,
        ["title", "puzzle_title", "name", "opening_name"],
        default="",
    )

    missing_title = out["title"].astype(str).str.strip().eq("")
    out.loc[missing_title, "title"] = out.loc[missing_title].apply(
        lambda r: _nice_fallback_title(
            str(r.get("theme", "")),
            str(r.get("phase", "")),
            str(r.get("piece_type", "")),
        ),
        axis=1,
    )

    defaults_numeric = {
        "white_elo": np.nan,
        "black_elo": np.nan,
        "avg_player_elo": np.nan,
        "target_elo": np.nan,
        "opponent_elo": np.nan,
        "source_cp_loss": np.nan,
        "source_eval_white_before": np.nan,
        "source_eval_white_after": np.nan,
        "puzzle_eval_white_before": np.nan,
        "engine_best_eval_cp": np.nan,
        "engine_best_mate": np.nan,
        "engine_second_eval_cp": np.nan,
        "engine_second_mate": np.nan,
        "best_vs_second_gap_cp": np.nan,
        "validation_depth": np.nan,
        "validation_multipv": np.nan,
    }
    for col, value in defaults_numeric.items():
        if col not in out.columns:
            out[col] = value

    defaults_categorical = {
        "side_to_move": "white",
        "final_theme": "",
        "source_move_quality": "",
        "source_player_color": "",
        "source_piece_type": "",
        "speed": "",
        "time_control": "",
        "rated": "",
        "opening_eco": "",
        "opening_name": "",
        "target_result": "",
        "final_solution_source": "",
    }
    for col, value in defaults_categorical.items():
        if col not in out.columns:
            out[col] = value

    out["final_theme"] = _first_nonempty(out, ["final_theme", "theme"], default="improvement")
    out["source_piece_type"] = _first_nonempty(out, ["source_piece_type", "piece_type"], default="Pawn")
    out["side_to_move"] = _first_nonempty(out, ["side_to_move", "player_color"], default="white")
    out["final_solution_source"] = _first_nonempty(out, ["final_solution_source"], default="engine")

    out = out.dropna(subset=["fen", "solution_uci"]).copy()
    out = out[
        out["fen"].astype(str).str.strip().ne("")
        & out["solution_uci"].astype(str).str.strip().ne("")
    ].copy()

    return out.reset_index(drop=True)


def load_puzzles(csv_path: Any) -> pd.DataFrame:
    path = _resolve_puzzles_path(csv_path)
    if path is None:
        raise FileNotFoundError(
            "Impossible de trouver un fichier de puzzles. "
            "Place puzzles_final.csv dans output/ ou définis CHESS_PUZZLES_CSV."
        )
    df = pd.read_csv(path)
    return _normalize_puzzles(df)


def _difficulty_fit(player_bucket: str, puzzle_bucket: str) -> float:
    if player_bucket not in DIFFICULTY_ORDER or puzzle_bucket not in DIFFICULTY_ORDER:
        return 0.6
    delta = abs(DIFFICULTY_ORDER[player_bucket] - DIFFICULTY_ORDER[puzzle_bucket])
    return {0: 1.0, 1: 0.75, 2: 0.35}.get(delta, 0.1)


def _solution_tags(solution_tags: str) -> List[str]:
    text = (solution_tags or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _puzzle_tactic_scores(puzzle: pd.Series, profile: pd.Series) -> Tuple[float, str, List[str]]:
    scores: List[Tuple[str, float]] = []
    theme = str(puzzle.get("final_theme", "") or "").strip()
    tags = set(
        _solution_tags(
            str(
                puzzle.get("final_solution_tags", "")
                or puzzle.get("engine_solution_tags", "")
                or ""
            )
        )
    )

    if theme in {"mate", "check", "tactical-check"} or "check" in tags or "mate" in tags:
        scores.append(("check", _safe_float(profile.get("weakness_check_score"), 1.0) or 1.0))
    if theme in {"capture", "tactical-check"} or "capture" in tags:
        scores.append(("capture", _safe_float(profile.get("weakness_capture_score"), 1.0) or 1.0))
    if theme == "promotion" or "promotion" in tags:
        scores.append(("promotion", _safe_float(profile.get("weakness_promotion_score"), 1.0) or 1.0))
    if theme == "endgame-technique":
        scores.append(("quiet", _safe_float(profile.get("weakness_quiet_score"), 1.0) or 1.0))
    if not scores:
        scores.append(("quiet", _safe_float(profile.get("weakness_quiet_score"), 1.0) or 1.0))

    best_name, best_value = max(scores, key=lambda x: x[1])
    reasons = [f"tactic:{name}={value:.2f}" for name, value in sorted(scores, key=lambda x: x[1], reverse=True)]
    return best_value, best_name, reasons


def _phase_score(puzzle: pd.Series, profile: pd.Series) -> Tuple[float, str]:
    phase = str(puzzle.get("phase", "") or "").strip()
    value = _safe_float(profile.get(f"weakness_{phase}_score"), 1.0) if phase else 1.0
    return value or 1.0, phase


def _piece_score(puzzle: pd.Series, profile: pd.Series) -> Tuple[float, str]:
    piece = str(puzzle.get("source_piece_type", "") or "").strip().lower()
    value = _safe_float(profile.get(f"weakness_{piece}_score"), 1.0) if piece else 1.0
    return value or 1.0, piece


def _gap_bonus(puzzle: pd.Series) -> float:
    gap = _safe_float(puzzle.get("best_vs_second_gap_cp"), 0.0) or 0.0
    if gap >= 400:
        return 1.0
    if gap >= 250:
        return 0.8
    if gap >= 120:
        return 0.6
    if gap > 0:
        return 0.35
    return 0.0


def _engine_bonus(puzzle: pd.Series) -> float:
    valid = _normalize_bool(puzzle.get("is_valid_puzzle"))
    has_engine = _normalize_bool(puzzle.get("has_engine_solution")) or bool(
        str(puzzle.get("engine_best_move_uci", "") or "").strip()
    )
    bonus = 0.0
    if valid:
        bonus += 0.35
    if has_engine:
        bonus += 0.25
    return bonus


def _recommendation_reason(
    phase: str,
    phase_value: float,
    piece: str,
    piece_value: float,
    diff_fit: float,
    gap_bonus: float,
    tactic_reasons: Sequence[str],
) -> str:
    reasons = [
        f"phase:{phase}={phase_value:.2f}",
        f"piece:{piece}={piece_value:.2f}",
        f"difficulty_fit={diff_fit:.2f}",
        f"gap_bonus={gap_bonus:.2f}",
    ]
    reasons.extend(list(tactic_reasons[:2]))
    return "; ".join(reasons)


def pair_features(profile: pd.Series, puzzle: pd.Series) -> Dict[str, Any]:
    phase_value, phase_name = _phase_score(puzzle, profile)
    piece_value, piece_name = _piece_score(puzzle, profile)
    tactic_value, tactic_name, tactic_reasons = _puzzle_tactic_scores(puzzle, profile)
    player_bucket = str(profile.get("recommended_difficulty_bucket", "medium") or "medium").strip()
    puzzle_bucket = str(puzzle.get("difficulty_bucket", "") or "").strip()
    diff_fit = _difficulty_fit(player_bucket, puzzle_bucket)
    gap_bonus = _gap_bonus(puzzle)
    engine_bonus = _engine_bonus(puzzle)
    time_trouble_score = _safe_float(profile.get("time_trouble_weakness_score"), 1.0) or 1.0
    time_component = 0.15 * max(0.6, min(1.6, time_trouble_score))

    heuristic_score = (
        35.0 * phase_value
        + 25.0 * piece_value
        + 20.0 * tactic_value
        + 12.0 * diff_fit
        + 5.0 * gap_bonus
        + 3.0 * engine_bonus
        + time_component
    )

    row: Dict[str, Any] = {
        "username": str(profile.get("username", "") or ""),
        "puzzle_id": str(puzzle.get("puzzle_id", "") or ""),
        "game_id": str(puzzle.get("game_id", "") or ""),
        "heuristic_score": heuristic_score,
        "recommendation_reason": _recommendation_reason(
            phase_name, phase_value, piece_name, piece_value, diff_fit, gap_bonus, tactic_reasons
        ),
        "matched_phase": phase_name,
        "matched_piece": piece_name,
        "matched_tactic": tactic_name,
        "phase_match_score": phase_value,
        "piece_match_score": piece_value,
        "tactic_match_score": tactic_value,
        "difficulty_fit_score": diff_fit,
        "gap_bonus": gap_bonus,
        "engine_bonus": engine_bonus,
        "time_component": time_component,
        "difficulty_bucket": puzzle_bucket,
        "final_theme": str(puzzle.get("final_theme", "") or ""),
    }

    for col in PLAYER_FEATURES_NUMERIC + PLAYER_FEATURES_CATEGORICAL:
        row[f"player__{col}"] = profile.get(col, np.nan)
    for col in PUZZLE_FEATURES_NUMERIC + PUZZLE_FEATURES_CATEGORICAL:
        row[f"puzzle__{col}"] = puzzle.get(col, np.nan)

    return row


def filter_puzzles(puzzles: pd.DataFrame, only_valid: bool, min_gap_cp: int) -> pd.DataFrame:
    out = puzzles.copy()
    if only_valid and "is_valid_puzzle" in out.columns:
        mask = out["is_valid_puzzle"].astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "t"})
        out = out.loc[mask].copy()
    if min_gap_cp > 0 and "best_vs_second_gap_cp" in out.columns:
        gap = pd.to_numeric(out["best_vs_second_gap_cp"], errors="coerce")
        out = out.loc[(gap.isna()) | (gap >= min_gap_cp)].copy()
    return out.reset_index(drop=True)


def _normalize_profile(profile: Dict[str, Any]) -> pd.Series:
    data = dict(profile)

    avg_rating = float(data.get("avg_target_elo") or data.get("avg_rating") or 1500)
    data.setdefault("username", data.get("username", ""))
    data.setdefault("avg_target_elo", avg_rating)
    data.setdefault("mean_cp_loss", 120.0)
    data.setdefault("median_cp_loss", 100.0)
    data.setdefault("p90_cp_loss", 300.0)
    data.setdefault("good_rate", 0.55)
    data.setdefault("inaccuracy_rate", 0.20)
    data.setdefault("mistake_rate", 0.15)
    data.setdefault("blunder_rate", 0.10)
    data.setdefault("time_trouble_weakness_score", 1.0)
    data.setdefault("recommended_difficulty_bucket", "medium")
    data.setdefault("profile_quality", "general")
    data.setdefault("favorite_opening", "")
    data.setdefault("weakest_opening", "")
    data.setdefault("primary_weak_phase", "middlegame")
    data.setdefault("primary_weak_piece", "knight")
    data.setdefault("primary_weak_tactic", "quiet")

    for phase in PHASES:
        data.setdefault(f"weakness_{phase}_score", 1.0)
    for piece in PIECES:
        data.setdefault(f"weakness_{piece}_score", data.get(f"weakness_{piece.title()}_score", 1.0))
        data.setdefault(f"weakness_{piece.title()}_score", data.get(f"weakness_{piece}_score", 1.0))
    for tactic in TACTICS:
        data.setdefault(f"weakness_{tactic}_score", 1.0)

    return pd.Series(data)


def _load_saved_model() -> Any:
    env_model = os.environ.get("CHESS_RANKER_MODEL", "").strip()
    candidates: List[Path] = []

    if env_model:
        candidates.append(Path(env_model))

    for name in [
        "personalized_puzzle_ranker_random_forest.joblib",
        "puzzle_ranker.joblib",
    ]:
        found = _find_file(name)
        if found is not None:
            candidates.append(found)

    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            try:
                return joblib.load(path)
            except Exception:
                continue
    return None


def train_or_load_model(puzzles_df: pd.DataFrame):
    return _load_saved_model()


def _fallback_rank(profile: pd.Series, puzzles_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    out = puzzles_df.copy()

    theme_to_tactic = {
        "mate": "check",
        "check": "check",
        "tactical-check": "check",
        "capture": "capture",
        "promotion": "promotion",
        "endgame-technique": "quiet",
        "improvement": "quiet",
    }

    mapped_tactic = out["theme"].map(lambda v: theme_to_tactic.get(str(v), "quiet"))
    diff_fit = out["difficulty_bucket"].map(
        lambda v: 1.0 if str(v) == str(profile.get("recommended_difficulty_bucket", "medium")) else 0.75
    )
    phase_score = out["phase"].map(lambda v: float(profile.get(f"weakness_{v}_score", 1.0)))
    piece_score = out["piece_type"].map(
        lambda v: float(
            profile.get(
                f"weakness_{str(v).lower()}_score",
                profile.get(f"weakness_{str(v).title()}_score", 1.0),
            )
        )
    )
    tactic_score = mapped_tactic.map(lambda v: float(profile.get(f"weakness_{v}_score", 1.0)))

    heuristic = 35.0 * phase_score + 25.0 * piece_score + 20.0 * tactic_score + 12.0 * diff_fit
    heuristic = heuristic.astype(float)
    model_score = (heuristic - heuristic.min()) / (heuristic.max() - heuristic.min() + 1e-9)

    out["model_score"] = model_score
    out["priority_score"] = model_score
    out["recommendation_reason"] = out.apply(
        lambda r: f"Heuristique: phase {r['phase']}; pièce {r['piece_type']}; motif {r['theme']}",
        axis=1,
    )
    return out.sort_values(["priority_score", "difficulty_score"], ascending=[False, True]).head(top_n).reset_index(drop=True)


def rank_puzzles(profile: Dict[str, Any], puzzles_df: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    prof = _normalize_profile(profile)
    puzzles = filter_puzzles(puzzles_df, only_valid=False, min_gap_cp=0)

    if puzzles.empty:
        return puzzles.copy()

    pair_rows = [pair_features(prof, puzzle) for _, puzzle in puzzles.iterrows()]
    pair_df = pd.DataFrame(pair_rows)

    if pair_df.empty:
        return puzzles.head(0).copy()

    heur = pair_df["heuristic_score"].astype(float)
    heur_norm = (heur - heur.min()) / (heur.max() - heur.min() + 1e-9)

    model = _load_saved_model()
    model_scores = None

    if model is not None:
        try:
            for col in FEATURE_COLUMNS:
                if col not in pair_df.columns:
                    pair_df[col] = np.nan
            model_scores = model.predict_proba(pair_df[FEATURE_COLUMNS])[:, 1]
        except Exception:
            model_scores = None

    if model_scores is None:
        return _fallback_rank(prof, puzzles, top_n)

    out = puzzles.reset_index(drop=True).copy()
    out["model_score"] = model_scores
    out["priority_score"] = 0.7 * out["model_score"].astype(float) + 0.3 * heur_norm.astype(float)
    out["recommendation_reason"] = pair_df["recommendation_reason"].values

    if "theme" not in out.columns:
        out["theme"] = out["final_theme"]
    if "piece_type" not in out.columns:
        out["piece_type"] = _coalesce(out.get("source_piece_type"), out.get("piece_type"))

    return out.sort_values(
        ["priority_score", "model_score", "difficulty_score"],
        ascending=[False, False, True],
    ).head(top_n).reset_index(drop=True)