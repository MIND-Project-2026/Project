from __future__ import annotations
import pandas as pd

REQUIRED_COLUMNS = ["phase","piece_type","move_quality"]

def validate_history_csv(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception as exc:
        return False, f"CSV invalide : {exc}", None
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        return False, f"Colonnes manquantes : {', '.join(missing)}", None
    for col in ["is_capture","is_check","is_castle","is_promotion"]:
        if col not in df.columns: df[col] = False
    if "clock_before_cs" not in df.columns: df["clock_before_cs"] = 5000
    return True, "CSV valide", df
