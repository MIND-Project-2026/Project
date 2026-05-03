from __future__ import annotations

import chess
import chess.svg
import streamlit as st

HTML = """
<div class="cb-root">
  <div class="cb-board-shell">
    <div class="cb-files top"></div>
    <div class="cb-main">
      <div class="cb-ranks left"></div>
      <div class="cb-board-wrap">
        <div class="cb-svg-slot"></div>
        <div class="cb-overlay"></div>
      </div>
      <div class="cb-ranks right"></div>
    </div>
    <div class="cb-files bottom"></div>
  </div>
  <div class="cb-status"></div>
</div>
"""

CSS = """
:host {
  display: block;
  width: 100%;
}

.cb-root {
  width: 100%;
  max-width: 620px;
  margin: 0 auto;
}

.cb-board-shell {
  width: 100%;
}

.cb-main {
  display: grid;
  grid-template-columns: 28px 1fr 28px;
  align-items: stretch;
  gap: 0;
}

.cb-board-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: 14px;
  overflow: hidden;
  box-shadow:
    0 12px 30px rgba(15, 23, 42, 0.10),
    0 3px 10px rgba(15, 23, 42, 0.08);
  border: 1px solid #cbd5e1;
  background: white;
}

.cb-svg-slot {
  position: absolute;
  inset: 0;
}

.cb-svg-slot svg {
  display: block;
  width: 100%;
  height: 100%;
}

.cb-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  grid-template-rows: repeat(8, 1fr);
}

.cb-hit {
  position: relative;
  cursor: pointer;
  background: transparent;
  box-sizing: border-box;
  transition: background 0.12s ease, box-shadow 0.12s ease;
}

.cb-hit:hover {
  background: rgba(59, 130, 246, 0.12);
}

.cb-root.locked .cb-hit {
  cursor: default;
  pointer-events: none;
}

.cb-hit.selected {
  box-shadow: inset 0 0 0 4px rgba(37, 99, 235, 0.95);
}

.cb-hit.target::after {
  content: "";
  position: absolute;
  width: 24%;
  height: 24%;
  min-width: 10px;
  min-height: 10px;
  max-width: 18px;
  max-height: 18px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.90);
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

.cb-status {
  margin-top: 0.6rem;
  text-align: center;
  color: #334155;
  font-size: 0.95rem;
  min-height: 1.3rem;
}

.cb-help {
  margin-top: 0.2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.83rem;
}

.cb-files,
.cb-ranks {
  display: grid;
  font-size: 0.9rem;
  font-weight: 600;
  color: #475569;
  user-select: none;
}

.cb-files {
  grid-template-columns: repeat(8, 1fr);
  margin: 0 28px;
  padding: 4px 0;
}

.cb-ranks {
  grid-template-rows: repeat(8, 1fr);
}

.cb-files > div,
.cb-ranks > div {
  display: flex;
  align-items: center;
  justify-content: center;
}

.cb-feedback-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 44%;
  height: 44%;
  min-width: 22px;
  min-height: 22px;
  max-width: 42px;
  max-height: 42px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.3rem;
  line-height: 1;
  pointer-events: none;
  animation: cb-pop-in 0.18s cubic-bezier(0.34, 1.56, 0.64, 1) both;
  z-index: 10;
}

.cb-feedback-icon.correct {
  background: rgba(34, 197, 94, 0.92);
  color: #fff;
  box-shadow: 0 2px 12px rgba(34,197,94,0.5);
}

.cb-feedback-icon.wrong {
  background: rgba(239, 68, 68, 0.92);
  color: #fff;
  box-shadow: 0 2px 12px rgba(239,68,68,0.5);
}

@keyframes cb-pop-in {
  from { transform: translate(-50%, -50%) scale(0.4); opacity: 0; }
  to   { transform: translate(-50%, -50%) scale(1);   opacity: 1; }
}
"""

