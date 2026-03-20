# ── settings.py ──────────────────────────────────────────────────────────────
# All configuration lives here. Edit this file to change behaviour.
# ─────────────────────────────────────────────────────────────────────────────

# Lichess API token (paste yours here)
import os
from dotenv import load_dotenv

load_dotenv()  # This loads the variables from .env into os.environ

token = os.getenv("LICHESS_API_TOKEN")
# ── Collection parameters ─────────────────────────────────────────────────────
MAX_GAMES_PER_PLAYER = 30       # how many games to fetch per player
MAX_PLAYERS          = 1000     # how many players to collect from leaderboards

# Only keep games in these speed and variants categories
ALLOWED_SPEEDS = {"blitz", "rapid"}
ALLOWED_VARIANTS = {"standard"}

# Drop games with fewer than this many half-moves (plies)
MIN_PLIES = 10

# Seconds to wait between API calls (stay within Lichess rate limits)
API_DELAY = 0.5

# ELO range buckets to sample from (for puzzle generation diversity)
ELO_BUCKETS = [
    (1000, 1400, 200),   # (min, max, num_players)
    (1400, 1600, 200),
    (1600, 1800, 200),
    (1800, 2000, 200),
    (2000, 2200, 200),
]

# ── Move quality thresholds (centipawns) ──────────────────────────────────────
# A move is "Good" if cp_loss < INACCURACY
# "Inaccuracy"  if INACCURACY  <= cp_loss < MISTAKE
# "Mistake"     if MISTAKE     <= cp_loss < BLUNDER
# "Blunder"     if cp_loss    >= BLUNDER
INACCURACY_THRESHOLD = 50
MISTAKE_THRESHOLD    = 100
BLUNDER_THRESHOLD    = 200

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"

# Leaderboard variants to pull players from
LEADERBOARD_VARIANTS = ["bullet", "blitz", "rapid", "classical"]
