/* NotenErkennung – Browser-Oberfläche */

const PLAYER_VERSION = 5; // bei App-Änderungen erhöhen (Cache-Kontrolle)
console.log("NotenErkennung Player v" + PLAYER_VERSION);

const $ = (sel) => document.querySelector(sel);

// Datenabrufe niemals aus dem Browser-Cache bedienen -- sonst zeigt die
// App nach einer Neutranskription alte Noten an.
const NO_CACHE = { cache: "no-store" };

let osmd = null;
let currentSong = null;   // Name des angezeigten Songs
let watchedJobs = new Set();
let pollTimer = null;

/* ---------------- Songliste ---------------- */

async function loadSongs() {
  const res = await fetch("/api/songs", NO_CACHE);
  const songs = await res.json();
  const list = $("#song-list");
  list.innerHTML = "";

  let anyRunning = false;
  for (const song of songs) {
    const li = document.createElement("li");
    if (song.name === currentSong) li.classList.add("active");

    const name = document.createElement("div");
    name.className = "song-name";
    name.textContent = song.name;
    li.appendChild(name);

    const state = document.createElement("div");
    state.className = "song-state";

    if (song.job && song.job.state === "running") {
      anyRunning = true;
      state.classList.add("running");
      state.textContent = `⏳ ${song.job.message} (${song.job.step}/${song.job.total})`;
      if (song.name === currentSong) showProgress(song);
    } else if (song.job && song.job.state === "error") {
      state.classList.add("error");
      state.textContent = "Fehler: " + song.job.message;
    } else if (song.transcribed) {
      state.textContent = "✓ Noten vorhanden";
      if (watchedJobs.has(song.name)) {
        watchedJobs.delete(song.name);
        openSong(song.name); // frisch fertig geworden -> direkt anzeigen
      }
    } else {
      state.textContent = "Noch nicht transkribiert – klicken zum Starten";
    }
    li.appendChild(state);

    li.onclick = () => {
      if (song.transcribed) openSong(song.name);
      else if (!song.job || song.job.state !== "running") startTranscription(song);
    };
    list.appendChild(li);
  }

  clearTimeout(pollTimer);
  if (anyRunning) pollTimer = setTimeout(loadSongs, 2500);
}

async function startTranscription(song) {
  watchedJobs.add(song.name);
  currentSong = song.name;
  showProgress({ name: song.name, job: { step: 0, total: 5, message: "Starte ..." } });
  await fetch("/api/transcribe/" + encodeURIComponent(song.file), { method: "POST" });
  loadSongs();
}

$("#upload-input").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: form });
  const info = await res.json();
  ev.target.value = "";
  await startTranscription(info);
});

/* ---------------- Ansichten ---------------- */

function showOnly(id) {
  for (const v of ["#empty-state", "#progress-view", "#song-view"]) {
    $(v).hidden = v !== id;
  }
}

function showProgress(song) {
  showOnly("#progress-view");
  $("#progress-title").textContent = song.name;
  const job = song.job || {};
  const pct = Math.max(4, ((job.step || 0) / (job.total || 5)) * 100);
  $("#progress-fill").style.width = pct + "%";
  $("#progress-message").textContent = job.message || "";
}

