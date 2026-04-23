from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import requests

USER_URL = "https://lichess.org/api/user/{username}"
GAMES_URL = "https://lichess.org/api/games/user/{username}"


def check_lichess_username(username: str) -> Tuple[bool, str]:
    username = (username or "").strip()
    if not username:
        return False, "Pseudo vide"
    try:
        response = requests.get(USER_URL.format(username=username), timeout=12)
        if response.status_code == 200:
            return True, "Pseudo trouvé"
        if response.status_code == 404:
            return False, "Pseudo introuvable"
        return False, f"Erreur Lichess ({response.status_code})"
    except Exception as exc:
        return False, f"Impossible de contacter Lichess: {exc}"


def fetch_games_as_pgn(username: str, max_games: int = 20) -> Tuple[List[Dict[str, Any]], str]:
    """
    Kept for UI compatibility: despite the historical name, this now returns
    raw analysed Lichess game JSON rows, not PGN objects.

    That lets the Streamlit demo reuse the real profile-construction logic
    (cp loss, move quality, phase/piece/tactic statistics) instead of the old
    lightweight PGN-only heuristic.
    """
    username = (username or "").strip()
    if not username:
        return [], "Pseudo vide"

    params = {
        "max": int(max_games),
        "rated": "true",
        "analysed": "true",
        "evals": "true",
        "clocks": "true",
        "opening": "true",
        "pgnInJson": "true",
    }
    headers = {"Accept": "application/x-ndjson"}

    try:
        response = requests.get(
            GAMES_URL.format(username=username),
            params=params,
            headers=headers,
            timeout=(12, 90),
            stream=True,
        )
        if response.status_code != 200:
            return [], f"Erreur Lichess ({response.status_code})"

        games: List[Dict[str, Any]] = []
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            game = json.loads(line)
            if "analysis" not in game:
                continue
            games.append(game)

        if not games:
            return [], "Aucune partie analysée exploitable renvoyée"
        return games, f"{len(games)} parties analysées récupérées"
    except Exception as exc:
        return [], f"Impossible de récupérer les parties: {exc}"