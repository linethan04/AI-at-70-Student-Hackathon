// Visit Recorder front end: record in the browser, send to app.py, show the cleaned transcript.

const $ = (id) => document.getElementById(id);
const STEPS = ["save", "transcribe", "speakers", "terms"];
const SPEAKER_COLORS = ["--spk-1", "--spk-2", "--spk-3", "--spk-4"];

let mediaRecorder = null;
let chunks = [];
let timerId = null;
let meterId = null;
let audioContext = null;

// ---------- setup ----------

async function loadConfig() {
  const cfg = await (await fetch("/api/config")).json();
  const select = $("savedSelect");
  select.length = 1;
  for (const r of cfg.recordings) {
    const opt = document.createElement("option");
    opt.value = r.name;
    opt.textContent = `${r.name.replace(/\.wav$/, "")}  (${fmtTime(r.seconds)})`;
    select.append(opt);
  }
  const notes = [];
  if (!cfg.has_anthropic) notes.push("No Anthropic key set: speakers and terms use the offline method.");
  if (!cfg.has_elevenlabs) {
    $("transcriber").querySelector('[value="elevenlabs"]').disabled = true;
    notes.push("No ElevenLabs key set: transcription uses Whisper.");
  }
  if (!cfg.has_anthropic) $("cleanup").querySelector('[value="claude"]').disabled = true;
  $("keyNote").textContent = notes.join(" ");
}

function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function options() {
  return {
    transcriber: $("transcriber").value,
    whisper_model: $("whisperModel").value,
    cleanup: $("cleanup").value,
    num_speakers: $("numSpeakers").value,
    keyterms: $("keyterms").value,
  };
}

// ---------- recording ----------

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    $("recordHint").textContent = "Could not use the microphone. Allow microphone access in the browser and try again.";
    return;
  }
  chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    const type = mediaRecorder.mimeType || "audio/webm";
    const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
    const blob = new Blob(chunks, { type });
    submit({ file: blob, filename: `recording.${ext}` });
  };
  mediaRecorder.start(1000);

  const started = Date.now();
  $("timer").textContent = "0:00";
  timerId = setInterval(() => ($("timer").textContent = fmtTime((Date.now() - started) / 1000)), 250);
  startMeter(stream);

  $("recordBtn").classList.add("recording");
  $("recordBtn").setAttribute("aria-pressed", "true");
  $("recordLabel").textContent = "Stop and transcribe";
  $("recordHint").textContent = "Recording… The bar moves when the microphone hears sound.";
}

function stopRecording() {
  clearInterval(timerId);
  cancelAnimationFrame(meterId);
  audioContext?.close();
  $("meterFill").style.width = "0";
  $("recordBtn").classList.remove("recording");
  $("recordBtn").setAttribute("aria-pressed", "false");
  $("recordLabel").textContent = "Start recording";
  $("recordHint").textContent = "Recording finished.";
  mediaRecorder.stop();
}

function startMeter(stream) {
  audioContext = new AudioContext();
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 512;
  audioContext.createMediaStreamSource(stream).connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  const tick = () => {
    analyser.getByteTimeDomainData(data);
    let peak = 0;
    for (const v of data) peak = Math.max(peak, Math.abs(v - 128));
    $("meterFill").style.width = `${Math.min(100, (peak / 128) * 160)}%`;
    meterId = requestAnimationFrame(tick);
  };
  tick();
}

$("recordBtn").addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state === "recording") stopRecording();
  else startRecording();
});

// ---------- upload / saved ----------

function updateProcessButton() {
  $("processBtn").disabled = !($("fileInput").files.length || $("savedSelect").value);
}
$("fileInput").addEventListener("change", () => { if ($("fileInput").files.length) $("savedSelect").value = ""; updateProcessButton(); });
$("savedSelect").addEventListener("change", () => { if ($("savedSelect").value) $("fileInput").value = ""; updateProcessButton(); });
$("processBtn").addEventListener("click", () => {
  const file = $("fileInput").files[0];
  if (file) submit({ file, filename: file.name });
  else submit({ recording: $("savedSelect").value });
});

// ---------- processing ----------

async function submit({ file, filename, recording }) {
  const form = new FormData();
  for (const [k, v] of Object.entries(options())) form.append(k, v);
  if (file) form.append("audio", file, filename);
  else form.append("recording", recording);

  $("resultsCard").hidden = true;
  $("progressCard").hidden = false;
  $("errorMsg").hidden = true;
  setStep("save", file ? "Uploading audio…" : "Loading recording…");
  $("processBtn").disabled = true;
  $("recordBtn").disabled = true;
  $("progressCard").scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const res = await fetch("/api/jobs", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || res.statusText);
    poll(body.job_id, Date.now());
  } catch (e) {
    showError(e.message);
  }
}

async function poll(jobId, started) {
  const job = await (await fetch(`/api/jobs/${jobId}`)).json();
  const elapsed = fmtTime((Date.now() - started) / 1000);
  if (job.status === "error") return showError(job.message);
  if (job.status === "done") {
    setStep("done", `Finished in ${elapsed}.`);
    finish();
    renderResult(job.result);
    loadConfig();
    return;
  }
  setStep(job.step, `${job.message}  (${elapsed})`);
  setTimeout(() => poll(jobId, started), 1000);
}

