const API = "/api";

const MAX_ALTERNATIVES_SHOWN = 10;

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

  const positions = ["T", "U", "V", "W", "X", "Y"];
  const domainsEl = document.getElementById("domains");
  domainsEl.innerHTML = "";
  for (const p of positions) {
    const div = document.createElement("div");
    div.className = "position-box";
    div.innerHTML = `<strong>${p}</strong><br>{${state.domains[p].join(",")}}`;
    domainsEl.appendChild(div);
  }

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

document.getElementById("row-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const row = document.getElementById("row-select").value;
  const value = document.getElementById("row-value").value;
  return runMutation(() => postClue({ type: "row_total", row, value: value === "" ? null : Number(value) }));
});

document.getElementById("col-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const col = document.getElementById("col-select").value;
  const value = document.getElementById("col-value").value;
  return runMutation(() => postClue({ type: "col_total", col, value: value === "" ? null : Number(value) }));
});

document.getElementById("parity-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const pos = document.getElementById("parity-pos").value;
  const value = document.getElementById("parity-value").value;
  return runMutation(() => postClue({ type: "parity", pos, value: value === "" ? null : value }));
});

document.getElementById("cmp-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const left = document.getElementById("cmp-left").value;
  const rel = document.getElementById("cmp-rel").value;
  const right = document.getElementById("cmp-right").value;
  return runMutation(() => postClue({ type: "comparison", left, rel, right }));
});

document.getElementById("seg-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const pos = document.getElementById("seg-pos").value;
  const seg = document.getElementById("seg-seg").value;
  const value = document.getElementById("seg-value").value;
  return runMutation(() => postClue({ type: "segment", pos, seg, value: value === "" ? null : value === "on" }));
});

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
