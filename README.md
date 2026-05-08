# Chess Trainer Complete

A personalized chess puzzle training application that builds a weakness profile from your Lichess game history and recommends targeted puzzles — ranked by machine learning — to address your specific errors.

---

## Overview

Most chess puzzle platforms serve generic tactics. Chess Trainer is different: it analyzes your actual games, identifies where and how you make mistakes across multiple dimensions, and ranks a puzzle library by predicted fit for *your* specific weaknesses. Every recommendation is explainable — you see exactly why each puzzle was chosen for you.

The system has five layers:

1. **Game collection** — fetch analysed games from Lichess with engine evaluations
2. **Weakness profiling** — compute error patterns across phase, piece, tactic, and time pressure
3. **Puzzle mining** — extract candidate positions from your mistakes
4. **Puzzle validation** — filter candidates with Stockfish to ensure clean, unambiguous puzzles
5. **Personalized ranking** — score every puzzle for every player using a trained RandomForest model

---

## Architecture

```
lichess API
    │
    ▼
run.py / lichess_logic.py          ← data collection
    │
    ▼
parser.py / chess_utils.py         ← per-ply parsing: FEN, cp_loss, quality, clocks
    │
    ├──► games.csv
    ├──► moves.csv
    └──► summary.csv
         │
         ├──► mine_puzzle_candidates.py    ← extract positions from mistakes
         │         │
         │         ▼
         │    puzzle_candidates.csv
         │         │
         │         ▼
         │    validate_puzzle_candidates.py  ← Stockfish validation
         │         │
         │         ▼
         │    puzzles_validated.csv
         │         │
         │         ▼
         │    build_final_puzzle_dataset.py  ← theme labels, difficulty scores
         │         │
         │         ▼
         │    puzzles_final.csv  ←────────────────────────────────────┐
         │                                                             │
         └──► build_player_weakness_profile.py                        │
                   │                                                   │
                   ▼                                                   │
         player_weakness_profiles.csv                                  │
                   │                                                   │
                   └──► personalized_puzzle_ranker.py  ───────────────┘
                                   │
                                   ▼
                         trained model (.joblib)
                                   │
                                   ▼
                               app.py  (Streamlit UI)
```

---

## Features

### Player profiling
- Fetches up to 50 analysed Lichess games per player
- Computes centipawn loss, move quality (Good / Inaccuracy / Mistake / Blunder), and error rates across:
  - **Game phase**: opening, middlegame, endgame
  - **Piece type**: Pawn, Knight, Bishop, Rook, Queen, King
  - **Tactical motif**: capture, check, castle, promotion, quiet moves
  - **Time pressure**: moves played with ≤30 seconds on the clock vs. normal time
- Produces a normalized weakness score per dimension (ratio vs. overall baseline)
- Identifies primary weak phase, piece, and tactic
- Recommends a difficulty bucket (easy / medium / hard / expert)

### Puzzle mining
- Scans `moves.csv` for Mistake/Blunder moves (configurable `--min-cp-loss`)
- Takes the opponent's next ply as the candidate puzzle position
- Tags each candidate with: theme guess, solution UCI/SAN, tactical flags, source game metadata

### Stockfish validation (`validate_puzzle_candidates.py`)
- Runs MultiPV analysis at configurable depth (default: depth 16, 2 lines)
- Accepts puzzles that meet at least one of:
  - Forced mate within N plies
  - Clear best move with centipawn gap ≥ threshold over second-best
  - Strong forcing move (check/capture/promotion) with large evaluation advantage
- Adds `is_valid_puzzle`, `validation_reason`, engine best move/PV, and gap fields

### Final dataset builder (`build_final_puzzle_dataset.py`)
- Deduplicates positions (configurable: by `fen+solution`, `fen` only, or none)
- Normalizes the solution field (engine output takes priority over heuristic)
- Assigns a difficulty score (1–100) and bucket using a multi-factor heuristic:
  - Mate distance, centipawn advantage, best-vs-second gap, PV length, average ELO of source game, game phase, forcing nature of the move

### Personalized ranking (`personalized_puzzle_ranker.py` / `model_logic.py`)
- Builds player–puzzle feature pairs covering:
  - 23 numeric player features (weakness scores, error rates, ELO)
  - 7 categorical player features (difficulty bucket, weak phase/piece/tactic)
  - 17 numeric puzzle features (engine eval, gap, difficulty score, ELOs)
  - 14 categorical puzzle features (theme, phase, piece type, speed, opening)
  - 7 computed pair features (phase match score, piece match score, tactic match score, difficulty fit, gap bonus, engine bonus, time component)
