# ── core/api.py ───────────────────────────────────────────────────────────────
# Handles all communication with the Lichess REST API.
# Nothing in here knows about CSV files or chess logic.
# ─────────────────────────────────────────────────────────────────────────────

import json
import time
import logging
<<<<<<< HEAD
from typing import List

import requests

from settings import API_DELAY, LEADERBOARD_VARIANTS, TOURNAMENTS_TO_SCAN
=======
from typing import List, Optional

import requests

from settings import API_DELAY, LEADERBOARD_VARIANTS
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45

logger = logging.getLogger(__name__)

LICHESS_BASE = "https://lichess.org/api"


class LichessClient:
    """
    Thin wrapper around the Lichess HTTP API.
    All methods return plain Python dicts / lists (no chess logic here).
    """

    def __init__(self, api_token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_token}"

    # ── Players ───────────────────────────────────────────────────────────────

    def get_top_players(self, variant: str, count: int = 200) -> List[str]:
        """Return up to `count` usernames from the leaderboard of `variant`."""
        url = f"{LICHESS_BASE}/player/top/{count}/{variant}"
        try:
            r = self.session.get(url, headers={"Accept": "application/json"})
            r.raise_for_status()
            return [p["username"] for p in r.json().get("users", [])]
        except Exception as e:
            logger.error(f"get_top_players({variant}): {e}")
            return []

    def get_leaderboard_players(self, max_players: int) -> List[str]:
        """
        Collect usernames from all leaderboard variants, deduplicated.
        Returns at most `max_players` usernames.
        """
        seen = set()
        players = []
        per_variant = min(200, max_players // len(LEADERBOARD_VARIANTS) + 100)

        for variant in LEADERBOARD_VARIANTS:
            for username in self.get_top_players(variant, per_variant):
                if username not in seen:
                    seen.add(username)
                    players.append(username)
            time.sleep(API_DELAY)
            logger.info(f"  leaderboard {variant}: {len(seen)} unique players so far")

        return players[:max_players]

    # ── Games ─────────────────────────────────────────────────────────────────

    def get_analysed_games(self, username: str, max_games: int) -> List[dict]:
        """
        Fetch up to `max_games` Lichess-analysed games for `username`.
        Only returns games that have an `analysis` field (cloud evals included).
        Handles HTTP 429 rate-limit with an automatic 65-second retry.
        """
        url = f"{LICHESS_BASE}/games/user/{username}"
        params = {
<<<<<<< HEAD
            "max": max_games,
            "rated": "true",
            "analysed": "true",   # only pre-analysed games
            "evals": "true",      # include per-move evaluations
            "clocks": "true",     # include clock times
            "opening": "true",    # include opening name / ECO
            "pgnInJson": "true",
=======
            "max":        max_games,
            "rated":      "true",
            "analysed":   "true",   # only pre-analysed games
            "evals":      "true",   # include per-move evaluations
            "clocks":     "true",   # include clock times
            "opening":    "true",   # include opening name / ECO
            "pgnInJson":  "true",
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
        }
        headers = {**self.session.headers, "Accept": "application/x-ndjson"}

        for attempt in range(1, 4):
            response = None
            try:
                response = self.session.get(
<<<<<<< HEAD
                    url,
                    params=params,
                    headers=headers,
                    stream=True,
                    timeout=(10, 180),
                )

                if response.status_code == 429:
                    logger.warning(
                        f"Rate limited on {username} (attempt {attempt}/3). Waiting 65s…"
                    )
=======
                    url, params=params, headers=headers,
                    stream=True, timeout=(10, 180),
                )

                if response.status_code == 429:
                    logger.warning(f"Rate limited on {username} (attempt {attempt}/3). Waiting 65s…")
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
                    time.sleep(65)
                    continue

                response.raise_for_status()

                games = []
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    game = json.loads(line)
<<<<<<< HEAD
                    if "analysis" in game:
                        games.append(game)
                return games

            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
=======
                    if "analysis" in game:   # drop games without evals
                        games.append(game)
                return games

            except (requests.exceptions.ReadTimeout,
                    requests.exceptions.ChunkedEncodingError) as e:
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
                logger.warning(f"Stream error on {username} (attempt {attempt}/3): {e}")
                time.sleep(2 * attempt)
            except Exception as e:
                logger.error(f"get_analysed_games({username}): {e}")
                break
            finally:
                if response is not None:
                    response.close()

        return []

<<<<<<< HEAD
    def get_recent_tournament_ids(self, count: int = TOURNAMENTS_TO_SCAN) -> List[str]:
=======
    def get_recent_tournament_ids(self, count: int = 20) -> List[str]:
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
        """Get IDs of recently finished arena tournaments."""
        url = f"{LICHESS_BASE}/tournament"
        try:
            r = self.session.get(url, headers={"Accept": "application/json"})
            r.raise_for_status()
            data = r.json()
            finished = data.get("finished", [])
            return [t["id"] for t in finished[:count]]
        except Exception as e:
            logger.error(f"get_recent_tournament_ids: {e}")
            return []

<<<<<<< HEAD
    def get_players_by_elo_range(
        self,
        min_elo: int,
        max_elo: int,
        count: int,
        *,
        include_max: bool = True,
        tournaments_to_scan: int = TOURNAMENTS_TO_SCAN,
    ) -> List[str]:
        """
        Get candidate players within an ELO range by scanning recent arena tournament
        results. Tournament results include username + rating for every participant.

        Use include_max=False for half-open buckets such as [1400, 1600), which avoids
        duplicate edge ratings appearing in two adjacent buckets.
        """
        tournament_ids = self.get_recent_tournament_ids(count=tournaments_to_scan)
=======
    def get_players_by_elo_range(self, min_elo: int, max_elo: int, count: int) -> List[str]:
        """
        Get players within an ELO range by scanning recent arena tournament results.
        Tournament results include username + rating for every participant.
        """
        tournament_ids = self.get_recent_tournament_ids(count=30)
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
        result = []
        seen = set()

        for tid in tournament_ids:
            if len(result) >= count:
                break
<<<<<<< HEAD

=======
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
            url = f"{LICHESS_BASE}/tournament/{tid}/results"
            try:
                r = self.session.get(
                    url,
                    params={"nb": 500},
                    headers={"Accept": "application/x-ndjson"},
                    stream=True,
                    timeout=(10, 30),
                )
                r.raise_for_status()
<<<<<<< HEAD

                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue

                    player = json.loads(line)
                    username = player.get("username", "")
                    rating = player.get("rating")
                    if not username or rating is None or username in seen:
                        continue

                    in_bucket = (
                        min_elo <= rating <= max_elo
                        if include_max
                        else min_elo <= rating < max_elo
                    )
                    if not in_bucket:
                        continue

                    seen.add(username)
                    result.append(username)
                    if len(result) >= count:
                        break

            except Exception as e:
                logger.error(f"tournament results ({tid}): {e}")

            time.sleep(API_DELAY)

        return result
=======
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    player = json.loads(line)
                    username = player.get("username", "")
                    rating = player.get("rating")
                    if username and rating and username not in seen:
                        if min_elo <= rating <= max_elo:
                            seen.add(username)
                            result.append(username)
                            if len(result) >= count:
                                break
            except Exception as e:
                logger.error(f"tournament results ({tid}): {e}")
            time.sleep(API_DELAY)

        return result
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