function setStep(step, message) {
  const idx = step === "done" ? STEPS.length : STEPS.indexOf(step);
  document.querySelectorAll("#steps li").forEach((li, i) => {
    li.classList.toggle("done", i < idx);
    li.classList.toggle("active", i === idx);
  });
  $("progressMsg").textContent = message;
}

function showError(message) {
  $("errorMsg").textContent = `Something went wrong: ${message}`;
  $("errorMsg").hidden = false;
  document.querySelectorAll("#steps li.active").forEach((li) => li.classList.remove("active"));
  finish();
}

function finish() {
  $("recordBtn").disabled = false;
  updateProcessButton();
}

// ---------- results ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

function seekButton(seconds, label) {
  return el("button", { class: "time", type: "button", title: "Play from here", onclick: () => {
    const p = $("player");
    p.currentTime = seconds;
    p.play();
  } }, label ?? fmtTime(seconds));
}

function speakerColor(label, speakers) {
  const i = speakers.findIndex((s) => s.label === label);
  return `var(${SPEAKER_COLORS[(i < 0 ? 0 : i) % SPEAKER_COLORS.length]})`;
}

// Text of one utterance, with corrected terms highlighted.
function utteranceNode(utt, index, corrections) {
  const span = el("span", utt.speaker_confidence === "low"
    ? { class: "unsure", title: "Speaker uncertain: please check who said this" } : {});
  let text = utt.text;
  for (const c of corrections.filter((c) => c.utterance_id === index)) {
    const at = text.toLowerCase().indexOf(c.corrected_text.toLowerCase());
    if (at < 0) continue;
    span.append(text.slice(0, at), el("mark", { title: `Heard: "${c.heard}"` }, text.slice(at, at + c.corrected_text.length)));
    text = text.slice(at + c.corrected_text.length);
  }
  span.append(text, " ");
  return span;
}

function renderResult(r) {
  $("resultsCard").hidden = false;
  $("method").textContent = `Speakers and terms reviewed by: ${r.method}`;
  $("player").src = r.audio_url;
  $("dlTxt").href = r.downloads.txt;
  $("dlJson").href = r.downloads.json;

  $("speakers").replaceChildren(...r.speakers.map((s) =>
    el("span", { class: "chip", style: `--c: ${speakerColor(s.label, r.speakers)}`, title: s.evidence },
      el("i"), `${s.label}: ${s.role}`)));

  // Group consecutive utterances by speaker into turns.
  const corrections = r.term_checks.filter((t) => t.status === "corrected");
  const turns = [];
  r.utterances.forEach((u, i) => {
    const last = turns[turns.length - 1];
    if (last && last.speaker === u.speaker) last.items.push([u, i]);
    else turns.push({ speaker: u.speaker, role: u.role, start: u.start, items: [[u, i]] });
  });
  $("transcript").replaceChildren(...turns.map((t) => {
    const color = speakerColor(t.speaker, r.speakers);
    return el("div", { class: "turn", style: `--c: ${color}` },
      el("div", { class: "turn-head" }, el("strong", {}, t.speaker), el("span", {}, t.role), seekButton(t.start)),
      el("p", {}, ...t.items.map(([u, i]) => utteranceNode(u, i, corrections))));
  }));

  const STATUS = {
    corrected: ["ok", "Corrected"], confirmed: ["ok", "Confirmed"], "needs review": ["warn", "Review"],
    "not in dictionary": ["bad", "Not found"], "not checked": ["warn", "Unchecked"],
  };
  $("terms").replaceChildren(...(r.term_checks.length ? r.term_checks.map((t) => {
    const [cls, label] = STATUS[t.status] || ["warn", t.status];
    const what = t.heard === t.corrected_text ? `“${t.heard}”` : `“${t.heard}” → “${t.corrected_text}”`;
    const src = t.dictionary_match ? ` (${t.dictionary_source}: ${t.dictionary_match})` : "";
    return el("li", {}, el("span", { class: `badge ${cls}` }, label), what, src);
  }) : [el("li", {}, "No medical terms found.")]));

  const timeOf = (id) => r.utterances[id]?.start ?? 0;
  const review = [
    ...r.issues.map((i) => el("li", {}, seekButton(timeOf(i.utterance_id)), " ", i.problem)),
    ...r.utterances.map((u, i) => [u, i])
      .filter(([u]) => u.speaker_confidence === "low" && u.text.split(/\s+/).length >= 4)
      .map(([u]) => el("li", {}, seekButton(u.start), ` Who said this? “${u.text}”`)),
  ];
  $("review").replaceChildren(...(review.length ? review : [el("li", {}, "Nothing flagged.")]));
  $("resultsCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

loadConfig();

// /advanced?open=<recording name> reopens a transcript processed earlier.
const toOpen = new URLSearchParams(location.search).get("open");
if (toOpen) {
  fetch(`/api/results/${encodeURIComponent(toOpen)}`)
    .then((res) => (res.ok ? res.json() : Promise.reject(new Error("No saved transcript with that name."))))
    .then(renderResult)
    .catch((e) => { $("progressCard").hidden = false; showError(e.message); });
}
