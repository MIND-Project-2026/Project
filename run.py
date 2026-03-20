#!/usr/bin/env python3
# ── run.py ────────────────────────────────────────────────────────────────────
# Entry point. Run this file to start collecting data.
#
# Usage:
#   python run.py                              # uses defaults from settings.py
#   python run.py --games 20                   # override games per player
#   python run.py --usernames EricRosen Naroditsky  # specific players only
#
# Output (written to OUTPUT_DIR defined in settings.py):
#   players.csv  – one row per player
#   games.csv    – one row per game
#   moves.csv    – one row per half-move (ply)
#   summary.csv  – one row per (player x game), aggregated quality stats
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import logging
import os
import time
from datetime import datetime
from typing import List, Tuple, Optional

from settings import (
    LICHESS_API_TOKEN,
    MAX_GAMES_PER_PLAYER,
    API_DELAY,
    OUTPUT_DIR,
    ELO_BUCKETS,
)
from api import LichessClient
from parser import parse_game, build_player_row
from writer import write_games, write_moves, write_summary, write_players

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Per-player processing ─────────────────────────────────────────────────────

def process_player(
    client: LichessClient,
    username: str,
    max_games: int,
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Fetch and parse all analysed games for one player.
    Returns (game_rows, move_rows, summary_rows).
    """
    game_rows, move_rows, summary_rows = [], [], []

    time.sleep(API_DELAY)
    raw_games = client.get_analysed_games(username, max_games)

    if not raw_games:
        logger.info(f"  {username}: no analysed games found")
        return game_rows, move_rows, summary_rows

    for raw in raw_games:
        g_row, m_rows, s_row = parse_game(raw, username)
        if g_row:
            game_rows.append(g_row)
        move_rows.extend(m_rows)
        if s_row:
            summary_rows.append(s_row)

    logger.info(
        f"  {username}: {len(game_rows)} games  |  "
        f"{len(move_rows)} plies  |  "
        f"{len(summary_rows)} summaries"
    )
    return game_rows, move_rows, summary_rows


def get_player_elo_from_games(username: str, game_rows: List[dict]) -> Optional[int]:
    """Extract the player's most recent ELO from their collected games."""
    for game in game_rows:
        elo = game.get("target_elo")
        if elo:
            try:
                return int(elo)
            except (ValueError, TypeError):
                continue
    return None


# ── Checkpoint helper ─────────────────────────────────────────────────────────

def _checkpoint(all_games, all_moves, all_summaries, all_players, out_dir: str, tag: str):
    write_games(all_games,       os.path.join(out_dir, f"games_{tag}.csv"))
    write_moves(all_moves,       os.path.join(out_dir, f"moves_{tag}.csv"))
    write_summary(all_summaries, os.path.join(out_dir, f"summary_{tag}.csv"))
    write_players(all_players,   os.path.join(out_dir, f"players_{tag}.csv"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Lichess data collector")
    parser.add_argument("--games",      type=int, default=MAX_GAMES_PER_PLAYER,
                        help="Max analysed games per player")
    parser.add_argument("--usernames",  nargs="+", default=None,
                        help="Collect specific players instead of ELO bucket sampling")
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR)
    args = parser.parse_args()

    if not LICHESS_API_TOKEN:
        raise RuntimeError(
            "Missing LICHESS_API_TOKEN. Set it in your environment before running."
        )

    os.makedirs(args.output_dir, exist_ok=True)
    client = LichessClient(LICHESS_API_TOKEN)

    # ── Decide which players to process ──────────────────────────────────────
    # players_with_meta: list of (username, elo_bucket_label)
    players_with_meta: List[Tuple[str, str]] = []

    if args.usernames:
        logger.info(f"Mode: specific players -> {args.usernames}")
        for username in args.usernames:
            players_with_meta.append((username, "manual"))
    else:
        logger.info("Mode: ELO bucket sampling")
        seen = set()
        for min_elo, max_elo, count in ELO_BUCKETS:
            bucket_label = f"{min_elo}-{max_elo}"
            logger.info(f"Fetching players ELO {bucket_label}...")
            bucket_players = client.get_players_by_elo_range(min_elo, max_elo, count)
            added = 0
            for username in bucket_players:
                if username not in seen:
                    seen.add(username)
                    players_with_meta.append((username, bucket_label))
                    added += 1
            logger.info(f"  got {added} unique players")
        logger.info(f"Total unique players: {len(players_with_meta)}")

    # ── Process ───────────────────────────────────────────────────────────────
    all_games, all_moves, all_summaries, all_players = [], [], [], []
    start = datetime.now()

    for i, (username, elo_bucket) in enumerate(players_with_meta):
        logger.info(f"[{i+1}/{len(players_with_meta)}] {username}  (bucket: {elo_bucket})")

        g, m, s = process_player(client, username, args.games)
        all_games.extend(g)
        all_moves.extend(m)
        all_summaries.extend(s)

        # build player row
        elo = get_player_elo_from_games(username, g)
        player_row = build_player_row(username, elo, elo_bucket, s)
        if player_row:
            all_players.append(player_row)

        # checkpoint every 100 players
        if (i + 1) % 100 == 0:
            _checkpoint(all_games, all_moves, all_summaries, all_players,
                        args.output_dir, f"checkpoint_{i+1}")
            logger.info(f"  checkpoint saved at player {i+1}")

    # ── Final save ────────────────────────────────────────────────────────────
    write_players(all_players,   os.path.join(args.output_dir, "players.csv"))
    write_games(all_games,       os.path.join(args.output_dir, "games.csv"))
    write_moves(all_moves,       os.path.join(args.output_dir, "moves.csv"))
    write_summary(all_summaries, os.path.join(args.output_dir, "summary.csv"))

    duration = datetime.now() - start
    logger.info("-" * 60)
    logger.info(f"Done in {duration}")
    logger.info(f"  Players:   {len(all_players):,}")
    logger.info(f"  Games:     {len(all_games):,}")
    logger.info(f"  Plies:     {len(all_moves):,}")
    logger.info(f"  Summaries: {len(all_summaries):,}")
    logger.info(f"  Output:    {args.output_dir}/")


if __name__ == "__main__":
    main()