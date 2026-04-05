#!/usr/bin/env python3
"""
Train and use a learned personalized puzzle ranking model.

Important note:
- This script trains on *proxy labels* built from the current heuristic recommender,
  because the project does not yet have real player->puzzle outcome data
  (shown / solved / failed / time to solve / hints used).
- That still gives you a useful learned ranking model that can replace or complement
  the hand-written rules. Later, when you collect real interaction logs, you can keep
  the same structure and swap in true labels.

Modes:
1) train
   - reads output/player_weakness_profiles.csv and output/puzzles_final.csv
   - builds player/puzzle pairs with heuristic compatibility scores
   - labels top matches as positives and sampled lower-scoring matches as negatives
   - trains a classifier to predict whether a puzzle is a good fit for a player
   - saves model + metrics + feature importance + sample predictions

2) recommend
   - loads the saved model
   - scores every puzzle for one username
   - writes a ranked CSV of recommended puzzles

Examples:
    python personalized_puzzle_ranker.py train

    python personalized_puzzle_ranker.py train \
        --profiles-csv output/player_weakness_profiles.csv \
        --puzzles-csv output/puzzles_final.csv

    python personalized_puzzle_ranker.py recommend \
        --model-path output/model_artifacts/personalized_puzzle_ranker_random_forest.joblib \
        --username some_player
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


DEFAULT_PROFILES = "output/player_weakness_profiles.csv"
DEFAULT_PUZZLES = "output/puzzles_final.csv"
DEFAULT_OUTPUT_DIR = "output/model_artifacts"
DEFAULT_RECOMMEND_OUTPUT = "output/personalized_puzzles_model.csv"
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

META_COLUMNS = [
    "username",
    "puzzle_id",
    "game_id",
    "heuristic_score",
    "pseudo_label",
    "difficulty_bucket",
    "final_theme",
    "recommendation_reason",
]


@dataclass
class PairBuildConfig:
    top_k_per_user: int = 30
    negative_ratio: float = 2.0
    max_puzzles_per_user: int = 0
    min_gap_cp: int = 0
    only_valid: bool = True
    random_state: int = 42


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train or use a personalized puzzle ranking model")
    sub = parser.add_subparsers(dest="mode", required=True)

    train = sub.add_parser("train", help="Train the personalized ranker")
    train.add_argument("--profiles-csv", default=DEFAULT_PROFILES, help="Path to player_weakness_profiles.csv")
    train.add_argument("--puzzles-csv", default=DEFAULT_PUZZLES, help="Path to puzzles_final.csv")
    train.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for model/artifacts")
    train.add_argument("--model", choices=["random_forest", "logistic_regression"], default="random_forest")
    train.add_argument("--top-k-per-user", type=int, default=30, help="Pseudo-positive count per user")
    train.add_argument("--negative-ratio", type=float, default=2.0, help="Negatives per positive")
    train.add_argument("--max-puzzles-per-user", type=int, default=0, help="Optional cap on candidate puzzles per user")
    train.add_argument("--min-gap-cp", type=int, default=0, help="Optional puzzle filter on best_vs_second_gap_cp")
    train.add_argument("--include-invalid", action="store_true", help="Include puzzles marked invalid")
    train.add_argument("--val-size", type=float, default=0.15, help="Validation fraction")
    train.add_argument("--test-size", type=float, default=0.15, help="Test fraction")
    train.add_argument("--random-state", type=int, default=42, help="Random seed")
    train.add_argument("--top-k-features", type=int, default=40, help="How many top features to save")

    rec = sub.add_parser("recommend", help="Score puzzles for one player using a saved model")
    rec.add_argument("--model-path", required=True, help="Path to saved .joblib model")
    rec.add_argument("--profiles-csv", default=DEFAULT_PROFILES, help="Path to player_weakness_profiles.csv")
    rec.add_argument("--puzzles-csv", default=DEFAULT_PUZZLES, help="Path to puzzles_final.csv")
    rec.add_argument("--username", required=True, help="Player username to score for")
    rec.add_argument("--output", default=DEFAULT_RECOMMEND_OUTPUT, help="Output ranked CSV path")
    rec.add_argument("--top-n", type=int, default=50, help="How many puzzles to keep")
    rec.add_argument("--min-gap-cp", type=int, default=0, help="Optional extra filter on best_vs_second_gap_cp")
    rec.add_argument("--include-invalid", action="store_true", help="Include puzzles marked invalid")
    rec.add_argument("--max-per-theme", type=int, default=0, help="Optional cap per final_theme")

    return parser.parse_args()


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


def _load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


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
    tags = set(_solution_tags(str(puzzle.get("final_solution_tags", "") or puzzle.get("engine_solution_tags", "") or "")))

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
    has_engine = _normalize_bool(puzzle.get("has_engine_solution")) or bool(str(puzzle.get("engine_best_move_uci", "") or "").strip())
    bonus = 0.0
    if valid:
        bonus += 0.35
    if has_engine:
        bonus += 0.25
    return bonus


def _recommendation_reason(phase: str, phase_value: float, piece: str, piece_value: float, diff_fit: float, gap_bonus: float, tactic_reasons: Sequence[str]) -> str:
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
        "recommendation_reason": _recommendation_reason(phase_name, phase_value, piece_name, piece_value, diff_fit, gap_bonus, tactic_reasons),
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


def build_training_pairs(profiles: pd.DataFrame, puzzles: pd.DataFrame, cfg: PairBuildConfig) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.random_state)
    all_rows: List[Dict[str, Any]] = []

    puzzles = filter_puzzles(puzzles, only_valid=cfg.only_valid, min_gap_cp=cfg.min_gap_cp)
    if puzzles.empty:
        raise ValueError("No puzzles available after filtering.")

    for _, profile in profiles.iterrows():
        candidates = puzzles
        if cfg.max_puzzles_per_user > 0 and len(candidates) > cfg.max_puzzles_per_user:
            take = rng.choice(candidates.index.to_numpy(), size=cfg.max_puzzles_per_user, replace=False)
            candidates = candidates.loc[np.sort(take)].copy()

        pair_rows = [pair_features(profile, puzzle) for _, puzzle in candidates.iterrows()]
        if not pair_rows:
            continue
        pair_df = pd.DataFrame(pair_rows).sort_values("heuristic_score", ascending=False).reset_index(drop=True)

        pos_k = min(cfg.top_k_per_user, len(pair_df))
        if pos_k == 0:
            continue
        neg_k = min(int(round(pos_k * cfg.negative_ratio)), max(0, len(pair_df) - pos_k))

        positives = pair_df.iloc[:pos_k].copy()
        positives["pseudo_label"] = 1

        remainder = pair_df.iloc[pos_k:].copy()
        if neg_k > 0 and not remainder.empty:
            if len(remainder) > neg_k:
                low_half = remainder.iloc[len(remainder) // 2 :].copy()
                source = low_half if len(low_half) >= neg_k else remainder
                chosen = rng.choice(source.index.to_numpy(), size=neg_k, replace=False)
                negatives = source.loc[np.sort(chosen)].copy()
            else:
                negatives = remainder.copy()
            negatives["pseudo_label"] = 0
            pair_df = pd.concat([positives, negatives], ignore_index=True)
        else:
            pair_df = positives

        all_rows.extend(pair_df.to_dict("records"))

    if not all_rows:
        raise ValueError("Failed to build any training pairs.")

    out = pd.DataFrame(all_rows)
    out[FEATURE_COLUMNS] = out[FEATURE_COLUMNS].copy()
    return out


def train_val_test_split(df: pd.DataFrame, group_column: str, val_size: float, test_size: float, random_state: int) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    groups = df[group_column].astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_val_idx, test_idx = next(splitter.split(df, groups=groups))
    train_val = df.iloc[train_val_idx].reset_index(drop=True)
    test = df.iloc[test_idx].reset_index(drop=True)

    adjusted_val = val_size / max(1e-9, 1.0 - test_size)
    groups_train_val = train_val[group_column].astype(str)
    splitter2 = GroupShuffleSplit(n_splits=1, test_size=adjusted_val, random_state=random_state + 1)
    train_idx, val_idx = next(splitter2.split(train_val, groups=groups_train_val))
    train = train_val.iloc[train_idx].reset_index(drop=True)
    val = train_val.iloc[val_idx].reset_index(drop=True)
    return train, val, test


def build_model(feature_df: pd.DataFrame, model_name: str) -> Pipeline:
    categorical_cols = [c for c in feature_df.columns if feature_df[c].dtype == object]
    numeric_cols = [c for c in feature_df.columns if c not in categorical_cols]

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]),
                numeric_cols,
            ),
            (
                "cat",
                Pipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore")),
                ]),
                categorical_cols,
            ),
        ]
    )

    if model_name == "logistic_regression":
        estimator = LogisticRegression(max_iter=2000, class_weight="balanced")
    else:
        estimator = RandomForestClassifier(
            n_estimators=400,
            max_depth=None,
            min_samples_leaf=2,
            random_state=42,
            class_weight="balanced_subsample",
            n_jobs=-1,
        )

    return Pipeline([
        ("preprocessor", preprocessor),
        ("model", estimator),
    ])


def evaluate_classifier(model: Pipeline, X: pd.DataFrame, y: pd.Series) -> Dict[str, Any]:
    prob = model.predict_proba(X)[:, 1]
    pred = (prob >= 0.5).astype(int)
    metrics: Dict[str, Any] = {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro")),
        "weighted_f1": float(f1_score(y, pred, average="weighted")),
        "average_precision": float(average_precision_score(y, prob)),
        "confusion_matrix": confusion_matrix(y, pred).tolist(),
        "classification_report": classification_report(y, pred, output_dict=True),
    }
    if len(np.unique(y)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y, prob))
    return metrics


def prediction_frame(model: Pipeline, df: pd.DataFrame) -> pd.DataFrame:
    X = df[FEATURE_COLUMNS]
    prob = model.predict_proba(X)[:, 1]
    pred = (prob >= 0.5).astype(int)
    out = df[META_COLUMNS].copy()
    out["predicted_probability"] = prob
    out["predicted_label"] = pred
    return out


def top_features(model: Pipeline, feature_df: pd.DataFrame, top_k: int) -> pd.DataFrame:
    pre = model.named_steps["preprocessor"]
    est = model.named_steps["model"]
    feature_names = pre.get_feature_names_out()

    if hasattr(est, "feature_importances_"):
        values = est.feature_importances_
    elif hasattr(est, "coef_"):
        coef = est.coef_[0] if getattr(est.coef_, "ndim", 1) > 1 else est.coef_
        values = np.abs(coef)
    else:
        return pd.DataFrame(columns=["feature", "importance"])

    imp = pd.DataFrame({"feature": feature_names, "importance": values})
    imp = imp.sort_values("importance", ascending=False).head(top_k).reset_index(drop=True)
    return imp


def train_mode(args: argparse.Namespace) -> None:
    profiles = _load_csv(args.profiles_csv)
    puzzles = _load_csv(args.puzzles_csv)
    cfg = PairBuildConfig(
        top_k_per_user=args.top_k_per_user,
        negative_ratio=args.negative_ratio,
        max_puzzles_per_user=args.max_puzzles_per_user,
        min_gap_cp=args.min_gap_cp,
        only_valid=not args.include_invalid,
        random_state=args.random_state,
    )

    pairs = build_training_pairs(profiles, puzzles, cfg)
    train_df, val_df, test_df = train_val_test_split(
        pairs,
        group_column="username",
        val_size=args.val_size,
        test_size=args.test_size,
        random_state=args.random_state,
    )

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df["pseudo_label"].astype(int)
    X_val = val_df[FEATURE_COLUMNS]
    y_val = val_df["pseudo_label"].astype(int)
    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df["pseudo_label"].astype(int)

    model = build_model(X_train, args.model)
    model.fit(X_train, y_train)

    metrics = {
        "task": "personalized_proxy_classification",
        "model": args.model,
        "train_rows": int(len(train_df)),
        "val_rows": int(len(val_df)),
        "test_rows": int(len(test_df)),
        "players_train": int(train_df["username"].nunique()),
        "players_val": int(val_df["username"].nunique()),
        "players_test": int(test_df["username"].nunique()),
        "config": {
            "top_k_per_user": args.top_k_per_user,
            "negative_ratio": args.negative_ratio,
            "max_puzzles_per_user": args.max_puzzles_per_user,
            "min_gap_cp": args.min_gap_cp,
            "only_valid": not args.include_invalid,
        },
        "val": evaluate_classifier(model, X_val, y_val),
        "test": evaluate_classifier(model, X_test, y_test),
    }

    os.makedirs(args.output_dir, exist_ok=True)
    stem = f"personalized_puzzle_ranker_{args.model}"
    model_path = os.path.join(args.output_dir, f"{stem}.joblib")
    metrics_path = os.path.join(args.output_dir, f"{stem}_metrics.json")
    features_path = os.path.join(args.output_dir, f"{stem}_top_features.csv")
    predictions_path = os.path.join(args.output_dir, f"{stem}_predictions.csv")
    manifest_path = os.path.join(args.output_dir, f"{stem}_manifest.json")

    joblib.dump(model, model_path)
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    feature_imp = top_features(model, X_train, args.top_k_features)
    feature_imp.to_csv(features_path, index=False)

    preds = pd.concat(
        [
            prediction_frame(model, train_df).assign(split="train"),
            prediction_frame(model, val_df).assign(split="val"),
            prediction_frame(model, test_df).assign(split="test"),
        ],
        ignore_index=True,
    )
    preds.to_csv(predictions_path, index=False)

    manifest = {
        "feature_columns": FEATURE_COLUMNS,
        "meta_columns": META_COLUMNS,
        "model_path": model_path,
        "metrics_path": metrics_path,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("Personalized puzzle ranker training complete")
    print("-" * 60)
    print(f"Rows:        train={len(train_df)}  val={len(val_df)}  test={len(test_df)}")
    print(f"Players:     train={train_df['username'].nunique()}  val={val_df['username'].nunique()}  test={test_df['username'].nunique()}")
    print()
    print(f"Val accuracy:   {metrics['val']['accuracy']:.4f}")
    print(f"Val macro F1:   {metrics['val']['macro_f1']:.4f}")
    print(f"Val avg prec:   {metrics['val']['average_precision']:.4f}")
    if 'roc_auc' in metrics['val']:
        print(f"Val ROC AUC:    {metrics['val']['roc_auc']:.4f}")
    print(f"Test accuracy:  {metrics['test']['accuracy']:.4f}")
    print(f"Test macro F1:  {metrics['test']['macro_f1']:.4f}")
    print(f"Test avg prec:  {metrics['test']['average_precision']:.4f}")
    if 'roc_auc' in metrics['test']:
        print(f"Test ROC AUC:   {metrics['test']['roc_auc']:.4f}")
    print()
    print(f"Saved model:        {model_path}")
    print(f"Saved metrics:      {metrics_path}")
    print(f"Saved top features: {features_path}")
    print(f"Saved predictions:  {predictions_path}")


def load_profile(profiles: pd.DataFrame, username: str) -> pd.Series:
    wanted = username.strip().lower()
    mask = profiles["username"].astype(str).str.strip().str.lower() == wanted
    if not mask.any():
        raise ValueError(f"Username not found in profiles CSV: {username}")
    return profiles.loc[mask].iloc[0]


def recommend_mode(args: argparse.Namespace) -> None:
    profiles = _load_csv(args.profiles_csv)
    puzzles = _load_csv(args.puzzles_csv)
    puzzles = filter_puzzles(puzzles, only_valid=not args.include_invalid, min_gap_cp=args.min_gap_cp)
    profile = load_profile(profiles, args.username)
    model = joblib.load(args.model_path)

    pair_rows = [pair_features(profile, puzzle) for _, puzzle in puzzles.iterrows()]
    if not pair_rows:
        raise ValueError("No puzzles available for recommendation after filtering.")
    pair_df = pd.DataFrame(pair_rows)

    X = pair_df[FEATURE_COLUMNS]
    prob = model.predict_proba(X)[:, 1]
    pair_df["predicted_fit_probability"] = prob
    pair_df["predicted_rank_score"] = prob

    ranked = pair_df.sort_values(["predicted_rank_score", "heuristic_score"], ascending=False).reset_index(drop=True)
    if args.max_per_theme > 0:
        keep_rows: List[int] = []
        counts: Dict[str, int] = {}
        for idx, row in ranked.iterrows():
            theme = str(row.get("final_theme", "") or "")
            counts.setdefault(theme, 0)
            if counts[theme] >= args.max_per_theme:
                continue
            keep_rows.append(idx)
            counts[theme] += 1
            if args.top_n > 0 and len(keep_rows) >= args.top_n:
                break
        ranked = ranked.loc[keep_rows].reset_index(drop=True)
    elif args.top_n > 0:
        ranked = ranked.head(args.top_n).copy()

    preferred = [
        "username",
        "predicted_fit_probability",
        "predicted_rank_score",
        "heuristic_score",
        "recommendation_reason",
        "puzzle_id",
        "game_id",
        "final_theme",
        "difficulty_bucket",
        "puzzle__difficulty_score",
        "puzzle__phase",
        "puzzle__source_piece_type",
        "puzzle__best_vs_second_gap_cp",
        "puzzle__engine_best_move_uci",
    ]
    # restore raw puzzle columns alongside model outputs
    output_rows: List[Dict[str, Any]] = []
    for _, row in ranked.iterrows():
        out = {
            "recommended_for_username": args.username,
            "predicted_fit_probability": round(float(row["predicted_fit_probability"]), 6),
            "predicted_rank_score": round(float(row["predicted_rank_score"]), 6),
            "heuristic_score": round(float(row["heuristic_score"]), 6),
            "recommendation_reason": row["recommendation_reason"],
            "phase_match_score": round(float(row["phase_match_score"]), 4),
            "piece_match_score": round(float(row["piece_match_score"]), 4),
            "tactic_match_score": round(float(row["tactic_match_score"]), 4),
            "difficulty_fit_score": round(float(row["difficulty_fit_score"]), 4),
            "puzzle_id": row["puzzle_id"],
            "game_id": row["game_id"],
            "final_theme": row.get("final_theme", ""),
            "difficulty_bucket": row.get("difficulty_bucket", ""),
        }
        for col in PUZZLE_FEATURES_NUMERIC + PUZZLE_FEATURES_CATEGORICAL:
            out[col] = row.get(f"puzzle__{col}", "")
        output_rows.append(out)

    out_df = pd.DataFrame(output_rows)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    out_df.to_csv(args.output, index=False)

    print("Model-based personalized puzzle recommendations")
    print("-" * 60)
    print(f"Username: {args.username}")
    print(f"Recommended puzzles: {len(out_df):,}")
    if not out_df.empty:
        by_theme = out_df["final_theme"].fillna("").value_counts()
        print()
        print("By theme:")
        for theme, count in by_theme.items():
            print(f"  {theme:<20} {int(count):>8,}")
    print()
    print(f"Saved: {args.output}")


def main() -> None:
    args = parse_args()
    if args.mode == "train":
        train_mode(args)
    else:
        recommend_mode(args)


if __name__ == "__main__":
    main()
