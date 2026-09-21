(() => {
  "use strict";

  const DATA = JSON.parse(document.getElementById("play-data")?.textContent || "{}");
  const $ = id => document.getElementById(id);
  const empty = $("empty-play");
  const content = $("play-content");
  const status = $("connection-status");
  const speakerName = $("speaker-name");
  const speakerMeta = $("speaker-meta");
  const speakerCount = $("speaker-count");
  const timer = $("timer");
  const overtime = $("overtime");
  const bar = $("progress-bar");
  const descriptionSection = $("description-section");
  const description = $("speaker-description");
  const speakerFilesSection = $("speaker-files-section");
  const speakerFiles = $("speaker-files");
  const commonFiles = $("common-files");
  const btnStart = $("btn-start");
  const btnPause = $("btn-pause");
  const btnReset = $("btn-reset");
  const btnNext = $("btn-next");
  const btnPrev = $("btn-prev");
  const btnFinish = $("btn-finish");
  const btnContinue = $("btn-continue");
  const btnFinishAlert = $("btn-finish-alert");
  const btnDelete = $("btn-delete-current-speaker");
  const timeAlert = $("time-alert");
  const recordStatus = $("record-status");
  const recordDot = $("record-dot");
  const deleteDialog = $("speaker-delete-dialog");

  const csrf = DATA.csrf || "";
  let state = null;
  let polling = false;
  let pollTimer = null;
  let destroyed = false;
  let recorder = null;
  let stream = null;
  let chunks = [];
  let recordingSpeakerId = null;
  let recordedSeconds = 0;
  let recordingStartedAt = 0;
  let pendingRecording = null;

  const fmt = seconds => {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
  };

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const speakerById = id => DATA.speakers.find(s => Number(s.id) === Number(id)) || null;
  const setStatus = (text, ok = true) => {
    if (!status) return;
    status.textContent = text;
    status.className = ok ? "muted status-online" : "muted status-offline";
  };
  const setRecordUI = (mode, text) => {
    if (recordDot) recordDot.classList.toggle("active", mode === "recording");
    if (recordStatus) recordStatus.textContent = text || "";
  };

  function renderFiles(list, target) {
    if (!target) return;
    target.replaceChildren();
    if (!list?.length) {
      target.innerHTML = '<span class="muted">فایلی وجود ندارد.</span>';
      return;
    }
    for (const file of list) {
      const item = document.createElement("div");
      item.className = "file-item";
      item.innerHTML = `<a target="_blank" rel="noopener" href="/files/${encodeURIComponent(file.id)}">📄 ${esc(file.name)}</a>`;
      target.appendChild(item);
    }
  }

  function setButtons() {
    if (!state) return;
    const running = Boolean(state.running);
    const waiting = Boolean(state.awaiting_decision);
    const completed = Boolean(state.completed);
    const hasPending = Boolean(pendingRecording);
    const hasCurrentRecorder = Boolean(recorder && recordingSpeakerId === state.current_speaker_id);

    if (btnStart) btnStart.disabled = running || waiting || completed || hasPending;
    if (btnPause) btnPause.disabled = !running || hasPending;
    if (btnContinue) btnContinue.disabled = !waiting || hasPending;
    if (btnFinish) btnFinish.disabled = !state.current_speaker_id || completed || Boolean(hasPending && pendingRecording?.speakerId !== state.current_speaker_id);
    if (btnFinishAlert) btnFinishAlert.disabled = !waiting || Boolean(hasPending);
    if (btnReset) btnReset.disabled = running || waiting || hasCurrentRecorder || hasPending || !(Number(state.elapsed_seconds) || Number(state.overtime_seconds));
    if (btnPrev) btnPrev.disabled = running || waiting || hasCurrentRecorder || hasPending || state.current_index <= 0;
    if (btnNext) btnNext.disabled = running || waiting || hasCurrentRecorder || hasPending || state.current_index >= state.total_speakers - 1;
    // Deletion is intentionally allowed while the timer is running: the active recorder
    // is stopped first and the user is asked whether to save it.
    if (btnDelete) btnDelete.disabled = !state.current_speaker_id || Boolean(hasPending && pendingRecording?.speakerId !== state.current_speaker_id) || completed;
  }

  function updateState(next) {
    state = next;
    if (!DATA.speakers.length || !next.current_speaker_id || next.completed && !next.current_speaker_id) {
      empty.hidden = false;
      content.hidden = true;
      if (speakerCount) speakerCount.textContent = "۰ / ۰";
      setButtons();
      return;
    }
    empty.hidden = true;
    content.hidden = false;

    const fallback = speakerById(next.current_speaker_id) || {};
    const speaker = {...fallback, ...(next.current_speaker || {})};
    speakerName.textContent = speaker.name || "بدون نام";
    speakerMeta.textContent = [speaker.gender, speaker.age ? `سن ${speaker.age}` : ""].filter(Boolean).join(" · ");
    speakerCount.textContent = `${Number(next.current_index || 0) + 1} / ${Number(next.total_speakers || 0)}`;
    timer.textContent = fmt(next.remaining_seconds);
    timer.classList.toggle("running", Boolean(next.running));
    overtime.textContent = next.overtime_seconds ? `زمان اضافه: +${fmt(next.overtime_seconds)}` : "";
    const limit = Number(next.limit_seconds || speaker.seconds || 0);
    bar.style.width = `${limit ? Math.max(0, Math.min(100, Number(next.remaining_seconds || 0) / limit * 100)) : 0}%`;

    if (speaker.description) {
      descriptionSection.hidden = false;
      description.textContent = speaker.description;
    } else {
      descriptionSection.hidden = true;
      description.textContent = "";
    }

    speakerFilesSection.hidden = !DATA.live_files;
    if (DATA.live_files) renderFiles(speaker.files || [], speakerFiles);
    renderFiles(DATA.common || [], commonFiles);

    timeAlert.hidden = !next.awaiting_decision;
    timer.setAttribute("aria-live", next.awaiting_decision ? "assertive" : "off");
    if (next.awaiting_decision) {
      timer.textContent = "00:00";
      pauseRecorder("زمان اصلی تمام شد؛ ضبط موقتاً متوقف است.");
    }
    if (next.completed) setStatus("سخنرانی‌ها به پایان رسیده‌اند", true);
    setButtons();
  }

  async function api(action) {
    const fd = new FormData();
    fd.append("csrf", csrf);
    const response = await fetch(`/api/rooms/${DATA.room_id}/${action}`, {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      cache: "no-store",
      headers: {Accept: "application/json"},
    });
    if (response.status === 401) {
      window.location.assign("/login");
      return null;
    }
    let body = null;
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(body?.detail || "عملیات ناموفق بود.");
    return body;
  }

  async function syncOnce() {
    if (polling || destroyed) return null;
    polling = true;
    try {
      const response = await fetch(`/api/rooms/${DATA.room_id}/state`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "application/json"},
      });
      if (response.status === 401) {
        window.location.assign("/login");
        return null;
      }
      if (!response.ok) throw new Error("state failed");
      const next = await response.json();
      updateState(next);
      setStatus("همگام‌سازی فعال است", true);
      return next;
    } catch (_) {
      setStatus("ارتباط با سرور قطع شده؛ تلاش مجدد…", false);
      return null;
    } finally {
      polling = false;
    }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    if (document.hidden || destroyed) return;
    pollTimer = setTimeout(async () => {
      await syncOnce();
      schedulePoll();
    }, 800);
  }

  function chooseMime() {
    const types = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
    ];
    return types.find(type => window.MediaRecorder?.isTypeSupported?.(type)) || "";
  }

  function activeDurationNow() {
    return recordedSeconds + (recordingStartedAt ? Math.max(0, (Date.now() - recordingStartedAt) / 1000) : 0);
  }

  function pauseRecorder(message = "ضبط موقتاً متوقف شد.") {
    if (!recorder) return;
    if (recorder.state === "recording") {
      recordedSeconds = activeDurationNow();
      recordingStartedAt = 0;
      try { recorder.pause(); } catch (_) {}
      setRecordUI("paused", message);
    }
  }

  function resumeRecorder() {
    if (!recorder || recorder.state !== "paused") return;
    try {
      recordingStartedAt = Date.now();
      recorder.resume();
      setRecordUI("recording", "در حال ضبط خودکار…");
    } catch (_) {
      setRecordUI("error", "ادامهٔ ضبط در این مرورگر ممکن نیست.");
    }
  }

  async function ensureRecorder(speakerId) {
    if (!DATA.recording) return;
    if (!speakerId) throw new Error("سخنران فعلی مشخص نیست.");
    if (recorder && recordingSpeakerId === speakerId) return;
    if (recorder) throw new Error("ضبط سخنران قبلی هنوز بسته نشده است.");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      throw new Error("ضبط صدا در این مرورگر در دسترس نیست.");
    }
    stream = await navigator.mediaDevices.getUserMedia({audio: true});
    const mime = chooseMime();
    const options = {audioBitsPerSecond: 24000};
    if (mime) options.mimeType = mime;
    try {
      recorder = new MediaRecorder(stream, options);
    } catch (_) {
      stream.getTracks().forEach(track => track.stop());
      stream = null;
      recorder = null;
      throw new Error("مرورگر این نوع ضبط صدا را پشتیبانی نمی‌کند.");
    }
    recordingSpeakerId = Number(speakerId);
    chunks = [];
    recordedSeconds = 0;
    recordingStartedAt = 0;
    recorder.ondataavailable = event => {
      if (event.data?.size) chunks.push(event.data);
    };
    recorder.onerror = () => setRecordUI("error", "ضبط صدا با خطا متوقف شد.");
  }

  function stopRecorderAndMakeBlob() {
    return new Promise((resolve, reject) => {
      if (!recorder) {
        resolve(pendingRecording || null);
        return;
      }
      const r = recorder;
      recordedSeconds = activeDurationNow();
      recordingStartedAt = 0;
      const speakerId = recordingSpeakerId;
      const finish = () => {
        try {
          const mime = r.mimeType || "audio/webm";
          const blob = new Blob(chunks, {type: mime});
          stream?.getTracks().forEach(track => track.stop());
          stream = null;
          chunks = [];
          recorder = null;
          recordingSpeakerId = null;
          const info = {blob, duration: Math.round(Math.max(0, recordedSeconds)), speakerId};
          return info;
        } catch (error) {
          reject(error);
          return null;
        }
      };
      const done = () => {
        const info = finish();
        if (info) resolve(info);
      };
      r.addEventListener("stop", done, {once: true});
      try {
        if (r.state !== "inactive") r.stop();
        else done();
      } catch (error) {
        reject(error);
      }
    });
  }

  async function startRecorder(speakerId) {
    if (!DATA.recording) return;
    await ensureRecorder(speakerId);
    if (!recorder) return;
    if (recorder.state === "inactive") {
      recordingStartedAt = Date.now();
      recorder.start(1000);
      setRecordUI("recording", "در حال ضبط خودکار…");
    } else if (recorder.state === "paused") {
      resumeRecorder();
    }
  }

  function recordingName(info) {
    const ext = (info.blob.type || "").includes("ogg") ? "ogg" : ((info.blob.type || "").includes("mp4") ? "mp4" : "webm");
    return `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.${ext}`;
  }

  async function uploadBlob(info) {
    if (!info?.blob || info.blob.size === 0) return true;
    setRecordUI("paused", "در حال ذخیره ضبط…");
    const fd = new FormData();
    fd.append("csrf", csrf);
    fd.append("speaker_id", String(info.speakerId || ""));
    fd.append("duration_seconds", String(Math.min(Math.round(info.duration || 0), Number(DATA.max_recording_seconds || 10800))));
    fd.append("file", info.blob, recordingName(info));
    const response = await fetch(`/api/rooms/${DATA.room_id}/recording`, {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      cache: "no-store",
      headers: {Accept: "application/json"},
    });
    if (response.status === 401) {
      window.location.assign("/login");
      return false;
    }
    let body = null;
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(body?.detail || "ذخیره ضبط ناموفق بود.");
    setRecordUI("idle", "ضبط ذخیره شد.");
    return true;
  }

  async function uploadOrKeepPending(info) {
    if (!info) return;
    try {
      await uploadBlob(info);
      if (pendingRecording === info) pendingRecording = null;
    } catch (error) {
      pendingRecording = info;
      setRecordUI("error", `${error.message} فایل ضبط فعلاً نگه داشته شد.`);
      throw error;
    }
  }

  function discardLocalRecorder() {
    if (recorder) {
      try { if (recorder.state !== "inactive") recorder.stop(); } catch (_) {}
    }
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    recorder = null;
    chunks = [];
    recordingSpeakerId = null;
    recordedSeconds = 0;
    recordingStartedAt = 0;
  }

  async function control(action) {
    [btnStart, btnPause, btnReset, btnPrev, btnNext, btnFinish, btnContinue, btnFinishAlert, btnDelete].forEach(button => { if (button) button.disabled = true; });
    try {
      const speakerId = state?.current_speaker_id;
      if (action === "start") {
        if (DATA.recording) await ensureRecorder(speakerId);
        const next = await api("start");
        if (next) {
          updateState(next);
          if (next.running && DATA.recording) await startRecorder(speakerId);
        }
      } else if (action === "continue") {
        const next = await api("continue");
        if (next) {
          updateState(next);
          if (next.running && DATA.recording) await startRecorder(next.current_speaker_id);
        }
      } else if (action === "pause") {
        const next = await api("pause");
        if (next) {
          updateState(next);
          pauseRecorder();
        }
      } else if (action === "finish") {
        let info = null;
        if (DATA.recording) {
          info = await stopRecorderAndMakeBlob();
          if (info?.blob?.size) {
            pendingRecording = info;
            await uploadOrKeepPending(info);
          }
        }
        const next = await api("finish");
        if (next) {
          pendingRecording = null;
          discardLocalRecorder();
          updateState(next);
          setRecordUI("idle", next.completed ? "سخنرانی‌ها تمام شدند." : "آمادهٔ ضبط خودکار سخنران بعدی.");
        }
      } else {
        const next = await api(action);
        if (next) {
          if ((action === "next" || action === "prev" || action === "reset") && recorder) discardLocalRecorder();
          if (action === "next" || action === "prev" || action === "reset") pendingRecording = null;
          updateState(next);
          if (DATA.recording) setRecordUI("idle", "آمادهٔ ضبط خودکار.");
        }
      }
    } catch (error) {
      alert(error.message || "عملیات ناموفق بود.");
      await syncOnce();
    } finally {
      setButtons();
    }
  }

  function chooseDeleteResult() {
    if (!deleteDialog) return Promise.resolve("cancel");
    return new Promise(resolve => {
      const done = () => {
        deleteDialog.removeEventListener("close", done);
        resolve(deleteDialog.returnValue || "cancel");
      };
      deleteDialog.addEventListener("close", done, {once: true});
      deleteDialog.showModal();
    });
  }

  async function deleteCurrentSpeaker() {
    const speakerId = state?.current_speaker_id;
    if (!speakerId) return;
    const choice = await chooseDeleteResult();
    if (choice === "cancel") return;
    const currentIsRecording = Boolean(recorder && recordingSpeakerId === speakerId && recorder.state !== "inactive");
    let info = pendingRecording?.speakerId === speakerId ? pendingRecording : null;
    try {
      if (currentIsRecording) info = await stopRecorderAndMakeBlob();
      if (info) pendingRecording = info;

      const form = new FormData();
      form.append("csrf", csrf);
      form.append("save_recording", choice === "save" ? "1" : "0");
      if (choice === "save" && info?.blob?.size) {
        form.append("duration_seconds", String(Math.round(info.duration || 0)));
        form.append("recording", info.blob, recordingName(info));
      }
      const response = await fetch(`/api/rooms/${DATA.room_id}/speakers/${speakerId}/delete`, {
        method: "POST",
        body: form,
        credentials: "same-origin",
        cache: "no-store",
        headers: {Accept: "application/json"},
      });
      if (response.status === 401) { window.location.assign("/login"); return; }
      let body = null;
      try { body = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(body?.detail || "حذف سخنران ناموفق بود.");
      pendingRecording = null;
      discardLocalRecorder();
      await syncOnce();
      setRecordUI("idle", "سخنران حذف شد.");
    } catch (error) {
      alert(error.message || "حذف سخنران ناموفق بود.");
      await syncOnce();
    } finally {
      setButtons();
    }
  }

  btnStart?.addEventListener("click", () => control("start"));
  btnPause?.addEventListener("click", () => control("pause"));
  btnReset?.addEventListener("click", () => control("reset"));
  btnNext?.addEventListener("click", () => control("next"));
  btnPrev?.addEventListener("click", () => control("prev"));
  btnFinish?.addEventListener("click", () => control("finish"));
  btnContinue?.addEventListener("click", () => control("continue"));
  btnFinishAlert?.addEventListener("click", () => control("finish"));
  btnDelete?.addEventListener("click", deleteCurrentSpeaker);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = null;
    } else {
      syncOnce().finally(schedulePoll);
    }
  });

  window.addEventListener("beforeunload", event => {
    if (recorder?.state && recorder.state !== "inactive" || pendingRecording) {
      event.preventDefault();
      event.returnValue = "ضبط صدا هنوز ذخیره نشده است.";
    }
  });

  renderFiles(DATA.common || [], commonFiles);
  syncOnce().finally(schedulePoll);
})();
