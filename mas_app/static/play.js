(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("play-data")?.textContent || "{}");
  const root = document.getElementById("play-root");
  const empty = document.getElementById("empty-play");
  const content = document.getElementById("play-content");
  const status = document.getElementById("connection-status");
  const speakerName = document.getElementById("speaker-name");
  const speakerMeta = document.getElementById("speaker-meta");
  const speakerCount = document.getElementById("speaker-count");
  const timer = document.getElementById("timer");
  const overtime = document.getElementById("overtime");
  const bar = document.getElementById("progress-bar");
  const descriptionSection = document.getElementById("description-section");
  const description = document.getElementById("speaker-description");
  const speakerFilesSection = document.getElementById("speaker-files-section");
  const speakerFiles = document.getElementById("speaker-files");
  const commonFiles = document.getElementById("common-files");
  const btnStart = document.getElementById("btn-start");
  const btnPause = document.getElementById("btn-pause");
  const btnReset = document.getElementById("btn-reset");
  const btnNext = document.getElementById("btn-next");
  const btnPrev = document.getElementById("btn-prev");
  const recordBtn = document.getElementById("record-btn");
  const recordStatus = document.getElementById("record-status");
  const recordingBox = recordBtn?.closest(".recording-box");

  const csrf = DATA.csrf || "";
  let currentState = null;
  let pollTimer = null;
  let polling = false;
  let recorder = null;
  let recorderStream = null;
  let chunks = [];
  let recordStartedAt = null;
  let sessionExpired = false;
  let recordingLimitTimer = null;
  let recordingFailed = false;

  const fmt = seconds => {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
    const secs = String(seconds % 60).padStart(2, "0");
    return `${mins}:${secs}`;
  };

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

  const speakerById = id => DATA.speakers.find(s => Number(s.id) === Number(id)) || null;

  const setStatus = (text, ok = true) => {
    status.textContent = text;
    status.className = ok ? "muted status-online" : "muted status-offline";
  };

  function renderFiles(list, target) {
    target.innerHTML = "";
    if (!list.length) {
      target.innerHTML = '<span class="muted">فایلی وجود ندارد.</span>';
      return;
    }
    for (const file of list) {
      const item = document.createElement("div");
      item.className = "file-item";
      item.innerHTML = `<a target="_blank" rel="noopener" href="/files/${file.id}">📄 ${esc(file.name)}</a>`;
      target.appendChild(item);
    }
  }

  function updateState(state) {
    currentState = state;
    if (!DATA.speakers.length || !state.current_speaker_id) {
      empty.hidden = false;
      content.hidden = true;
      speakerCount.textContent = "۰ / ۰";
      return;
    }
    empty.hidden = true;
    content.hidden = false;

    const serverSpeaker = state.current_speaker || null;
    const speaker = serverSpeaker ? {
      ...speakerById(state.current_speaker_id),
      ...serverSpeaker,
    } : speakerById(state.current_speaker_id);
    if (!speaker) {
      setStatus("وضعیت سخنران تغییر کرده است؛ صفحه را دوباره بارگذاری کنید.", false);
      return;
    }

    speakerName.textContent = speaker.name || "بدون نام";
    const meta = [speaker.gender, speaker.age ? `سن ${speaker.age}` : ""].filter(Boolean).join(" · ");
    speakerMeta.textContent = meta || "";
    speakerCount.textContent = `${state.current_index + 1} / ${state.total_speakers}`;
    timer.textContent = fmt(state.remaining_seconds);
    timer.classList.toggle("running", Boolean(state.running));
    overtime.textContent = state.overtime_seconds ? `زمان اضافه: +${fmt(state.overtime_seconds)}` : "";
    const limit = Number(state.limit_seconds ?? speaker.seconds ?? 0);
    const pct = limit > 0 ? Math.max(0, Math.min(100, state.remaining_seconds / limit * 100)) : 0;
    bar.style.width = `${pct}%`;

    if (speaker.description) {
      descriptionSection.hidden = false;
      description.textContent = speaker.description;
    } else {
      descriptionSection.hidden = true;
      description.textContent = "";
    }

    // This fixes the old live-files setting: personal files are only shown when enabled.
    speakerFilesSection.hidden = !DATA.live_files;
    if (DATA.live_files) renderFiles(speaker.files || [], speakerFiles);
    renderFiles(DATA.common || [], commonFiles);

    btnStart.disabled = Boolean(state.running);
    btnPause.disabled = !state.running;
    btnReset.disabled = !state.elapsed_seconds && !state.overtime_seconds;
    btnPrev.disabled = state.current_index <= 0;
    btnNext.disabled = state.current_index >= state.total_speakers - 1;
  }

  async function api(action) {
    const fd = new FormData();
    fd.append("csrf", csrf);
    const response = await fetch(`/api/rooms/${DATA.room_id}/${action}`, {
      method: "POST", body: fd, credentials: "same-origin", headers: {"Accept":"application/json"}
    });
    if (response.status === 401) {
      sessionExpired = true;
      setStatus("نشست شما منقضی شده است؛ دوباره وارد شوید.", false);
      stopPolling();
      return null;
    }
    if (!response.ok) {
      let msg = "عملیات ناموفق بود.";
      try { const body = await response.json(); if (body.detail) msg = body.detail; } catch (_) {}
      throw new Error(msg);
    }
    return response.json();
  }

  async function control(action) {
    [btnStart, btnPause, btnReset, btnPrev, btnNext].forEach(b => b.disabled = true);
    try {
      const state = await api(action);
      if (state) updateState(state);
    } catch (error) {
      alert(error.message || "عملیات ناموفق بود.");
      await syncOnce();
    }
  }

  async function syncOnce() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(`/api/rooms/${DATA.room_id}/state`, {credentials: "same-origin", headers: {"Accept":"application/json"}});
      if (response.status === 401) {
        sessionExpired = true;
        setStatus("نشست شما منقضی شده است؛ دوباره وارد شوید.", false);
        stopPolling();
        return;
      }
      if (!response.ok) throw new Error("state failed");
      updateState(await response.json());
      setStatus("همگام‌سازی فعال است", true);
    } catch (_) {
      setStatus("ارتباط با سرور قطع شده؛ تلاش مجدد…", false);
    } finally {
      polling = false;
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    if (document.hidden || sessionExpired) return;
    pollTimer = setTimeout(async () => { await syncOnce(); schedulePoll(); }, 1000);
  }
  function stopPolling() { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; }

  function chooseMimeType() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
    return candidates.find(type => window.MediaRecorder?.isTypeSupported?.(type)) || "";
  }

  async function toggleRecording() {
    if (!recordBtn) return;
    if (recorder && recorder.state === "recording") {
      recordBtn.disabled = true;
      recorder.stop();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      recordStatus.textContent = "ضبط صوت در این مرورگر در دسترس نیست.";
      return;
    }
    try {
      recorderStream = await navigator.mediaDevices.getUserMedia({audio: true});
      const mime = chooseMimeType();
      recorder = mime ? new MediaRecorder(recorderStream, {mimeType: mime}) : new MediaRecorder(recorderStream);
      chunks = [];
      recordingFailed = false;
      recordStartedAt = Date.now();
      clearTimeout(recordingLimitTimer);
      if (Number(DATA.max_recording_seconds) > 0) {
        recordingLimitTimer = setTimeout(() => {
          if (recorder?.state === "recording") {
            recordStatus.textContent = "به سقف مدت ضبط رسید؛ در حال ذخیره…";
            recorder.stop();
          }
        }, Number(DATA.max_recording_seconds) * 1000);
      }
      recorder.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        clearTimeout(recordingLimitTimer);
        const duration = Math.round((Date.now() - recordStartedAt) / 1000);
        recorderStream?.getTracks().forEach(track => track.stop());
        recorderStream = null;
        const actualType = recorder?.mimeType || "audio/webm";
        const blob = new Blob(chunks, {type: actualType});
        recorder = null;
        chunks = [];
        if (recordingFailed) {
          recordingFailed = false;
          return;
        }
        try {
          const fd = new FormData();
          fd.append("csrf", csrf);
          fd.append("duration_seconds", String(duration));
          const ext = actualType.includes("ogg") ? "ogg" : "webm";
          fd.append("file", blob, `recording-${new Date().toISOString().replace(/[:.]/g,"-")}.${ext}`);
          recordStatus.textContent = "در حال ذخیره ضبط…";
          const response = await fetch(`/api/rooms/${DATA.room_id}/recording`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
          if (!response.ok) {
            let message = "ذخیره ضبط ناموفق بود.";
            try { const body = await response.json(); if (body.detail) message = body.detail; } catch (_) {}
            throw new Error(message);
          }
          recordStatus.textContent = "ضبط ذخیره شد.";
          if (recordingBox) recordingBox.classList.remove("recording");
        } catch (error) {
          recordStatus.textContent = error.message || "ذخیره ضبط ناموفق بود.";
        } finally {
          recordBtn.disabled = false;
          recordBtn.textContent = "● شروع ضبط";
        }
      };
      recorder.onerror = () => {
        recordingFailed = true;
        clearTimeout(recordingLimitTimer);
        recorderStream?.getTracks().forEach(track => track.stop());
        recorderStream = null;
        recorder = null;
        recordStatus.textContent = "ضبط با خطا متوقف شد.";
        recordBtn.disabled = false;
        recordBtn.textContent = "● شروع ضبط";
      };
      recorder.start(1000);
      recordBtn.textContent = "■ توقف ضبط";
      recordStatus.textContent = "در حال ضبط…";
      if (recordingBox) recordingBox.classList.add("recording");
    } catch (_) {
      clearTimeout(recordingLimitTimer);
      recorderStream?.getTracks().forEach(track => track.stop());
      recorderStream = null;
      recordStatus.textContent = "اجازهٔ دسترسی به میکروفون داده نشد یا میکروفون در دسترس نیست.";
    }
  }

  btnStart?.addEventListener("click", () => control("start"));
  btnPause?.addEventListener("click", () => control("pause"));
  btnReset?.addEventListener("click", () => control("reset"));
  btnNext?.addEventListener("click", () => control("next"));
  btnPrev?.addEventListener("click", () => control("prev"));
  recordBtn?.addEventListener("click", toggleRecording);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling(); else { syncOnce(); schedulePoll(); }
  });
  window.addEventListener("beforeunload", event => {
    if (recorder?.state === "recording") {
      event.preventDefault();
      event.returnValue = "ضبط صدا هنوز فعال است.";
    }
  });

  renderFiles(DATA.common || [], commonFiles);
  syncOnce().finally(schedulePoll);
})();