JS = r"""
let selectedSquare = null;
let currentFen = null;
let currentOrientation = "white";
let currentExpectedMove = "";
let baseSvg = "";
let displayedSvg = "";
let nextSvgMap = {};
let feedbackStatus = "";
let feedbackSquare = "";
let solved = false;
let transientLock = false;
let wrongTimer = null;

function orderedSquares(orientation) {
  const ranks = orientation === "black"
    ? [1, 2, 3, 4, 5, 6, 7, 8]
    : [8, 7, 6, 5, 4, 3, 2, 1];

  const files = orientation === "black"
    ? ["h", "g", "f", "e", "d", "c", "b", "a"]
    : ["a", "b", "c", "d", "e", "f", "g", "h"];

  const squares = [];
  for (const rank of ranks) {
    for (const file of files) {
      squares.push(file + String(rank));
    }
  }
  return squares;
}

function orderedFiles(orientation) {
  return orientation === "black"
    ? ["h", "g", "f", "e", "d", "c", "b", "a"]
    : ["a", "b", "c", "d", "e", "f", "g", "h"];
}

function orderedRanks(orientation) {
  return orientation === "black"
    ? ["1", "2", "3", "4", "5", "6", "7", "8"]
    : ["8", "7", "6", "5", "4", "3", "2", "1"];
}

function parseFenBoard(fen) {
  const boardPart = (fen || "").split(" ")[0];
  const rows = boardPart.split("/");
  const pieces = {};
  const files = ["a","b","c","d","e","f","g","h"];

  rows.forEach((row, rankIdx) => {
    let fileIdx = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) {
        fileIdx += parseInt(ch, 10);
      } else {
        const square = files[fileIdx] + String(8 - rankIdx);
        pieces[square] = ch;
        fileIdx += 1;
      }
    }
  });

  return pieces;
}

function turnFromFen(fen) {
  const parts = (fen || "").split(" ");
  return parts.length > 1 ? parts[1] : "w";
}

function isOwnPiece(pieceChar, turn) {
  if (!pieceChar) return false;
  return turn === "w"
    ? pieceChar === pieceChar.toUpperCase()
    : pieceChar === pieceChar.toLowerCase();
}

function maybePromotion(pieceChar, toSquare) {
  if (!pieceChar) return "";
  if (pieceChar !== "P" && pieceChar !== "p") return "";
  const targetRank = toSquare[1];
  return (targetRank === "1" || targetRank === "8") ? "q" : "";
}

function renderLabels(container, values) {
  container.innerHTML = "";
  values.forEach((value) => {
    const div = document.createElement("div");
    div.textContent = value;
    container.appendChild(div);
  });
}

function clearWrongFeedbackSoon(repaint) {
  if (wrongTimer) {
    clearTimeout(wrongTimer);
  }
  wrongTimer = setTimeout(() => {
    feedbackStatus = "";
    feedbackSquare = "";
    displayedSvg = baseSvg;
    transientLock = false;
    repaint();
  }, 800);
}

export default function(component) {
  const { data, parentElement } = component;

  const root = parentElement.querySelector(".cb-root");
  const svgSlot = parentElement.querySelector(".cb-svg-slot");
  const overlay = parentElement.querySelector(".cb-overlay");
  const status = parentElement.querySelector(".cb-status");
  const filesTop = parentElement.querySelector(".cb-files.top");
  const filesBottom = parentElement.querySelector(".cb-files.bottom");
  const ranksLeft = parentElement.querySelector(".cb-ranks.left");
  const ranksRight = parentElement.querySelector(".cb-ranks.right");

  const fen = data?.fen || "";
  const orientation = data?.orientation || "white";
  const svg = data?.svg || "";
  const legalMap = data?.legal_map || {};
  const expectedMove = (data?.expected_uci || "").toLowerCase();
  const nextSvgs = data?.next_svg_map || {};

  if (!fen || !svg || !root || !svgSlot || !overlay || !status) {
    return;
  }

  if (
    fen !== currentFen ||
    orientation !== currentOrientation ||
    expectedMove !== currentExpectedMove
  ) {
    selectedSquare = null;
    currentFen = fen;
    currentOrientation = orientation;
    currentExpectedMove = expectedMove;
    baseSvg = svg;
    displayedSvg = svg;
    nextSvgMap = nextSvgs;
    feedbackStatus = "";
    feedbackSquare = "";
    solved = false;
    transientLock = false;
    if (wrongTimer) {
      clearTimeout(wrongTimer);
      wrongTimer = null;
    }
  }

  const pieces = parseFenBoard(fen);
  const turn = turnFromFen(fen);

  function repaint() {
    if (solved || transientLock) {
      root.classList.add("locked");
    } else {
      root.classList.remove("locked");
    }

    svgSlot.innerHTML = displayedSvg;
    overlay.innerHTML = "";

    renderLabels(filesTop, orderedFiles(orientation));
    renderLabels(filesBottom, orderedFiles(orientation));
    renderLabels(ranksLeft, orderedRanks(orientation));
    renderLabels(ranksRight, orderedRanks(orientation));

    const squares = orderedSquares(orientation);
    const targets = selectedSquare ? (legalMap[selectedSquare] || []) : [];

    for (const square of squares) {
      const cell = document.createElement("div");
      cell.className = "cb-hit";

      if (selectedSquare === square) {
        cell.classList.add("selected");
      }
      if (!solved && !transientLock && targets.includes(square)) {
        cell.classList.add("target");
      }

      cell.onclick = () => {
        if (solved || transientLock) return;

        const clickedPiece = pieces[square] || "";

        if (!selectedSquare) {
          if (clickedPiece && isOwnPiece(clickedPiece, turn)) {
            feedbackStatus = "";
            feedbackSquare = "";
            selectedSquare = square;
            repaint();
          }
          return;
        }

        if (square === selectedSquare) {
          selectedSquare = null;
          repaint();
          return;
        }

        if (clickedPiece && isOwnPiece(clickedPiece, turn)) {
          selectedSquare = square;
          repaint();
          return;
        }

        const legalTargets = legalMap[selectedSquare] || [];
        if (!legalTargets.includes(square)) {
          return;
        }

        const sourcePiece = pieces[selectedSquare] || "";
        const move = (selectedSquare + square + maybePromotion(sourcePiece, square)).toLowerCase();

        selectedSquare = null;
        feedbackSquare = square;

        if (nextSvgMap[move]) {
          displayedSvg = nextSvgMap[move];
        }

        if (move === currentExpectedMove) {
          feedbackStatus = "correct";
          solved = true;
          repaint();
        } else {
          feedbackStatus = "wrong";
          transientLock = true;
          repaint();
          clearWrongFeedbackSoon(repaint);
        }
      };

      overlay.appendChild(cell);
    }

    if (feedbackStatus && feedbackSquare) {
      const squareIdx = squares.indexOf(feedbackSquare);
      if (squareIdx !== -1) {
        const cells = overlay.querySelectorAll(".cb-hit");
        const targetCell = cells[squareIdx];
        if (targetCell) {
          const badge = document.createElement("div");
          badge.className = `cb-feedback-icon ${feedbackStatus}`;
          badge.textContent = feedbackStatus === "correct" ? "✓" : "✗";
          targetCell.appendChild(badge);
        }
      }
    }
  }

  repaint();
}
"""

