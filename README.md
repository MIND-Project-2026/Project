# chess_collector

Scrapes Lichess games and exports clean CSVs for analysis or ML.
No local Stockfish needed — uses Lichess cloud evaluations.

---

## Structure

```
PMIND2/
├── api.py
├── chess_utils.py
├── parser.py
├── writer.py
├── settings.py
├── run.py
└── output/
```

---

## How to run

```bash
# Install dependencies
pip install requests chess

# Collect from leaderboards (uses settings.py defaults)
python run.py

# Override number of players / games
python run.py --players 50 --games 20

# Collect specific players only (skips leaderboard fetch)
python run.py --usernames EricRosen Naroditsky Alireza2003

# Custom output folder
python run.py --usernames EricRosen --output-dir my_data
```

---

## Output files

### `games.csv` — one row per game
| Column | Description |
|--------|-------------|
| `game_id` | Lichess game ID |
| `date_utc` | Game start time (ISO 8601 UTC) |
| `time_control` | e.g. `300+0` |
| `variant` | `standard`, `chess960`, … |
| `speed` | `blitz`, `rapid`, … |
| `rated` | True / False |
| `status` | `mate`, `resign`, `draw`, … |
| `ply_count` | Total half-moves |
| `white_name` / `black_name` | Usernames |
| `white_elo` / `black_elo` | Rating at game time |
| `white_elo_diff` / `black_elo_diff` | Rating change |
| `opening_eco` | ECO code (e.g. `B12`) |
| `opening_name` | Full opening name |
| `opening_ply` | Ply where opening ends |
| `target_name` | The player being tracked |
| `target_color` | `white` or `black` |
| `opponent_name` | The other player |
| `target_elo` / `opponent_elo` | Their ratings |
| `target_result` | `win` / `loss` / `draw` |
| `target_score` | 1.0 / 0.0 / 0.5 |

---

### `moves.csv` — one row per half-move (ply)
| Column | Description |
|--------|-------------|
| `game_id` | Links back to `games.csv` |
| `ply` | Half-move number (1 = White's first move) |
| `player_color` | `white` or `black` |
| `is_target_move` | True when it's the tracked player's turn |
| `fen_before` | Board state before this move |
| `phase` | `opening` / `middlegame` / `endgame` |
| `move_san` | Move in Standard Algebraic Notation (e.g. `Nf3`) |
| `move_uci` | Move in UCI format (e.g. `g1f3`) |
| `piece_type` | `Pawn`, `Knight`, `Bishop`, `Rook`, `Queen`, `King` |
| `is_capture` / `is_check` / `is_castle` / `is_promotion` | Tactical flags |
| `promotion_piece` | `Q`, `R`, `B`, or `N` if promotion |
| `best_move_san` / `best_move_uci` | Engine's best move |
| `eval_white_before` / `eval_white_after` | Position eval in centipawns (White's POV) |
| `cp_loss` | Centipawn loss (only for target player's moves) |
| `move_quality` | `Good` / `Inaccuracy` / `Mistake` / `Blunder` |
| `clock_before_cs` / `clock_after_cs` | Clock before/after in centiseconds |
| `time_spent_cs` | Time used for this move |

---

### `summary.csv` — one row per (player × game)
| Column | Description |
|--------|-------------|
| `target_name` / `game_id` | Identifiers |
| `target_color` / `speed` / `time_control` / `rated` | Game context |
| `target_elo` / `opponent_elo` | Ratings |
| `target_result` / `target_score` | Outcome |
| `total_moves` | Target player's move count |
| `mean_cp_loss` / `median_cp_loss` / `p90_cp_loss` | Overall quality stats |
| `good_moves` / `inaccuracies` / `mistakes` / `blunders` | Error counts |
| `opening_mean_cp_loss` | Avg cp_loss in opening phase |
| `middlegame_mean_cp_loss` | Avg cp_loss in middlegame |
| `endgame_mean_cp_loss` | Avg cp_loss in endgame |

### `players.csv` — one row per player
| Column | Description |
|--------|-------------|
| `username` | Lichess username |
| `elo` | Detected player ELO from collected games |
| `elo_bucket` | Sampling bucket label (or `manual`) |
| `games_collected` | Number of analysed games used |
| `mean_cp_loss` / `median_cp_loss` | Aggregated quality stats |
| `blunder_rate` / `mistake_rate` / `inaccuracy_rate` | Error rates over target moves |
| `avg_blunders_per_game` / `avg_mistakes_per_game` | Mean errors per game |
| `win_rate` | Mean score from target perspective |

---

## Move quality thresholds (edit in `settings.py`)
| Label | cp_loss range |
|-------|--------------|
| Good | < 50 |
| Inaccuracy | 50 – 99 |
| Mistake | 100 – 199 |
| Blunder | ≥ 200 |
