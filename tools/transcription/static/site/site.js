// Visit Recorder (simple page): record or upload, then show the transcript.
// Uses the server's fast defaults (Whisper base; Claude cleanup if a key is set, else offline).

const $ = (id) => document.getElementById(id);
const SCREENS = ["start", "recording", "working", "error", "result"];
const STEPS = ["save", "transcribe", "speakers", "terms"];
const STEP_TITLES = {
  save: "Uploading…", transcribe: "Writing down what was said…",
  speakers: "Working out who said what…", terms: "Checking medical terms…",
};
const SPEAKER_COLORS = ["--spk-1", "--spk-2", "--spk-3", "--spk-4"];
const ROLE_NAMES = { clinician: "Clinician", patient: "Patient", "family member or caregiver": "Family / caregiver" };

let recorder = null;
let stream = null;
let cancelled = false;
let timerId = null;
let meterId = null;
let audioCtx = null;
let wakeLock = null;
let plainText = "";

function show(name) {
  for (const s of SCREENS) $(s).hidden = s !== name;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => ($("toast").hidden = true), 2200);
}

function fail(message) {
  $("errorText").textContent = message;
  show("error");
}

// ---------- recording ----------

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    return fail("This browser can't record audio. Try Chrome or Safari, or use Upload audio instead.");
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch {
    return fail("Microphone access was blocked. Allow the microphone for this site in your browser settings, then try again.");
  }

  const chunks = [];
  cancelled = false;
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = () => {
    cleanupRecording();
    if (cancelled) return show("start");
    const type = recorder.mimeType || "audio/webm";
    const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
    upload(new Blob(chunks, { type }), `recording.${ext}`);
  };
  recorder.start(1000);

  const started = Date.now();
  $("timer").textContent = "0:00";
  timerId = setInterval(() => ($("timer").textContent = fmtTime((Date.now() - started) / 1000)), 250);
  startMeter();
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch { /* not supported: fine */ }
  show("recording");
}

const WAVE_BARS = 28;

// Live waveform: one bar per frequency band, so it visibly reacts to speech.
function startMeter() {
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.75;
  audioCtx.createMediaStreamSource(stream).connect(analyser);
  const bars = Array.from({ length: WAVE_BARS }, () => document.createElement("span"));
  $("wave").replaceChildren(...bars);
  const data = new Uint8Array(analyser.frequencyBinCount);
  const tick = () => {
    analyser.getByteFrequencyData(data);
    bars.forEach((bar, i) => {
      // Mirror around the middle so the shape looks balanced; speech lives in the low bins.
      const bin = 2 + Math.round(Math.abs(i - WAVE_BARS / 2) * 1.6);
      bar.style.height = `${Math.max(6, (data[bin] / 255) * 72)}px`;
    });
    meterId = requestAnimationFrame(tick);
  };
  tick();
}

function cleanupRecording() {
  clearInterval(timerId);
  cancelAnimationFrame(meterId);
  audioCtx?.close();
  stream?.getTracks().forEach((t) => t.stop());
  wakeLock?.release?.();
  wakeLock = null;
  $("wave").replaceChildren();
}

$("recordBtn").addEventListener("click", startRecording);
$("stopBtn").addEventListener("click", () => recorder?.state === "recording" && recorder.stop());
$("cancelBtn").addEventListener("click", () => {
  cancelled = true;
  if (recorder?.state === "recording") recorder.stop();
  else show("start");
});

// ---------- upload & progress ----------

$("fileInput").addEventListener("change", () => {
  const file = $("fileInput").files[0];
  $("fileInput").value = "";
  if (file) upload(file, file.name);
});

async function upload(blob, filename) {
  setProgress("save");
  show("working");
  const form = new FormData();
  form.append("audio", blob, filename);
  try {
    const res = await fetch("/api/jobs", { method: "POST", body: form });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || (res.status === 413 ? "That file is too large." : "The upload didn't go through."));
    poll(body.job_id, Date.now());
  } catch (e) {
    fail(e.message === "Failed to fetch" ? "Couldn't reach the server. Check your connection and try again." : e.message);
  }
}

async function poll(jobId, started) {
  let job;
  try {
    job = await (await fetch(`/api/jobs/${jobId}`)).json();
  } catch {
    return setTimeout(() => poll(jobId, started), 2000);  // brief network hiccup: keep waiting
  }
  if (job.status === "error") return fail(friendlyError(job.message));
  if (job.status === "done") return showResult(job.result);
  setProgress(job.step, job.message?.startsWith("Waiting") ? job.message : null, started);
  setTimeout(() => poll(jobId, started), 1000);
}

function friendlyError(message) {
  if (/No speech/i.test(message)) return "No speech was found in the recording. Try again a little closer to the microphone.";
  return "The transcript couldn't be made. Please try again.";
}

