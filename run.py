<<<<<<< HEAD
=======
#!/usr/bin/env python3
# ── run.py ────────────────────────────────────────────────────────────────────
# Entry point. Run this file to start collecting data.
#
# Usage:
#   python run.py                              # uses defaults from settings.py
#   python run.py --games 20                   # override games per player
#   python run.py --usernames EricRosen Naroditsky  # specific players only
#
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
# Output (written to OUTPUT_DIR defined in settings.py):
#   players.csv  – one row per player
#   games.csv    – one row per game
#   moves.csv    – one row per half-move (ply)
#   summary.csv  – one row per (player x game), aggregated quality stats
<<<<<<< HEAD
=======
# ─────────────────────────────────────────────────────────────────────────────
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45

import argparse
import logging
import os
import time
from datetime import datetime
<<<<<<< HEAD
from typing import List, Optional, Tuple

from settings import (
    API_DELAY,
    CANDIDATE_PLAYERS_PER_BUCKET,
    ELO_BUCKETS,
    EXACT_GAMES_PER_PLAYER,
    LICHESS_API_TOKEN,
    OUTPUT_DIR,
    RAW_GAMES_TO_FETCH_PER_PLAYER,
    TOURNAMENTS_TO_SCAN,
=======
from typing import List, Tuple, Optional

from settings import (
    LICHESS_API_TOKEN,
    MAX_GAMES_PER_PLAYER,
    API_DELAY,
    OUTPUT_DIR,
    ELO_BUCKETS,
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
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

<<<<<<< HEAD
def process_player_exact(
    client: LichessClient,
    username: str,
    raw_games_to_fetch: int,
    exact_games_required: int,
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    Fetch more raw games than needed, keep only valid parsed games, and accept the
    player only if they end up with at least `exact_games_required` valid games.

    Returns exactly `exact_games_required` games/summaries for accepted players.
    Returns empty lists for rejected players.
    """
    game_rows: List[dict] = []
    move_rows: List[dict] = []
    summary_rows: List[dict] = []

    time.sleep(API_DELAY)
    raw_games = client.get_analysed_games(username, raw_games_to_fetch)

    if not raw_games:
        logger.info(f"  {username}: no analysed games found")
        return [], [], []

    for raw in raw_games:
        g_row, m_rows, s_row = parse_game(raw, username)
        if not g_row or not s_row:
            continue

        game_rows.append(g_row)
        move_rows.extend(m_rows)
        summary_rows.append(s_row)

        if len(game_rows) == exact_games_required:
            logger.info(
                f"  {username}: accepted with exactly {len(game_rows)} valid games "
                f"from {len(raw_games)} raw fetched games"
            )
            return game_rows, move_rows, summary_rows

    logger.info(
        f"  {username}: rejected ({len(game_rows)}/{exact_games_required} valid games "
        f"from {len(raw_games)} raw fetched games)"
    )
    return [], [], []


def get_player_elo_from_games(game_rows: List[dict]) -> Optional[int]:
=======
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
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
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
<<<<<<< HEAD
    write_games(all_games, os.path.join(out_dir, f"games_{tag}.csv"))
    write_moves(all_moves, os.path.join(out_dir, f"moves_{tag}.csv"))
    write_summary(all_summaries, os.path.join(out_dir, f"summary_{tag}.csv"))
    write_players(all_players, os.path.join(out_dir, f"players_{tag}.csv"))


def _bucket_label(min_elo: int, max_elo: int, include_max: bool) -> str:
    return f"{min_elo}-{max_elo}" if include_max else f"{min_elo}-{max_elo-1}"


def _collect_bucket_exact(
    client: LichessClient,
    min_elo: int,
    max_elo: int,
    target_players: int,
    raw_games_to_fetch: int,
    exact_games_required: int,
    candidate_pool_size: int,
    tournaments_to_scan: int,
    include_max: bool,
    global_seen: set,
) -> Tuple[List[dict], List[dict], List[dict], List[dict]]:
    """
    Collect exactly `target_players` accepted players for one ELO bucket.
    Raises RuntimeError if the quota cannot be met.
    """
    bucket_name = _bucket_label(min_elo, max_elo, include_max)
    logger.info(
        f"Fetching {candidate_pool_size} candidate players for bucket {bucket_name} "
        f"(target accepted players: {target_players})"
    )

    candidates = client.get_players_by_elo_range(
        min_elo,
        max_elo,
        candidate_pool_size,
        include_max=include_max,
        tournaments_to_scan=tournaments_to_scan,
    )
    logger.info(f"  got {len(candidates)} candidate usernames for bucket {bucket_name}")

    bucket_games: List[dict] = []
    bucket_moves: List[dict] = []
    bucket_summaries: List[dict] = []
    bucket_players: List[dict] = []

    for candidate_idx, username in enumerate(candidates, start=1):
        if len(bucket_players) >= target_players:
            break
        if username in global_seen:
            continue

        global_seen.add(username)
        logger.info(
            f"[{bucket_name}] candidate {candidate_idx}/{len(candidates)} -> {username} "
            f"(accepted so far: {len(bucket_players)}/{target_players})"
        )

        g_rows, m_rows, s_rows = process_player_exact(
            client=client,
            username=username,
            raw_games_to_fetch=raw_games_to_fetch,
            exact_games_required=exact_games_required,
        )
        if not g_rows:
            continue

        elo = get_player_elo_from_games(g_rows)
        player_row = build_player_row(username, elo, bucket_name, s_rows)
        if not player_row:
            continue

        bucket_games.extend(g_rows)
        bucket_moves.extend(m_rows)
        bucket_summaries.extend(s_rows)
        bucket_players.append(player_row)

    if len(bucket_players) != target_players:
        raise RuntimeError(
            f"Bucket {bucket_name}: needed exactly {target_players} accepted players, "
            f"but only found {len(bucket_players)}. Increase "
            f"CANDIDATE_PLAYERS_PER_BUCKET, RAW_GAMES_TO_FETCH_PER_PLAYER, or "
            f"TOURNAMENTS_TO_SCAN."
        )

    logger.info(
        f"Bucket {bucket_name} complete: {len(bucket_players)} players, "
        f"{len(bucket_games)} games"
    )
    return bucket_games, bucket_moves, bucket_summaries, bucket_players
=======
    write_games(all_games,       os.path.join(out_dir, f"games_{tag}.csv"))
    write_moves(all_moves,       os.path.join(out_dir, f"moves_{tag}.csv"))
    write_summary(all_summaries, os.path.join(out_dir, f"summary_{tag}.csv"))
    write_players(all_players,   os.path.join(out_dir, f"players_{tag}.csv"))
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
<<<<<<< HEAD
    parser = argparse.ArgumentParser(description="Lichess data collector (exact quotas)")
    parser.add_argument(
        "--games",
        type=int,
        default=EXACT_GAMES_PER_PLAYER,
        help="Exact number of valid kept games required per accepted player",
    )
    parser.add_argument(
        "--raw-games",
        type=int,
        default=RAW_GAMES_TO_FETCH_PER_PLAYER,
        help="Number of raw analysed games to fetch per candidate player",
    )
    parser.add_argument(
        "--candidate-players",
        type=int,
        default=CANDIDATE_PLAYERS_PER_BUCKET,
        help="How many candidate usernames to sample per ELO bucket before filtering",
    )
    parser.add_argument(
        "--tournaments-to-scan",
        type=int,
        default=TOURNAMENTS_TO_SCAN,
        help="How many recent tournaments to scan while building candidate pools",
    )
    parser.add_argument(
        "--usernames",
        nargs="+",
        default=None,
        help="Collect specific players instead of ELO bucket sampling",
    )
=======
    parser = argparse.ArgumentParser(description="Lichess data collector")
    parser.add_argument("--games",      type=int, default=MAX_GAMES_PER_PLAYER,
                        help="Max analysed games per player")
    parser.add_argument("--usernames",  nargs="+", default=None,
                        help="Collect specific players instead of ELO bucket sampling")
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
    parser.add_argument("--output-dir", type=str, default=OUTPUT_DIR)
    args = parser.parse_args()

    if not LICHESS_API_TOKEN:
        raise RuntimeError(
            "Missing LICHESS_API_TOKEN. Set it in your environment before running."
        )

    os.makedirs(args.output_dir, exist_ok=True)
    client = LichessClient(LICHESS_API_TOKEN)

<<<<<<< HEAD
    all_games: List[dict] = []
    all_moves: List[dict] = []
    all_summaries: List[dict] = []
    all_players: List[dict] = []
    start = datetime.now()

    if args.usernames:
        logger.info(f"Mode: specific players -> {args.usernames}")
        for idx, username in enumerate(args.usernames, start=1):
            logger.info(f"[{idx}/{len(args.usernames)}] {username}")
            g_rows, m_rows, s_rows = process_player_exact(
                client=client,
                username=username,
                raw_games_to_fetch=args.raw_games,
                exact_games_required=args.games,
            )
            if not g_rows:
                raise RuntimeError(
                    f"Player {username} does not have {args.games} valid kept games "
                    f"under the current filters."
                )
            elo = get_player_elo_from_games(g_rows)
            player_row = build_player_row(username, elo, "manual", s_rows)
            if not player_row:
                raise RuntimeError(f"Failed to build player row for {username}")

            all_games.extend(g_rows)
            all_moves.extend(m_rows)
            all_summaries.extend(s_rows)
            all_players.append(player_row)
    else:
        logger.info("Mode: exact ELO bucket collection")
        global_seen = set()
        last_bucket_idx = len(ELO_BUCKETS) - 1

        for bucket_idx, (min_elo, max_elo, target_players) in enumerate(ELO_BUCKETS):
            include_max = bucket_idx == last_bucket_idx
            b_games, b_moves, b_summaries, b_players = _collect_bucket_exact(
                client=client,
                min_elo=min_elo,
                max_elo=max_elo,
                target_players=target_players,
                raw_games_to_fetch=args.raw_games,
                exact_games_required=args.games,
                candidate_pool_size=args.candidate_players,
                tournaments_to_scan=args.tournaments_to_scan,
                include_max=include_max,
                global_seen=global_seen,
            )
            all_games.extend(b_games)
            all_moves.extend(b_moves)
            all_summaries.extend(b_summaries)
            all_players.extend(b_players)

            _checkpoint(
                all_games,
                all_moves,
                all_summaries,
                all_players,
                args.output_dir,
                f"bucket_{bucket_idx + 1}",
            )
            logger.info(f"Checkpoint saved after bucket {bucket_idx + 1}")

    write_players(all_players, os.path.join(args.output_dir, "players.csv"))
    write_games(all_games, os.path.join(args.output_dir, "games.csv"))
    write_moves(all_moves, os.path.join(args.output_dir, "moves.csv"))
=======
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
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
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
<<<<<<< HEAD
    main()
=======
    main()
>>>>>>> c6755a2ef400be25159790161acbe118d43a1e45
