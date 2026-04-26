# Configuration settings
import os
from dotenv import load_dotenv

load_dotenv()  # Load env vars from .env

LICHESS_API_TOKEN = os.getenv("LICHESS_API_TOKEN")

# Collection parameters
MAX_GAMES_PER_PLAYER = 30
MAX_PLAYERS = 1000

# Only keep games in these speed and variants categories
ALLOWED_SPEEDS = {"blitz", "rapid"}
ALLOWED_VARIANTS = {"standard"}

# Drop games with fewer than this many half-moves (plies)
MIN_PLIES = 10

# Rate limit delay (seconds between API calls)
API_DELAY = 0.5

# ELO buckets for player sampling
ELO_BUCKETS = [
    (1000, 1400, 200),
    (1400, 1600, 200),
    (1600, 1800, 200),
    (1800, 2000, 200),
    (2000, 2200, 200),
]

# Move quality thresholds (centipawns)
# Good: < INACCURACY, Inaccuracy: < MISTAKE, Mistake: < BLUNDER, Blunder: >= BLUNDER
INACCURACY_THRESHOLD = 50
MISTAKE_THRESHOLD = 100
BLUNDER_THRESHOLD = 200

# Output
OUTPUT_DIR = "output"

# Leaderboard variants to pull players from
LEADERBOARD_VARIANTS = ["bullet", "blitz", "rapid", "classical"]
