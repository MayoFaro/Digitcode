const API = "/api";

const MAX_ALTERNATIVES_SHOWN = 10;

const ROW_LETTERS = ["J", "K", "L", "M", "N", "O", "P", "Q", "R", "S"];
const COL_LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H", "I"];
const POSITIONS = ["T", "U", "V", "W", "X", "Y"];
const SEGMENTS = ["a", "b", "c", "d", "e", "f", "g"];

// The 7 adjacent pairs the solver enforces "no equal neighbour" on -- fixed
// for this game's 2x3 grid, mirrors mapping.py's ADJACENT list. Drives both
// the comparison grid's layout and which pairs get a "<>" chip.
const ADJACENT_PAIRS = [
  ["T", "U"], ["U", "V"],
  ["W", "X"], ["X", "Y"],
  ["T", "W"], ["U", "X"], ["V", "Y"],
];

// Which letter is currently "open" for value-picking in the row/col chip
// groups. Purely local UI state -- the server has no notion of it.
let selectedRowLetter = null;
let selectedColLetter = null;

function showError(message) {
  const banner = document.getElementById("error-banner");
  banner.textContent = "⚠️ " + message;
  banner.style.display = "block";
}

// Each helper returns the parsed JSON body of its own response (including the
// {"error": ...} body the backend sends with a 4xx), or null if the request
// itself failed (server down, network error) — in which case the banner is
// already showing the reason and callers must not try to render.
async function fetchState() {
  try {
    const res = await fetch(`${API}/state`);
    return await res.json();
  } catch (e) {
    showError(`Impossible de joindre le serveur (${e.message}). Est-il démarré ?`);
    return null;
  }
}