function setProgress(step, note, started) {
  const idx = STEPS.indexOf(step);
  document.querySelectorAll("#progress li").forEach((li, i) => {
    li.classList.toggle("done", i < idx);
    li.classList.toggle("active", i === idx);
  });
  $("workTitle").textContent = note || STEP_TITLES[step] || "Working…";
  if (started) {
    $("workDetail").textContent = `${fmtTime((Date.now() - started) / 1000)} so far · about a minute for every 7 minutes of audio`;
  }
}

// ---------- result ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function speakerName(label, speakers) {
  const role = speakers.find((s) => s.label === label)?.role;
  return ROLE_NAMES[role] || label;
}

function speakerColor(label, speakers) {
  const i = Math.max(0, speakers.findIndex((s) => s.label === label));
  return `var(${SPEAKER_COLORS[i % SPEAKER_COLORS.length]})`;
}

function playIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 10 10");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<path d="M2 1l7 4-7 4z"/>';
  return svg;
}

function playFrom(seconds) {
  $("player").currentTime = seconds;
  $("player").play().catch(() => {});
}

function utteranceNode(utt, index, corrections) {
  const span = el("span", utt.speaker_confidence === "low" ? { class: "unsure", title: "Not sure who said this" } : {});
  let text = utt.text;
  for (const c of corrections.filter((c) => c.utterance_id === index)) {
    const at = text.toLowerCase().indexOf(c.corrected_text.toLowerCase());
    if (at < 0) continue;
    const heard = `Heard as “${c.heard}”`;
    span.append(text.slice(0, at), el("mark", { title: heard, tabindex: "0", onclick: () => toast(heard) },
      text.slice(at, at + c.corrected_text.length)));
    text = text.slice(at + c.corrected_text.length);
  }
  span.append(text, " ");
  return span;
}

function showResult(r) {
  $("player").src = r.audio_url;
  $("downloadTxt").href = r.downloads.txt;

  const named = r.speakers.filter((s) => r.utterances.some((u) => u.speaker === s.label));
  $("speakers").replaceChildren(...named.map((s) =>
    el("span", { class: "chip", style: `--c:${speakerColor(s.label, r.speakers)}` }, el("i"), speakerName(s.label, r.speakers))));

  // Consecutive lines by the same person form one turn.
  const corrections = r.term_checks.filter((t) => t.status === "corrected");
  const turns = [];
  r.utterances.forEach((u, i) => {
    const last = turns[turns.length - 1];
    if (last && last.speaker === u.speaker) last.items.push([u, i]);
    else turns.push({ speaker: u.speaker, start: u.start, items: [[u, i]] });
  });
  $("transcript").replaceChildren(...turns.map((t) =>
    el("article", { class: "turn", style: `--c:${speakerColor(t.speaker, r.speakers)}` },
      el("div", { class: "turn-head" },
        el("span", { class: "who" }, speakerName(t.speaker, r.speakers)),
        el("button", { class: "ts", type: "button", "aria-label": `Play from ${fmtTime(t.start)}`, onclick: () => playFrom(t.start) },
          playIcon(), fmtTime(t.start))),
      el("p", {}, ...t.items.map(([u, i]) => utteranceNode(u, i, corrections))))));

  const duration = r.utterances.length ? r.utterances[r.utterances.length - 1].end : 0;
  $("summary").textContent = `${fmtTime(duration)} · ${named.length} speaker${named.length === 1 ? "" : "s"}`;

  plainText = turns.map((t) =>
    `[${fmtTime(t.start)}] ${speakerName(t.speaker, r.speakers)}: ${t.items.map(([u]) => u.text).join(" ")}`).join("\n\n");

  // Things a person should double-check.
  const checks = [
    ...r.issues.map((i) => i.problem),
    ...r.term_checks.filter((t) => !["corrected", "confirmed"].includes(t.status))
      .map((t) => `Check the word “${t.heard}”.`),
  ];
  const unsureCount = r.utterances.filter((u) => u.speaker_confidence === "low" && u.text.split(/\s+/).length >= 4).length;
  if (unsureCount) checks.push(`${unsureCount} line${unsureCount > 1 ? "s are" : " is"} underlined because it's unclear who said ${unsureCount > 1 ? "them" : "it"}.`);
  $("checkList").replaceChildren(...checks.map((c) => el("li", {}, c)));
  $("checkBox").hidden = !checks.length;

  const checked = r.term_checks.filter((t) => ["corrected", "confirmed"].includes(t.status));
  $("termsSummary").textContent = `Medical terms checked (${checked.length})`;
  $("termsList").replaceChildren(...checked.map((t) => el("li", {},
    t.status === "corrected" ? `“${t.heard}” corrected to “${t.corrected_text}”` : `“${t.heard}” confirmed`)));
  $("termsBox").hidden = !checked.length;

  show("result");
}

$("copyBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(plainText);
    toast("Transcript copied");
  } catch {
    toast("Couldn't copy. Use Download instead.");
  }
});
for (const id of ["newBtn", "newBtn2"]) {
  $(id).addEventListener("click", () => { $("player").pause(); show("start"); });
}
$("retryBtn").addEventListener("click", () => show("start"));
