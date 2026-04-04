# ── settings.py ──────────────────────────────────────────────────────────────
# All configuration lives here. Edit this file to change behaviour.
# ─────────────────────────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env into os.environ

# Lichess API token
LICHESS_TOKEN = os.getenv("LICHESS_TOKEN")
# ── Exact collection targets ─────────────────────────────────────────────────
# Each accepted player must contribute EXACTLY this many valid kept games.
# A valid game is one that survives the parser filters below.
EXACT_GAMES_PER_PLAYER = 100

# Fetch more than EXACT_GAMES_PER_PLAYER so players still qualify after filters.
RAW_GAMES_TO_FETCH_PER_PLAYER = 300

# Ask the sampler for more candidate usernames than the final bucket target.
# This is necessary because many candidates will not have enough valid games.
CANDIDATE_PLAYERS_PER_BUCKET = 700

# How many recent tournaments to scan while searching for candidate players.
TOURNAMENTS_TO_SCAN = 150

# ── Bucket targets ───────────────────────────────────────────────────────────
# (min_elo, max_elo, exact_num_players_to_keep)
ELO_BUCKETS = [
    (1000, 1400, 100),
    (1400, 1600, 100),
    (1600, 1800, 100),
    (1800, 2000, 100),
    (2000, 2200, 100),
]

# ── Legacy / optional collection parameters ─────────────────────────────────
# Still used by some helper methods / CLI flows.
MAX_GAMES_PER_PLAYER = EXACT_GAMES_PER_PLAYER
MAX_PLAYERS = sum(target for _, _, target in ELO_BUCKETS)

# Only keep games in these speed and variants categories
ALLOWED_SPEEDS = {"blitz", "rapid", "classical", "bullet"}
ALLOWED_VARIANTS = {"standard"}

# Drop games with fewer than this many half-moves (plies)
MIN_PLIES = 10

# Seconds to wait between API calls (stay within Lichess rate limits)
API_DELAY = 0.5

# ── Move quality thresholds (centipawns) ─────────────────────────────────────
# A move is "Good" if cp_loss < INACCURACY
# "Inaccuracy"  if INACCURACY <= cp_loss < MISTAKE
# "Mistake"     if MISTAKE <= cp_loss < BLUNDER
# "Blunder"     if cp_loss >= BLUNDER
INACCURACY_THRESHOLD = 50
MISTAKE_THRESHOLD = 100
BLUNDER_THRESHOLD = 200

# ── Output ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"

# Leaderboard variants to pull players from
LEADERBOARD_VARIANTS = ["bullet", "blitz", "rapid", "classical"]
