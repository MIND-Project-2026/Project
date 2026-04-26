# PMIND

PMIND stands for Personalized Puzzle Mind. It takes real Lichess games, finds the mistakes that matter, builds weakness profiles, and turns them into custom chess puzzles.

The goal is simple: give each player puzzles that match how they actually play.

## What’s in the project

- `run.py` collects games from Lichess and writes the raw CSVs.
- `parser.py`, `chess_utils.py`, and `writer.py` turn game data into a usable dataset.
- `build_blunders_csv.py` and `build_player_weakness_profile.py` summarize mistakes by player.
- `mine_puzzle_candidates.py`, `validate_puzzle_candidates.py`, and `build_final_puzzle_dataset.py` create the final puzzle set.
- `personalized_puzzle_ranker.py` trains and runs the ranking model.
- `app.py` provides the Streamlit UI for browsing recommendations.
- `logic/` holds the smaller helpers used by the app and model code.

## How it works

1. Pull analyzed games from Lichess.
2. Parse each game into games, moves, and summaries.
3. Measure move quality and player weaknesses.
4. Mine puzzle candidates from the positions that look useful.
5. Validate the candidates with Stockfish.
6. Train a model that ranks puzzles by how well they fit a player.
7. Show the results in the app or export them as CSV files.

## Setup

```bash
python3 -m venv general-env
source general-env/bin/activate
pip install -r requirements.txt
export LICHESS_API_TOKEN="your_token_here"
```

If you already have a virtual environment, just activate it and install the requirements.

## Collect games

```bash
python run.py
python run.py --usernames EricRosen Naroditsky
python run.py --games 50 --output-dir my_data
```

`run.py` uses the defaults from `settings.py` unless you override them on the command line.

## Build the puzzle pipeline

```bash
python build_blunders_csv.py
python build_player_weakness_profile.py
python mine_puzzle_candidates.py
python validate_puzzle_candidates.py
python build_final_puzzle_dataset.py
```

## Train and recommend

```bash
python personalized_puzzle_ranker.py train \
  --profiles-csv output/player_weakness_profiles.csv \
  --puzzles-csv output/puzzles_final.csv \
  --output-dir output/model_artifacts

python personalized_puzzle_ranker.py recommend \
  --model-path output/model_artifacts/personalized_puzzle_ranker_random_forest.joblib \
  --profiles-csv output/player_weakness_profiles.csv \
  --puzzles-csv output/puzzles_final.csv \
  --username YourUsername
```

To browse recommendations in the UI:

```bash
streamlit run app.py
```

## Main outputs

- `games.csv` — one row per game
- `moves.csv` — one row per move
- `summary.csv` — one row per player-game pair
- `players.csv` — one row per player
- `blunders.csv` — filtered mistake moves
- `player_weakness_profiles.csv` — weakness profile per player
- `puzzle_candidates.csv` — mined puzzle positions
- `puzzles_validated.csv` — Stockfish-checked puzzles
- `puzzles_final.csv` — final puzzle dataset
- `output/model_artifacts/` — saved model files and metrics

## Data you get

### games.csv
Game metadata, ratings, opening info, result, and tracked player details.

### moves.csv
Move-by-move data with the board state, move type, phase, clock info, engine evals, and move quality.

### summary.csv
One row per player-game pair with move counts, cp loss stats, and error totals.

### players.csv
One row per player with ELO, sampled bucket, collected games, and overall error rates.

## Move quality

The project uses a simple centipawn scale:

- Good: under 50
- Inaccuracy: 50–99
- Mistake: 100–199
- Blunder: 200 or more

You can change those values in `settings.py`.

## Notes

- The project uses Lichess cloud analysis, so you do not need a local engine to collect games.
- Stockfish is only used later when validating puzzle candidates.
- The sample buckets and thresholds in `settings.py` are meant to be easy to tweak.
- The repo includes notebooks for EDA if you want to explore the data by hand.