async function openSong(name) {
  currentSong = name;
  stopPlayback();
  showOnly("#song-view");
  $("#song-title").textContent = name;
  $("#song-meta").textContent = "Lade ...";

  let variant = $("#variant-select").value; // "original" | "einfach"
  let suffix = variant === "einfach" ? "_einfach" : "";
  const stamp = "?t=" + Date.now(); // auch Downloads nie aus dem Cache
  const base = "/api/result/" + encodeURIComponent(name) + "/";

  let [dataRes, xmlRes] = await Promise.all([
    fetch(base + "data" + suffix, NO_CACHE),
    fetch(base + "musicxml" + suffix, NO_CACHE),
  ]);
  if (variant === "einfach" && (!dataRes.ok || !xmlRes.ok)) {
    // Ältere Transkription ohne vereinfachte Fassung -> auf Original ausweichen
    variant = "original";
    suffix = "";
    $("#variant-select").value = "original";
    [dataRes, xmlRes] = await Promise.all([
      fetch(base + "data", NO_CACHE),
      fetch(base + "musicxml", NO_CACHE),
    ]);
    alert("Für diesen Song gibt es noch keine vereinfachte Fassung.\nBitte einmal neu transkribieren (Ordner in output\\ löschen und Song anklicken).");
  }
  if (!dataRes.ok || !xmlRes.ok) {
    $("#song-meta").textContent = "Fehler beim Laden der Noten (HTTP " + dataRes.status + " / " + xmlRes.status + ")";
    return;
  }
  $("#btn-midi").href = base + "midi" + suffix + stamp;
  $("#btn-xml").href = base + "musicxml" + suffix + stamp;

  playerData = await dataRes.json();
  const xml = await xmlRes.text();

  const meta = [];
  if (variant === "einfach") meta.push("Fassung: Vereinfacht");
  if (playerData.mode) meta.push(playerData.mode === "klavier" ? "Modus: Klavier-Transkription" : "Modus: Gesangsmelodie");
  if (playerData.key) meta.push("Tonart: " + playerData.key);
  meta.push("Tempo: " + playerData.tempo + " BPM");
  meta.push(playerData.melody.length + " Noten rechts");
  meta.push(playerData.chords.length + " links");
  $("#song-meta").textContent = meta.join("  ·  ");

  if (!osmd) {
    osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay("sheet", {
      autoResize: true,
      backend: "svg",
      drawTitle: true,
      drawComposer: false,
      drawPartNames: false,
    });
  }
  try {
    await osmd.load(xml);
    osmd.render();
  } catch (err) {
    console.error("Notendarstellung fehlgeschlagen:", err);
    $("#song-meta").textContent =
      "Fehler bei der Notendarstellung: " + (err && err.message ? err.message : err);
    return;
  }
  // Nach dem ersten Rendern kann eine Bildlaufleiste erscheinen und den
  // Platz verengen -> einmal mit der endgültigen Breite nachrendern.
  requestAnimationFrame(() => {
    const svg = document.querySelector("#sheet svg");
    const sheet = $("#sheet");
    if (svg && svg.width.baseVal.value > sheet.clientWidth - 40) {
      osmd.render();
    }
    resetCursor();
  });
  loadSongs(); // aktiven Eintrag markieren
}

$("#variant-select").addEventListener("change", () => {
  if (currentSong) openSong(currentSong);
});

/* ---------------- Positionslinie (OSMD-Cursor) ---------------- */

function cursorEnabled() {
  return $("#chk-cursor").checked;
}

function resetCursor() {
  if (!osmd || !osmd.cursor) return;
  osmd.cursor.reset();
  if (cursorEnabled()) osmd.cursor.show();
  else osmd.cursor.hide();
}

let lastScroll = 0;

function updateCursor(quarters) {
  if (!osmd || !osmd.cursor || !cursorEnabled()) return;
  const it = () => osmd.cursor.iterator;
  let guard = 0;
  while (!it().EndReached && it().currentTimeStamp.RealValue * 4 < quarters && guard++ < 300) {
    osmd.cursor.next();
  }
  // Ansicht sanft mitscrollen (höchstens einmal pro Sekunde)
  const now = performance.now();
  if (now - lastScroll > 1000 && osmd.cursor.cursorElement) {
    const el = osmd.cursor.cursorElement;
    const main = $("#main");
    const top = el.offsetTop;
    if (top < main.scrollTop + 60 || top > main.scrollTop + main.clientHeight - 160) {
      main.scrollTo({ top: top - main.clientHeight / 3, behavior: "smooth" });
    }
    lastScroll = now;
  }
}

$("#chk-cursor").addEventListener("change", () => {
  if (!osmd || !osmd.cursor) return;
  if (cursorEnabled()) osmd.cursor.show();
  else osmd.cursor.hide();
});

/* ---------------- Wiedergabe (WebAudio) ---------------- */

let audioCtx = null;
let playerData = null;
let playing = false;
let masterChain = null;
let activeNodes = [];   // {osc, until}
let eventQueue = [];
let queueIdx = 0;
let schedTimer = null;
let rafId = null;
let playStart = 0;
let secPerQuarter = 0.6;
let totalSec = 0;

function ensureCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

/* Klavierähnlicher Ton: Grundton + abklingende Obertöne (Sinus),
   Tiefpass gegen Schrillheit, anschlagabhängige Lautstärke. */
function pianoTone(ctx, dest, midi, when, duration, velocity) {
  const freq = 440 * Math.pow(2, (midi - 69) / 12);
  const vol = 0.05 + (velocity / 127) * 0.20;

  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = Math.min(freq * 5, 8000);
  filter.Q.value = 0.4;
  filter.connect(dest);

  const release = 0.4;
  const harmonics = [
    { mult: 1, amp: 1.0 },
    { mult: 2, amp: 0.30 },
    { mult: 3, amp: 0.10 },
  ];
  for (const h of harmonics) {
    if (freq * h.mult > 8500) continue;
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = freq * h.mult;

    const gain = ctx.createGain();
    const peak = vol * h.amp;
    const g = gain.gain;
    g.setValueAtTime(0, when);
    g.linearRampToValueAtTime(peak, when + 0.008);
    g.setTargetAtTime(peak * 0.2, when + 0.03, Math.max(duration * 0.55, 0.15) / h.mult);
    g.setTargetAtTime(0, when + duration, 0.1);

    osc.connect(gain).connect(filter);
    osc.start(when);
    osc.stop(when + duration + release);
    activeNodes.push({ osc, until: when + duration + release });
  }
}