- Trains a RandomForestClassifier on proxy labels (top-K heuristic matches = positives)
- Falls back to a pure heuristic ranker if no model is available
- Group-aware train/val/test split (splits by username, not row, to prevent leakage)

### Interactive UI (`app.py`)
- Built with Streamlit
- Custom clickable SVG chessboard (`clickable_chessboard.py`) using `st.components.v2`:
  - Legal move highlighting (green dots on valid target squares)
  - Click-to-select, click-to-move interaction
  - Automatic queen promotion on pawn moves to back rank
  - Board orientation locked to the puzzle's side to move
- Puzzle cards display: title, targeted phase/piece/motif, difficulty fit, engine clarity
- Immediate move feedback integrated into the board component

---

## Project Structure

```
├── app.py                          # Streamlit application entry point
├── clickable_chessboard.py         # Custom interactive SVG board component
├── puzzle_logic.py                 # Move evaluation helpers
├── model_logic.py                  # Puzzle loading, ranking, model inference
├── profile_logic.py                # Profile construction from Lichess games or CSV
├── lichess_logic.py                # Lichess API wrapper for the UI
│
├── run.py                          # Data collection pipeline entry point
├── api.py                          # Lichess REST API client
├── parser.py                       # PGN + eval parsing → game/move/summary rows
├── writer.py                       # CSV writers for each output type
├── chess_utils.py                  # Pure chess helpers (phase, quality, eval)
├── settings.py                     # All configuration (tokens, thresholds, buckets)
│
├── mine_puzzle_candidates.py       # Step 1: extract puzzle positions from moves.csv
├── validate_puzzle_candidates.py   # Step 2: Stockfish validation pass
├── build_final_puzzle_dataset.py   # Step 3: dedupe, label, score final puzzles
├── build_player_weakness_profile.py # Build weakness profiles from CSV data
├── personalized_puzzle_ranker.py   # Train / run the ML ranking model
│
├── data/
│   └── puzzles.csv                 # Final puzzle dataset (place here for the UI)
├── output/                         # Pipeline output directory
│   ├── games.csv
│   ├── moves.csv
│   ├── summary.csv
│   ├── puzzle_candidates.csv
│   ├── puzzles_validated.csv
│   ├── puzzles_final.csv
│   ├── player_weakness_profiles.csv
│   └── model_artifacts/
│       └── personalized_puzzle_ranker_random_forest.joblib
└── requirements.txt
```

---

## Setup

### Requirements

- Python 3.10+
- Stockfish binary (for validation step only)
- A Lichess account with an API token

### Installation

```bash
git clone https://github.com/your-username/chess-trainer
cd chess-trainer
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file in the project root:

```env
LICHESS_TOKEN=your_lichess_api_token_here

# Optional overrides
CHESS_PROJECT_ROOT=/path/to/project
CHESS_PUZZLES_CSV=/path/to/puzzles.csv
CHESS_RANKER_MODEL=/path/to/model.joblib
```

---

## Running the Full Pipeline

### 1. Collect game data

```bash
# Collect 50 games per player across ELO buckets defined in settings.py
python run.py

# Or target specific players
python run.py --usernames MagnusCarlsen Hikaru --games 50
```

Output: `output/games.csv`, `output/moves.csv`, `output/summary.csv`

### 2. Build weakness profiles

```bash
python build_player_weakness_profile.py \
    --games-csv output/games.csv \
    --moves-csv output/moves.csv \
    --output output/player_weakness_profiles.csv
```

### 3. Mine puzzle candidates

```bash
python mine_puzzle_candidates.py \
    --moves-csv output/moves.csv \
    --games-csv output/games.csv \
    --min-cp-loss 100 \
    --dedupe-fen-solution \
    --output output/puzzle_candidates.csv
```

Key options:
- `--qualities Mistake Blunder` — which move qualities to mine from
- `--min-cp-loss 100` — minimum centipawn loss on the triggering move
- `--require-solution` — only keep candidates where the solution looks forcing
- `--max-per-game 3` — cap candidates per game to avoid over-representing one game

### 4. Validate with Stockfish

```bash
python validate_puzzle_candidates.py \
    --candidates-csv output/puzzle_candidates.csv \
    --engine-path /usr/local/bin/stockfish \
    --depth 16 \
    --only-valid \
    --output output/puzzles_validated.csv
```

Key options:
- `--depth 16` — search depth (higher = slower but more accurate)
- `--min-gap-cp 120` — minimum best-vs-second centipawn gap
- `--max-mate-plies 8` — only accept forced mates within this many moves
- `--require-forcing` — require the best move to be a check, capture, or promotion

### 5. Build final dataset

```bash
python build_final_puzzle_dataset.py \
    --validated-csv output/puzzles_validated.csv \
    --output output/puzzles_final.csv
