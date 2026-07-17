/**
 * Elara's Whisper — Glass Eye dial + loom UI
 */

const PRESETS = [
  { name: "pose", value: 0.0 },
  { name: "breath", value: 0.25 },
  { name: "recommended", value: 0.45 },
  { name: "fluff", value: 0.8 },
  { name: "grandmother", value: 1.0 },
];

const STAGE_ORDER = ["unstitch", "air", "dynamics", "warmth"];

const state = {
  files: [],
  intensity: 0.45,
  dragging: false,
  working: false,
  downloadUrl: null,
};

// ---------------------------------------------------------------------------
// Glass Eye dial (canvas)
// ---------------------------------------------------------------------------

function nearestPreset(v) {
  let best = null;
  let bestD = Infinity;
  for (const p of PRESETS) {
    const d = Math.abs(p.value - v);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  if (bestD <= 0.04) return best.name;
  if (v <= 0) return "pose";
  if (v < 0.2) return "barely breathing";
  if (v < 0.4) return "soft air";
  if (v < 0.55) return "recommended";
  if (v < 0.75) return "deepening";
  if (v < 0.95) return "fluff";
  return "grandmother";
}

function valueToAngle(v) {
  // Map 0..1.2 across ~270° arc (bottom-left → top → bottom-right)
  const t = Math.min(Math.max(v / 1.2, 0), 1);
  const start = Math.PI * 0.75; // 135°
  const sweep = Math.PI * 1.5; // 270°
  return start + t * sweep;
}

function angleToValue(angle) {
  const start = Math.PI * 0.75;
  const sweep = Math.PI * 1.5;
  let a = angle;
  // normalize relative to start
  let rel = a - start;
  while (rel < 0) rel += Math.PI * 2;
  while (rel > Math.PI * 2) rel -= Math.PI * 2;
  if (rel > sweep) {
    // snap to nearer endpoint
    rel = rel - sweep < Math.PI * 2 - rel ? sweep : 0;
  }
  const t = rel / sweep;
  return Math.round(t * 1.2 * 100) / 100;
}

function pointerAngle(canvas, clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  return Math.atan2(clientY - cy, clientX - cx);
}

function drawEye(canvas, intensity, animT = 0) {
  const dpr = window.devicePixelRatio || 1;
  const css = canvas.clientWidth || 360;
  if (canvas.width !== Math.floor(css * dpr)) {
    canvas.width = Math.floor(css * dpr);
    canvas.height = Math.floor(css * dpr);
  }
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const cx = W / 2;
  const cy = H / 2;
  const R = Math.min(W, H) * 0.42;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, W, H);

  // Outer void disc
  const voidGrad = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.15);
  voidGrad.addColorStop(0, "rgba(22, 26, 40, 0.95)");
  voidGrad.addColorStop(0.7, "rgba(10, 11, 16, 0.98)");
  voidGrad.addColorStop(1, "rgba(7, 8, 13, 0)");
  ctx.beginPath();
  ctx.arc(cx, cy, R * 1.12, 0, Math.PI * 2);
  ctx.fillStyle = voidGrad;
  ctx.fill();

  // Track arc (background)
  ctx.beginPath();
  ctx.arc(cx, cy, R, Math.PI * 0.75, Math.PI * 0.75 + Math.PI * 1.5);
  ctx.strokeStyle = "rgba(201, 162, 39, 0.15)";
  ctx.lineWidth = R * 0.06;
  ctx.lineCap = "round";
  ctx.stroke();

  // Active arc — gold → teal by intensity
  const ang = valueToAngle(intensity);
  const activeGrad = ctx.createLinearGradient(cx - R, cy, cx + R, cy);
  activeGrad.addColorStop(0, "#c9a227");
  activeGrad.addColorStop(0.5, "#5eead4");
  activeGrad.addColorStop(1, "#8b7cf6");
  ctx.beginPath();
  ctx.arc(cx, cy, R, Math.PI * 0.75, ang);
  ctx.strokeStyle = activeGrad;
  ctx.lineWidth = R * 0.07;
  ctx.shadowColor = "rgba(94, 234, 212, 0.45)";
  ctx.shadowBlur = 18 * dpr;
  ctx.stroke();
  ctx.shadowBlur = 0;

  // Iris body
  const irisR = R * 0.62;
  const breath = 1 + Math.sin(animT * 0.0018) * 0.012 * (0.3 + intensity);
  const irisOuter = ctx.createRadialGradient(
    cx - irisR * 0.2,
    cy - irisR * 0.25,
    irisR * 0.1,
    cx,
    cy,
    irisR
  );
  const tealMix = Math.min(intensity, 1);
  irisOuter.addColorStop(0, `rgba(${90 + tealMix * 40}, ${120 + tealMix * 80}, ${180}, 0.95)`);
  irisOuter.addColorStop(0.45, `rgba(40, 50, 90, 0.98)`);
  irisOuter.addColorStop(0.75, `rgba(20, 22, 40, 1)`);
  irisOuter.addColorStop(1, `rgba(12, 14, 24, 1)`);

  ctx.beginPath();
  ctx.arc(cx, cy, irisR * breath, 0, Math.PI * 2);
  ctx.fillStyle = irisOuter;
  ctx.fill();

  // Iris fibers (radial lines)
  ctx.save();
  ctx.translate(cx, cy);
  const fibers = 48;
  for (let i = 0; i < fibers; i++) {
    const a = (i / fibers) * Math.PI * 2 + animT * 0.00015 * intensity;
    const wobble = Math.sin(i * 1.7 + animT * 0.002) * 0.04;
    ctx.rotate(0); // keep absolute
    const x0 = Math.cos(a) * irisR * 0.28;
    const y0 = Math.sin(a) * irisR * 0.28;
    const x1 = Math.cos(a + wobble) * irisR * 0.92;
    const y1 = Math.sin(a + wobble) * irisR * 0.92;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.strokeStyle = `rgba(94, 234, 212, ${0.04 + intensity * 0.08})`;
    ctx.lineWidth = 1 * dpr;
    ctx.stroke();
  }
  ctx.restore();

  // Gold ring around iris
  ctx.beginPath();
  ctx.arc(cx, cy, irisR * breath, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(201, 162, 39, 0.55)";
  ctx.lineWidth = 1.5 * dpr;
  ctx.stroke();

  // Pupil — shrinks slightly with intensity (living eye)
  const pupilR = irisR * (0.32 - intensity * 0.06);
  const pupilGrad = ctx.createRadialGradient(
    cx - pupilR * 0.3,
    cy - pupilR * 0.3,
    pupilR * 0.1,
    cx,
    cy,
    pupilR
  );
  pupilGrad.addColorStop(0, "#1a2038");
  pupilGrad.addColorStop(0.6, "#05060a");
  pupilGrad.addColorStop(1, "#000");
  ctx.beginPath();
  ctx.arc(cx, cy, pupilR, 0, Math.PI * 2);
  ctx.fillStyle = pupilGrad;
  ctx.fill();

  // Catchlight
  ctx.beginPath();
  ctx.arc(cx - pupilR * 0.35, cy - pupilR * 0.35, pupilR * 0.22, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(232, 230, 240, 0.55)";
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx + pupilR * 0.25, cy + pupilR * 0.3, pupilR * 0.1, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(94, 234, 212, 0.35)";
  ctx.fill();

  // Thumb / pupil pointer on arc
  const tx = cx + Math.cos(ang) * R;
  const ty = cy + Math.sin(ang) * R;
  ctx.beginPath();
  ctx.arc(tx, ty, R * 0.07, 0, Math.PI * 2);
  ctx.fillStyle = "#e8d48b";
  ctx.shadowColor = "rgba(201, 162, 39, 0.8)";
  ctx.shadowBlur = 12 * dpr;
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.beginPath();
  ctx.arc(tx, ty, R * 0.03, 0, Math.PI * 2);
  ctx.fillStyle = "#0a0b10";
  ctx.fill();

  // Tick marks for presets
  for (const p of PRESETS) {
    const pa = valueToAngle(p.value);
    const inner = R * 0.88;
    const outer = R * 0.96;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(pa) * inner, cy + Math.sin(pa) * inner);
    ctx.lineTo(cx + Math.cos(pa) * outer, cy + Math.sin(pa) * outer);
    ctx.strokeStyle =
      Math.abs(p.value - intensity) < 0.03
        ? "rgba(232, 212, 139, 0.95)"
        : "rgba(201, 162, 39, 0.35)";
    ctx.lineWidth = 2 * dpr;
    ctx.stroke();
  }
}