function buildQueue() {
  const evs = [];
  if ($("#chk-right").checked) {
    for (const n of playerData.melody) {
      evs.push({ t: n.start, d: n.duration, midi: n.midi, vel: n.velocity || 88 });
    }
  }
  if ($("#chk-left").checked) {
    for (const c of playerData.chords) {
      for (const midi of c.midis) {
        evs.push({ t: c.start, d: c.duration, midi, vel: c.velocity || 55 });
      }
    }
  }
  evs.sort((a, b) => a.t - b.t);
  return evs;
}

/* Plant nur die Töne der nächsten ~1 Sekunde ein, statt alle auf einmal --
   sonst bricht die Audio-Engine bei tausenden Klangerzeugern zusammen. */
function scheduleChunk() {
  if (!playing) return;
  const ctx = audioCtx;
  const elapsed = ctx.currentTime - playStart;
  const horizon = elapsed + 1.0;
  while (queueIdx < eventQueue.length) {
    const ev = eventQueue[queueIdx];
    const tSec = ev.t * secPerQuarter;
    if (tSec > horizon) break;
    pianoTone(ctx, masterChain, ev.midi, playStart + tSec, ev.d * secPerQuarter, ev.vel);
    queueIdx++;
  }
  activeNodes = activeNodes.filter((n) => n.until > ctx.currentTime - 0.2);
}

function tick() {
  if (!playing) return;
  const elapsed = audioCtx.currentTime - playStart;
  updateCursor(elapsed / secPerQuarter);
  if (elapsed > totalSec + 1.5) {
    stopPlayback();
    return;
  }
  rafId = requestAnimationFrame(tick);
}

function startPlayback() {
  if (!playerData || playing) return;
  const ctx = ensureCtx();
  ctx.resume();

  const factor = parseInt($("#tempo-slider").value, 10) / 100;
  secPerQuarter = 60 / (playerData.tempo * factor);
  totalSec = playerData.totalQuarters * secPerQuarter;

  masterChain = ctx.createGain();
  masterChain.gain.value = 0.7;
  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -20;
  compressor.knee.value = 18;
  compressor.ratio.value = 6;
  compressor.attack.value = 0.003;
  compressor.release.value = 0.25;
  masterChain.connect(compressor);
  compressor.connect(ctx.destination);

  eventQueue = buildQueue();
  queueIdx = 0;
  playStart = ctx.currentTime + 0.15;
  playing = true;
  $("#btn-play").textContent = "⏸ Läuft ...";

  resetCursor();
  scheduleChunk();
  schedTimer = setInterval(scheduleChunk, 150);
  rafId = requestAnimationFrame(tick);
}

function stopPlayback() {
  clearInterval(schedTimer);
  cancelAnimationFrame(rafId);
  for (const n of activeNodes) {
    try { n.osc.stop(0); } catch (e) { /* schon gestoppt */ }
  }
  activeNodes = [];
  if (masterChain) {
    try { masterChain.disconnect(); } catch (e) { /* egal */ }
    masterChain = null;
  }
  playing = false;
  $("#btn-play").textContent = "▶ Abspielen";
  if (osmd && osmd.cursor) resetCursor();
}

/* Testton: zwei kurze Klaviertöne über dieselbe Klangkette --
   prüft unabhängig vom Song, ob Audio beim Nutzer ankommt. */
$("#btn-test").addEventListener("click", () => {
  const ctx = ensureCtx();
  ctx.resume();
  const g = ctx.createGain();
  g.gain.value = 0.8;
  g.connect(ctx.destination);
  const t = ctx.currentTime + 0.05;
  pianoTone(ctx, g, 64, t, 0.5, 95);        // E4
  pianoTone(ctx, g, 71, t + 0.55, 0.9, 95); // H4
});

$("#btn-play").addEventListener("click", () => (playing ? stopPlayback() : startPlayback()));
$("#btn-stop").addEventListener("click", stopPlayback);
$("#tempo-slider").addEventListener("input", () => {
  $("#tempo-value").textContent = $("#tempo-slider").value + " %";
});
$("#btn-pdf").addEventListener("click", () => window.print());

/* ---------------- Start ---------------- */
const versionTag = $("#version-tag");
if (versionTag) versionTag.textContent = "App-Version: " + PLAYER_VERSION + " ✓";
loadSongs();