_board_component = st.components.v2.component(
    "real_clickable_chessboard",
    html=HTML,
    css=CSS,
    js=JS,
)


def clickable_chessboard(
    fen: str,
    orientation: str = "white",
    expected_uci: str = "",
    key: str | None = None,
) -> None:
    board = chess.Board(fen)

    legal_map: dict[str, list[str]] = {}
    next_svg_map: dict[str, str] = {}

    for move in board.legal_moves:
        from_sq = chess.square_name(move.from_square)
        to_sq = chess.square_name(move.to_square)
        uci = move.uci().lower()

        legal_map.setdefault(from_sq, []).append(to_sq)

        board_after = board.copy()
        board_after.push(move)
        next_svg_map[uci] = chess.svg.board(
            board=board_after,
            orientation=chess.WHITE if orientation == "white" else chess.BLACK,
            coordinates=False,
            size=720,
        )

    svg = chess.svg.board(
        board=board,
        orientation=chess.WHITE if orientation == "white" else chess.BLACK,
        coordinates=False,
        size=720,
    )

    _board_component(
        data={
            "fen": fen,
            "orientation": orientation,
            "svg": svg,
            "legal_map": legal_map,
            "expected_uci": expected_uci,
            "next_svg_map": next_svg_map,
        },
        key=key,
    )