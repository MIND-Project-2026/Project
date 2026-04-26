import json
import time
import logging
from typing import List

import requests

from settings import API_DELAY, LEADERBOARD_VARIANTS, TOURNAMENTS_TO_SCAN

logger = logging.getLogger(__name__)

LICHESS_BASE = "https://lichess.org/api"


class LichessClient:
    """Small Lichess API client."""

    def __init__(self, api_token: str):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_token}"

    def get_top_players(self, variant: str, count: int = 200) -> List[str]:
        """Get top usernames for one variant."""
        url = f"{LICHESS_BASE}/player/top/{count}/{variant}"
        try:
            r = self.session.get(url, headers={"Accept": "application/json"})
            r.raise_for_status()
            return [p["username"] for p in r.json().get("users", [])]
        except Exception as e:
            logger.error(f"get_top_players({variant}): {e}")
            return []

    def get_leaderboard_players(self, max_players: int) -> List[str]:
        """Get unique players from leaderboards."""
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

    def get_analysed_games(self, username: str, max_games: int) -> List[dict]:
        """Get analysed games for one user."""
        url = f"{LICHESS_BASE}/games/user/{username}"
        params = {
            "max": max_games,
            "rated": "true",
            "analysed": "true",
            "evals": "true",
            "clocks": "true",
            "opening": "true",
            "pgnInJson": "true",
        }
        headers = {**self.session.headers, "Accept": "application/x-ndjson"}

        for attempt in range(1, 4):
            response = None
            try:
                response = self.session.get(
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
                    time.sleep(65)
                    continue

                response.raise_for_status()

                games = []
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    game = json.loads(line)
                    if "analysis" in game:
                        games.append(game)
                return games

            except (
                requests.exceptions.ReadTimeout,
                requests.exceptions.ChunkedEncodingError,
            ) as e:
                logger.warning(f"Stream error on {username} (attempt {attempt}/3): {e}")
                time.sleep(2 * attempt)
            except Exception as e:
                logger.error(f"get_analysed_games({username}): {e}")
                break
            finally:
                if response is not None:
                    response.close()

        return []

    def get_recent_tournament_ids(self, count: int = TOURNAMENTS_TO_SCAN) -> List[str]:
        """Get recent finished arena IDs."""
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

    def get_players_by_elo_range(
        self,
        min_elo: int,
        max_elo: int,
        count: int,
        *,
        include_max: bool = True,
        tournaments_to_scan: int = TOURNAMENTS_TO_SCAN,
    ) -> List[str]:
        """Get tournament players in an Elo range."""
        tournament_ids = self.get_recent_tournament_ids(count=tournaments_to_scan)
        result = []
        seen = set()

        for tid in tournament_ids:
            if len(result) >= count:
                break

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