function setIntensity(v, { fromPreset = false } = {}) {
  state.intensity = Math.min(Math.max(Number(v) || 0, 0), 1.2);
  const valEl = document.getElementById("intensity-value");
  const nameEl = document.getElementById("intensity-name");
  const canvas = document.getElementById("eye-dial");
  valEl.textContent = state.intensity.toFixed(2);
  nameEl.textContent = nearestPreset(state.intensity);
  canvas.setAttribute("aria-valuenow", String(state.intensity));

  document.querySelectorAll(".preset-btn").forEach((btn) => {
    const pv = parseFloat(btn.dataset.value);
    btn.classList.toggle("active", Math.abs(pv - state.intensity) < 0.001);
  });
}

function initDial() {
  const canvas = document.getElementById("eye-dial");
  let animId = 0;
  let t0 = performance.now();

  function frame(now) {
    drawEye(canvas, state.intensity, now - t0);
    animId = requestAnimationFrame(frame);
  }
  animId = requestAnimationFrame(frame);

  function onPointer(e) {
    if (!state.dragging) return;
    e.preventDefault();
    const ang = pointerAngle(canvas, e.clientX, e.clientY);
    setIntensity(angleToValue(ang));
  }

  canvas.addEventListener("pointerdown", (e) => {
    state.dragging = true;
    canvas.setPointerCapture(e.pointerId);
    const ang = pointerAngle(canvas, e.clientX, e.clientY);
    setIntensity(angleToValue(ang));
  });
  canvas.addEventListener("pointermove", onPointer);
  canvas.addEventListener("pointerup", () => {
    state.dragging = false;
  });
  canvas.addEventListener("pointercancel", () => {
    state.dragging = false;
  });

  canvas.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.05 : 0.01;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      setIntensity(state.intensity + step);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      setIntensity(state.intensity - step);
    } else if (e.key === "Home") {
      setIntensity(0);
    } else if (e.key === "End") {
      setIntensity(1);
    }
  });

  // wheel fine-tune
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.02 : 0.02;
      setIntensity(state.intensity + delta);
    },
    { passive: false }
  );
}