```

### 6. Train the ranking model

```bash
python personalized_puzzle_ranker.py train \
    --profiles-csv output/player_weakness_profiles.csv \
    --puzzles-csv output/puzzles_final.csv \
    --model random_forest \
    --top-k-per-user 30 \
    --output-dir output/model_artifacts
```

### 7. Run the app

```bash
# Copy or symlink the final puzzle dataset where the app expects it
cp output/puzzles_final.csv data/puzzles.csv

streamlit run app.py
```

---

## Configuration (`settings.py`)

| Parameter | Default | Description |
|---|---|---|
| `LICHESS_TOKEN` | (from `.env`) | Lichess API bearer token |
| `EXACT_GAMES_PER_PLAYER` | 100 | Games required per accepted player (data collection) |
| `RAW_GAMES_TO_FETCH_PER_PLAYER` | 300 | Raw games fetched before filtering |
| `ELO_BUCKETS` | 5 buckets 1000–2200 | Min ELO, max ELO, target player count per bucket |
| `ALLOWED_SPEEDS` | blitz, rapid, classical, bullet | Game speeds to include |
| `INACCURACY_THRESHOLD` | 50 cp | Centipawn loss threshold for Inaccuracy |
| `MISTAKE_THRESHOLD` | 100 cp | Centipawn loss threshold for Mistake |
| `BLUNDER_THRESHOLD` | 200 cp | Centipawn loss threshold for Blunder |
| `API_DELAY` | 0.5s | Delay between Lichess API calls |

---

## Move Quality Classification

| Label | Centipawn loss |
|---|---|
| Good | < 50 |
| Inaccuracy | 50 – 99 |
| Mistake | 100 – 199 |
| Blunder | ≥ 200 |

---

## Weakness Score Formula

For each dimension category (e.g. "middlegame", "Knight", "capture"):

```
weakness_score = 0.65 × (category_mean_cp_loss / overall_mean_cp_loss)
               + 0.35 × (category_blunder_rate / overall_blunder_rate)
```

Clamped to [0.3, 3.0]. Categories with fewer than `min_category_moves` (default: 8) moves default to 1.0 (neutral).

---

## Difficulty Score Formula

Each puzzle gets a score from 1–100 (then bucketed into easy / medium / hard / expert) based on:

- Mate distance (shorter mate → easier)
- Best-vs-second centipawn gap (larger gap → easier, clearer)
- Absolute evaluation advantage
- Whether the solution is forcing (check / capture / promotion → easier)
- Game phase (endgame typically harder)
- PV length (longer lines → harder)
- Average ELO of the source game

---

## Puzzle Validation Acceptance Rules

A candidate is accepted if it satisfies any of:

1. **Forced mate**: engine finds mate in ≤ `max_mate_plies` (default: 8) moves
2. **Clear best**: gap ≥ `min_gap_cp` (120) AND best eval ≥ `min_winning_cp` (150) centipawns
3. **Forcing + gap**: best move is check/capture/promotion AND gap ≥ threshold
4. **Strong forcing move**: best move is forcing AND best eval ≥ `min_winning_cp + 100`

---

## Model Training Notes

The ranking model is trained on **proxy labels** because real player–puzzle outcome data (solved / failed / hints used / time to solve) is not yet collected. The proxy label is: the top-K puzzles by heuristic score for each player are treated as positives; lower-ranked puzzles (sampled from the bottom half) are negatives.

This gives a useful learned ranker that can be retrained on real interaction logs once those are available. The feature set and training structure are designed for that transition.

Group-aware splitting (by username) ensures no player appears in both training and validation sets, preventing label leakage.

---

## Deployment (Streamlit Cloud)

The UI works on Streamlit Cloud with one constraint: the `clickable_chessboard.py` component uses `st.components.v2` (inline HTML/CSS/JS), not `st.components.v1` with a `path=` argument. The `path=`-based approach does not work on Streamlit Cloud; the inline approach does.

Required secrets in Streamlit Cloud dashboard:

```toml
LICHESS_TOKEN = "your_token"
```

---

## Roadmap

- [ ] Collect real puzzle interaction logs (solved / failed / time / hints) for supervised retraining
- [ ] Multi-move puzzle sequences (currently limited to single-move solutions)
- [ ] Opening-specific weakness analysis (drilling down by ECO code)
- [ ] Spaced repetition scheduling for repeated exposure to weak areas
- [ ] ELO-based puzzle difficulty calibration (replace heuristic with human-solved data)
- [ ] CSV upload mode for players without a Lichess account

---

## License

MIT License. See `LICENSE` for details.
