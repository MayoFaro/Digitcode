const API = "/api";

async function fetchState() {
  const res = await fetch(`${API}/state`);
  return res.json();
}

async function postClue(body) {
  const res = await fetch(`${API}/clue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function postGuessFailed(body) {
  const res = await fetch(`${API}/guess-failed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function postUndo() {
  const res = await fetch(`${API}/undo`, { method: "POST" });
  return res.json();
}

async function postReset() {
  const res = await fetch(`${API}/reset`, { method: "POST" });
  return res.json();
}

function render(state) {
  const banner = document.getElementById("error-banner");
  if (state.error) {
    banner.textContent = "⚠️ " + state.error;
    banner.style.display = "block";
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

  const missSelect = document.getElementById("my-miss-select");
  missSelect.innerHTML = "";
  state.solutions.forEach((sol, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = sol;
    missSelect.appendChild(opt);
  });

  const race = state.race;
  document.getElementById("p-win").textContent = (race.p_win * 100).toFixed(1) + "%";
  document.getElementById("exact-tag").textContent = race.exact ? "(exact)" : "(estimation)";
  document.getElementById("best-question").textContent = race.best_question ? race.best_question.label : "(aucune)";
  const guessEl = document.getElementById("guess-now");
  guessEl.textContent = race.guess_now ? "OUI — proposez une solution !" : "Non, attendez.";
  guessEl.className = "guess-now " + (race.guess_now ? "guess-yes" : "guess-no");

  const altEl = document.getElementById("alternatives");
  altEl.innerHTML = "";
  for (const alt of race.ranked_alternatives) {
    const li = document.createElement("li");
    li.textContent = `${alt.label} — P(gagner)=${(alt.p_win * 100).toFixed(1)}%`;
    altEl.appendChild(li);
  }

  document.getElementById("a-me").textContent = state.a_me;
  document.getElementById("a-opp").textContent = state.a_opp;
  document.getElementById("trace").textContent = state.trace.join("\n");
}

async function refresh() {
  render(await fetchState());
}

document.getElementById("row-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const row = document.getElementById("row-select").value;
  const value = document.getElementById("row-value").value;
  await postClue({ type: "row_total", row, value: value === "" ? null : Number(value) });
  refresh();
});

document.getElementById("col-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const col = document.getElementById("col-select").value;
  const value = document.getElementById("col-value").value;
  await postClue({ type: "col_total", col, value: value === "" ? null : Number(value) });
  refresh();
});

document.getElementById("parity-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pos = document.getElementById("parity-pos").value;
  const value = document.getElementById("parity-value").value;
  await postClue({ type: "parity", pos, value: value === "" ? null : value });
  refresh();
});

document.getElementById("cmp-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const left = document.getElementById("cmp-left").value;
  const rel = document.getElementById("cmp-rel").value;
  const right = document.getElementById("cmp-right").value;
  await postClue({ type: "comparison", left, rel, right });
  refresh();
});

document.getElementById("seg-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pos = document.getElementById("seg-pos").value;
  const seg = document.getElementById("seg-seg").value;
  const value = document.getElementById("seg-value").value;
  await postClue({ type: "segment", pos, seg, value: value === "" ? null : value === "on" });
  refresh();
});

document.getElementById("undo-btn").addEventListener("click", async () => { await postUndo(); refresh(); });
document.getElementById("reset-btn").addEventListener("click", async () => { await postReset(); refresh(); });
document.getElementById("opp-miss-btn").addEventListener("click", async () => { await postGuessFailed({ who: "opponent" }); refresh(); });

document.getElementById("my-miss-btn").addEventListener("click", async () => {
  const idx = document.getElementById("my-miss-select").value;
  const state = await fetchState();
  const sol = state.solutions[idx];
  if (!sol) return;
  const digits = sol.replace(" ", "").split("").map(Number);
  await postGuessFailed({ who: "me", candidate: digits });
  refresh();
});

refresh();