// ---------------------------------------------------------------------------
// Files
// ---------------------------------------------------------------------------

function formatSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function renderFiles() {
  const list = document.getElementById("file-list");
  const zone = document.getElementById("dropzone");
  const btn = document.getElementById("whisper-btn");

  if (!state.files.length) {
    list.hidden = true;
    list.innerHTML = "";
    zone.classList.remove("has-files");
    btn.disabled = true;
    return;
  }

  zone.classList.add("has-files");
  list.hidden = false;
  list.innerHTML = "";
  state.files.forEach((file, i) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="dot"></span>
      <span class="name" title="${file.name}">${file.name}</span>
      <span class="size">${formatSize(file.size)}</span>
      <button type="button" aria-label="Remove ${file.name}" data-i="${i}">×</button>
    `;
    list.appendChild(li);
  });
  list.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      state.files.splice(parseInt(b.dataset.i, 10), 1);
      renderFiles();
    });
  });
  btn.disabled = state.working;
}

function addFiles(fileList) {
  const allowed = /\.(wav|flac|ogg|aiff|aif|mp3|caf)$/i;
  const incoming = Array.from(fileList || []).filter(
    (f) => allowed.test(f.name) || (f.type && f.type.startsWith("audio/"))
  );
  for (const f of incoming) {
    if (!state.files.some((x) => x.name === f.name && x.size === f.size)) {
      state.files.push(f);
    }
  }
  renderFiles();
  if (incoming.length === 0 && fileList && fileList.length) {
    setStatus("That format isn’t supported — try wav, flac, mp3, ogg, aiff.", "error");
  }
}

function initDropzone() {
  const zone = document.getElementById("dropzone");
  const input = document.getElementById("file-input");

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    addFiles(input.files);
    input.value = "";
  });

  ["dragenter", "dragover"].forEach((ev) => {
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
    });
  });
  zone.addEventListener("drop", (e) => {
    addFiles(e.dataTransfer.files);
  });

  // Global drop prevention
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());
}

// ---------------------------------------------------------------------------
// Presets + stages
// ---------------------------------------------------------------------------

function initPresets() {
  const root = document.getElementById("presets");
  PRESETS.forEach((p) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-btn" + (p.value === 0.45 ? " active" : "");
    btn.textContent = p.name;
    btn.dataset.value = String(p.value);
    btn.title = `intensity ${p.value}`;
    btn.addEventListener("click", () => setIntensity(p.value, { fromPreset: true }));
    root.appendChild(btn);
  });
}

function setStages(mode) {
  // mode: idle | run | done
  const items = document.querySelectorAll(".stages li");
  items.forEach((li) => li.classList.remove("active", "done"));
  if (mode === "idle") return;
  if (mode === "done") {
    items.forEach((li) => li.classList.add("done"));
    return;
  }
}

function animateStages(durationMs) {
  const items = STAGE_ORDER.map((s) =>
    document.querySelector(`.stages li[data-stage="${s}"]`)
  );
  items.forEach((li) => li && li.classList.remove("active", "done"));
  const step = durationMs / STAGE_ORDER.length;
  const timers = [];
  STAGE_ORDER.forEach((_, i) => {
    timers.push(
      setTimeout(() => {
        items.forEach((li, j) => {
          if (!li) return;
          li.classList.toggle("active", j === i);
          li.classList.toggle("done", j < i);
        });
      }, step * i)
    );
  });
  return () => timers.forEach(clearTimeout);
}

// ---------------------------------------------------------------------------
// Process
// ---------------------------------------------------------------------------

function setStatus(msg, kind = "") {
  const el = document.getElementById("status");
  el.textContent = msg || "";
  el.className = "status" + (kind ? ` ${kind}` : "");
}

async function runWhisper() {
  if (state.working || !state.files.length) return;

  state.working = true;
  const btn = document.getElementById("whisper-btn");
  btn.disabled = true;
  btn.classList.add("working");
  btn.querySelector(".btn-label").textContent = "The loom is breathing…";
  setStatus("Spectral unstitching in progress…");
  document.getElementById("result").hidden = true;

  if (state.downloadUrl) {
    URL.revokeObjectURL(state.downloadUrl);
    state.downloadUrl = null;
  }

  const cancelStages = animateStages(Math.max(2400, state.files.length * 900));

  const fd = new FormData();
  state.files.forEach((f) => fd.append("files", f, f.name));
  fd.append("intensity", String(state.intensity));
  fd.append("haze_hz", String(document.getElementById("haze").value || 6000));
  const seed = document.getElementById("seed").value;
  if (seed !== "") fd.append("seed", seed);

  try {
    const res = await fetch("/api/process", { method: "POST", body: fd });
    cancelStages();

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        detail = j.error || detail;
      } catch (_) {
        /* ignore */
      }
      throw new Error(detail);
    }

    const blob = await res.blob();
    const disp = res.headers.get("Content-Disposition") || "";
    let filename = "elaras_whisper.wav";
    const m = /filename="?([^";]+)"?/i.exec(disp);
    if (m) filename = m[1];

    state.downloadUrl = URL.createObjectURL(blob);
    const link = document.getElementById("download-link");
    link.href = state.downloadUrl;
    link.download = filename;
    document.getElementById("result-meta").textContent =
      `${filename} · intensity ${state.intensity.toFixed(2)} · ${state.files.length} source(s)`;
    document.getElementById("result").hidden = false;
    setStages("done");
    setStatus("The glass eye softens.", "ok");
  } catch (err) {
    cancelStages();
    setStages("idle");
    setStatus(err.message || String(err), "error");
  } finally {
    state.working = false;
    btn.classList.remove("working");
    btn.querySelector(".btn-label").textContent = "Unbind the glass eye";
    btn.disabled = !state.files.length;
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

function boot() {
  initPresets();
  initDial();
  initDropzone();
  setIntensity(0.45);
  document.getElementById("whisper-btn").addEventListener("click", runWhisper);

  fetch("/api/presets")
    .then((r) => r.json())
    .then(() => setStatus("Loom ready. Lay a track upon the glass."))
    .catch(() => setStatus("Loom ready (offline presets)."));
}

boot();