async function postClue(body) {
  try {
    const res = await fetch(`${API}/clue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (e) {
    showError(`Impossible de joindre le serveur (${e.message}). Est-il démarré ?`);
    return null;
  }
}

async function postGuessFailed(body) {
  try {
    const res = await fetch(`${API}/guess-failed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (e) {
    showError(`Impossible de joindre le serveur (${e.message}). Est-il démarré ?`);
    return null;
  }
}

async function postUndo() {
  try {
    const res = await fetch(`${API}/undo`, { method: "POST" });
    return await res.json();
  } catch (e) {
    showError(`Impossible de joindre le serveur (${e.message}). Est-il démarré ?`);
    return null;
  }
}

async function postReset() {
  try {
    const res = await fetch(`${API}/reset`, { method: "POST" });
    return await res.json();
  } catch (e) {
    showError(`Impossible de joindre le serveur (${e.message}). Est-il démarré ?`);
    return null;
  }
}

function makeChip(label, { selected = false, extraClass = "" } = {}, onClick) {
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "chip" + (selected ? " chip-selected" : "") + (extraClass ? " " + extraClass : "");
  chip.textContent = label;
  chip.addEventListener("click", onClick);
  return chip;
}

// --- Row / column sum chips -------------------------------------------------

function renderLineLetters(container, letters, totals, selected, onSelect) {
  container.innerHTML = "";
  for (const letter of letters) {
    const value = totals[letter];
    const label = value !== undefined ? `${letter}=${value}` : letter;
    const chip = makeChip(label, {
      selected: letter === selected,
      extraClass: value !== undefined ? "chip-set" : "",
    }, () => onSelect(letter));
    container.appendChild(chip);
  }
}

function renderLineValues(container, letter, totals, reachable, applyValue) {
  container.innerHTML = "";
  if (!letter) {
    container.textContent = "— choisissez une lettre ci-dessus —";
    return;
  }
  const current = totals[letter];
  const options = current !== undefined ? [current] : (reachable[letter] || []);
  for (const v of options) {
    const chip = makeChip(String(v), { selected: v === current }, () => applyValue(letter, v));
    container.appendChild(chip);
  }
  const raz = makeChip("RAZ", {}, () => applyValue(letter, null));
  container.appendChild(raz);
}

// --- Comparison grid ---------------------------------------------------------

function currentRelation(comparisons, left, right) {
  for (const [a, rel, b] of comparisons) {
    if (a === left && b === right) return rel;
    if (a === right && b === left) return rel === ">" ? "<" : ">";
  }
  return null;
}

function findStoredComparison(comparisons, left, right) {
  for (const entry of comparisons) {
    const [a, , b] = entry;
    if ((a === left && b === right) || (a === right && b === left)) return entry;
  }
  return null;
}

function relationLabel(rel) {
  if (rel === ">") return ">";
  if (rel === "<") return "<";
  return "?";
}

function renderComparisons(state) {
  const container = document.getElementById("cmp-grid");
  container.innerHTML = "";
  container.style.gridTemplateColumns = "repeat(5, auto)";

  const cell = (row, col, node) => {
    node.style.gridRow = String(row);
    node.style.gridColumn = String(col);
    container.appendChild(node);
  };

  const letterNode = (pos) => {
    const span = document.createElement("span");
    span.className = "cmp-letter";
    span.textContent = pos;
    return span;
  };

  const connectorNode = (left, right) => {
    const rel = currentRelation(state.comparisons, left, right);
    return makeChip(relationLabel(rel), { extraClass: "cmp-chip" }, () => {
      if (rel === null) {
        runMutation(() => postClue({ type: "comparison", left, rel: ">", right }));
      } else if (rel === ">") {
        runMutation(() => postClue({ type: "comparison", left, rel: "<", right }));
      } else {
        const stored = findStoredComparison(state.comparisons, left, right);
        runMutation(() => postClue({ type: "comparison", left: stored[0], rel: stored[1], right: stored[2], remove: true }));
      }
    });
  };

  cell(1, 1, letterNode("T"));
  cell(1, 2, connectorNode("T", "U"));
  cell(1, 3, letterNode("U"));
  cell(1, 4, connectorNode("U", "V"));
  cell(1, 5, letterNode("V"));

  cell(2, 1, connectorNode("T", "W"));
  cell(2, 3, connectorNode("U", "X"));
  cell(2, 5, connectorNode("V", "Y"));

  cell(3, 1, letterNode("W"));
  cell(3, 2, connectorNode("W", "X"));
  cell(3, 3, letterNode("X"));
  cell(3, 4, connectorNode("X", "Y"));
  cell(3, 5, letterNode("Y"));
}

// --- Parity + segment rows ---------------------------------------------------

function nextParity(current) {
  if (current === undefined || current === null) return "Pair";
  if (current === "Pair") return "Impair";
  return null;
}

function parityLabel(current) {
  if (current === "Pair") return "P";
  if (current === "Impair") return "I";
  return "?";
}

function nextSegmentValue(current) {
  if (current === undefined) return true;
  if (current === true) return false;
  return null;
}

function segmentClass(current) {
  if (current === true) return "seg-on";
  if (current === false) return "seg-off";
  return "seg-unknown";
}

function renderPositionRows(state) {
  const container = document.getElementById("pos-rows");
  container.innerHTML = "";

  for (const pos of POSITIONS) {
    const row = document.createElement("div");
    row.className = "pos-row";

    const parityValue = state.parity[pos];
    const parityChip = makeChip(parityLabel(parityValue), { extraClass: "parity-chip" }, () => {
      runMutation(() => postClue({ type: "parity", pos, value: nextParity(parityValue) }));
    });
    row.appendChild(parityChip);

    const label = document.createElement("span");
    label.className = "pos-label";
    label.textContent = pos;
    row.appendChild(label);

    for (const seg of SEGMENTS) {
      const segValue = state.segment_state[`${pos}${seg}`];
      const chip = makeChip(seg, { extraClass: "seg-chip " + segmentClass(segValue) }, () => {
        runMutation(() => postClue({ type: "segment", pos, seg, value: nextSegmentValue(segValue) }));
      });
      row.appendChild(chip);
    }

    container.appendChild(row);
  }
}

// --- Main render --------------------------------------------------------------

function render(state) {
  // A null state means the request never reached the server; showError() has
  // already put the reason in the banner, so keep the last rendered view.
  if (state === null) return;

  const banner = document.getElementById("error-banner");
  if (state.error) {
    showError(state.error);
    return;
  }
  banner.style.display = "none";

  const domainsEl = document.getElementById("domains");
  domainsEl.innerHTML = "";
  for (const p of POSITIONS) {
    const div = document.createElement("div");
    div.className = "position-box";
    div.innerHTML = `<strong>${p}</strong><br>{${state.domains[p].join(",")}}`;
    domainsEl.appendChild(div);
  }

  renderLineLetters(
    document.getElementById("row-letters"), ROW_LETTERS, state.row_totals, selectedRowLetter,
    (letter) => { selectedRowLetter = letter; render(state); },
  );
  renderLineValues(
    document.getElementById("row-values"), selectedRowLetter, state.row_totals, state.reachable_row_sums,
    (row, value) => runMutation(() => postClue({ type: "row_total", row, value })),
  );

  renderLineLetters(
    document.getElementById("col-letters"), COL_LETTERS, state.col_totals, selectedColLetter,
    (letter) => { selectedColLetter = letter; render(state); },
  );
  renderLineValues(
    document.getElementById("col-values"), selectedColLetter, state.col_totals, state.reachable_col_sums,
    (col, value) => runMutation(() => postClue({ type: "col_total", col, value })),
  );

  renderComparisons(state);
  renderPositionRows(state);

  document.getElementById("n-solutions").textContent = state.solutions.length;
  document.getElementById("solutions-list").textContent = state.solutions.join(" ; ");

  // Candidates already tried and failed must not be selectable again: with a
  // lifetime budget of 2 attempts, re-picking one would burn an attempt on a
  // code already known to be wrong.
  const excluded = new Set(state.my_excluded || []);
  const missSelect = document.getElementById("my-miss-select");
  missSelect.innerHTML = "";
  state.solutions.forEach((sol, i) => {
    if (excluded.has(sol)) return;
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = sol;
    missSelect.appendChild(opt);
  });

  const race = state.race;
  // Outside the exact regime the score is NOT a calibrated win probability but
  // a reduction-quality indicator (same distinction as cli.py's show_race).
  document.getElementById("p-win-label").textContent = race.exact ? "P(je gagne)" : "Qualité de réduction";
  document.getElementById("p-win").textContent = (race.p_win * 100).toFixed(1) + "%";
  document.getElementById("exact-tag").textContent = race.exact ? "(exact)" : "(estimation)";
  document.getElementById("best-question").textContent = race.best_question ? race.best_question.label : "(aucune)";
  const guessEl = document.getElementById("guess-now");
  guessEl.textContent = race.guess_now ? "OUI — proposez une solution !" : "Non, attendez.";
  guessEl.className = "guess-now " + (race.guess_now ? "guess-yes" : "guess-no");

  const altLabel = race.exact ? "P(gagner)" : "réduction";
  const altEl = document.getElementById("alternatives");
  altEl.innerHTML = "";
  for (const alt of race.ranked_alternatives.slice(0, MAX_ALTERNATIVES_SHOWN)) {
    const li = document.createElement("li");
    li.textContent = `${alt.label} — ${altLabel}=${(alt.p_win * 100).toFixed(1)}%`;
    altEl.appendChild(li);
  }

  document.getElementById("a-me").textContent = state.a_me;
  document.getElementById("a-opp").textContent = state.a_opp;
  document.getElementById("trace").textContent = state.trace.join("\n");
}

async function refresh() {
  render(await fetchState());
}

// In-flight guard: a request can take a couple of seconds on a narrowed-down
// board, and queuing concurrent mutations would race against the server's
// shared in-memory state. Disable every control until the response is rendered.
let inFlight = false;

function allControls() {
  return Array.from(document.querySelectorAll("button"));
}

async function runMutation(fn) {
  if (inFlight) return;
  inFlight = true;
  const controls = allControls();
  controls.forEach((c) => { c.disabled = true; });
  try {
    render(await fn());
  } finally {
    controls.forEach((c) => { c.disabled = false; });
    inFlight = false;
  }
}

document.getElementById("undo-btn").addEventListener("click", () => runMutation(postUndo));
document.getElementById("reset-btn").addEventListener("click", () => runMutation(postReset));
document.getElementById("opp-miss-btn").addEventListener("click", () => runMutation(() => postGuessFailed({ who: "opponent" })));

document.getElementById("my-miss-btn").addEventListener("click", () => {
  const select = document.getElementById("my-miss-select");
  const sol = select.selectedOptions.length ? select.selectedOptions[0].textContent : null;
  if (!sol) return;
  const digits = sol.replace(" ", "").split("").map(Number);
  return runMutation(() => postGuessFailed({ who: "me", candidate: digits }));
});

refresh();
