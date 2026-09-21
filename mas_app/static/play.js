(() => {
  "use strict";
  const DATA = JSON.parse(document.getElementById("play-data")?.textContent || "{}");
  const root = document.getElementById("play-root");
  if (!root) return;
  const empty = document.getElementById("empty-play");
  const content = document.getElementById("play-content");
  const status = document.getElementById("connection-status");
  const speakerName = document.getElementById("speaker-name");
  const speakerMeta = document.getElementById("speaker-meta");
  const speakerCount = document.getElementById("speaker-count");
  const speakerStatus = document.getElementById("speaker-status");
  const speakerTotal = document.getElementById("speaker-total");
  const timer = document.getElementById("timer");
  const overtime = document.getElementById("overtime");
  const bar = document.getElementById("progress-bar");
  const descriptionSection = document.getElementById("description-section");
  const description = document.getElementById("speaker-description");
  const speakerFilesSection = document.getElementById("speaker-files-section");
  const speakerFiles = document.getElementById("speaker-files");
  const commonFiles = document.getElementById("common-files");
  const recordingsList = document.getElementById("recordings-list");
  const btnStart = document.getElementById("btn-start");
  const btnPause = document.getElementById("btn-pause");
  const btnReset = document.getElementById("btn-reset");
  const btnNext = document.getElementById("btn-next");
  const btnPrev = document.getElementById("btn-prev");
  const btnFinish = document.getElementById("btn-finish");
  const btnDeleteSpeaker = document.getElementById("btn-delete-speaker");
  const recordBtn = document.getElementById("record-btn");
  const recordStatus = document.getElementById("record-status");
  const recordDownload = document.getElementById("record-download");
  const recordingBox = recordBtn?.closest(".recording-box");
  const overtimeModal = document.getElementById("overtime-modal");
  const overtimeContinue = document.getElementById("overtime-continue");
  const overtimeFinish = document.getElementById("overtime-finish");
  const csrf = DATA.csrf || "";

  let currentState = DATA.initial_state || null;
  let pollTimer = null;
  let syncBusy = false;
  let raf = null;
  let anchorPerf = performance.now();
  let recorder = null;
  let recorderStream = null;
  let chunks = [];
  let recordStartedAt = 0;
  let recordingLimitTimer = null;
  let sessionExpired = false;
  let promptedSpeakerId = null;
  let notificationPermissionRequested = false;

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const fmtMs = ms => {
    ms = Math.max(0, Math.floor(Number(ms) || 0));
    const sec = Math.floor(ms / 1000);
    const mins = String(Math.floor(sec / 60)).padStart(2, "0");
    const secs = String(sec % 60).padStart(2, "0");
    return `${mins}:${secs}`;
  };
  const setStatus = (text, ok = true) => {
    status.textContent = text;
    status.className = ok ? "muted status-online" : "muted status-offline";
  };
  const speakerById = id => (currentState?.speakers || DATA.speakers || []).find(s => Number(s.id) === Number(id)) || DATA.speakers.find(s => Number(s.id) === Number(id)) || null;

  function renderFiles(list, target) {
    target.innerHTML = "";
    if (!list?.length) { target.innerHTML = '<span class="muted">فایلی وجود ندارد.</span>'; return; }
    for (const file of list) {
      const item = document.createElement("div");
      item.className = "file-row";
      item.innerHTML = `<a target="_blank" rel="noopener" href="/files/${Number(file.id)}">📄 ${esc(file.name)}</a><a target="_blank" rel="noopener" href="/files/${Number(file.id)}/download">دانلود</a>`;
      target.appendChild(item);
    }
  }

  function renderRecordings() {
    renderFiles(DATA.recordings || [], recordingsList);
  }

  function renderSpeakerList() {
    const list = document.getElementById("speaker-list");
    if (!list) return;
    list.innerHTML = "";
    const items = currentState?.speakers || DATA.speakers || [];
    speakerTotal.textContent = String(items.length);
    items.forEach((s, idx) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `play-speaker${Number(s.id) === Number(currentState?.current_speaker_id) ? " current" : ""}${s.is_finished ? " finished" : ""}`;
      button.dataset.speakerId = s.id;
      button.innerHTML = `<span class="number">${idx + 1}</span><span>${esc(s.name || "بدون نام")}</span><span class="mini-status">${s.is_finished ? "فریز" : "فعال"}</span>`;
      button.addEventListener("click", async () => {
        if (Number(s.id) === Number(currentState?.current_speaker_id)) return;
        [btnStart, btnPause, btnReset, btnPrev, btnNext, btnFinish, btnDeleteSpeaker].forEach(b => { if (b) b.disabled = true; });
        try {
          const fd = new FormData(); fd.append("csrf", csrf);
          const response = await fetch(`/api/rooms/${DATA.room_id}/goto/${Number(s.id)}`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
          if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "انتقال به سخنران ناموفق بود."); }
          closeOvertimePrompt();
          updateState(await response.json());
        } catch (error) { alert(error.message || "انتقال ناموفق بود."); await syncOnce(); }
      });
      list.appendChild(button);
    });
  }

  function updateAnchor(state) {
    // `elapsed_ms` in the API response is already evaluated at `server_time_ms`.
    // Interpolate from that authoritative snapshot with the browser monotonic clock.
    anchorPerf = performance.now();
  }

  function currentElapsedMs() {
    if (!currentState) return 0;
    const base = Number(currentState.elapsed_ms || 0);
    if (!currentState.running) return Math.max(0, base);
    return Math.max(0, base + Math.max(0, performance.now() - anchorPerf));
  }

  function renderTimer() {
    if (!currentState || !currentState.current_speaker_id) {
      if (timer) timer.textContent = "00:00";
      raf = requestAnimationFrame(renderTimer);
      return;
    }
    const elapsed = currentElapsedMs();
    const limit = Number(currentState.limit_ms || 0);
    const isFinished = Boolean(currentState.current_speaker?.is_finished);
    const overtimeMs = Math.max(0, elapsed - limit);
    const remainingMs = Math.max(0, limit - elapsed);
    if (isFinished) {
      timer.textContent = "پایان سخنرانی";
      timer.classList.add("finished");
      overtime.textContent = overtimeMs > 0 ? `زمان اضافه ثبت‌شده: +${fmtMs(overtimeMs)}` : "";
      bar.style.width = "100%";
    } else {
      timer.classList.remove("finished");
      timer.textContent = fmtMs(overtimeMs > 0 ? 0 : remainingMs);
      overtime.textContent = overtimeMs > 0 ? `زمان اضافه: +${fmtMs(overtimeMs)}` : "";
      const pct = limit > 0 ? Math.min(100, (remainingMs / limit) * 100) : 0;
      bar.style.width = `${pct}%`;
      if (currentState.running && elapsed >= limit && promptedSpeakerId !== Number(currentState.current_speaker_id)) {
        promptedSpeakerId = Number(currentState.current_speaker_id);
        openOvertimePrompt();
      }
    }
    raf = requestAnimationFrame(renderTimer);
  }

  function updateState(state) {
    if (!state) return;
    const previousId = Number(currentState?.current_speaker_id || 0);
    currentState = state;
    updateAnchor(state);
    if (previousId !== Number(state.current_speaker_id || 0)) promptedSpeakerId = null;
    if (!state.current_speaker_id) {
      empty.hidden = false;
      content.hidden = true;
      speakerCount.textContent = "۰ / ۰";
      renderSpeakerList();
      return;
    }
    empty.hidden = true;
    content.hidden = false;
    const speaker = state.current_speaker || speakerById(state.current_speaker_id);
    if (!speaker) return;
    speakerName.textContent = speaker.name || "بدون نام";
    const meta = [speaker.gender, speaker.age ? `سن ${speaker.age}` : ""].filter(Boolean).join(" · ");
    speakerMeta.textContent = meta || "";
    speakerCount.textContent = `${state.current_index + 1} / ${state.total_speakers}`;
    speakerStatus.textContent = speaker.is_finished ? "فریز شده" : (state.running ? "در حال سخنرانی" : "آماده");
    speakerStatus.className = speaker.is_finished ? "badge danger-badge" : "badge";
    if (speaker.description) { descriptionSection.hidden = false; description.textContent = speaker.description; }
    else { descriptionSection.hidden = true; description.textContent = ""; }
    speakerFilesSection.hidden = !DATA.live_files;
    if (DATA.live_files) renderFiles(speaker.files || [], speakerFiles);
    renderFiles(DATA.common || [], commonFiles);
    renderRecordings();
    btnStart.disabled = Boolean(state.running) || Boolean(speaker.is_finished);
    btnPause.disabled = !state.running;
    btnReset.disabled = Boolean(speaker.is_finished) || !Number(state.elapsed_ms) && !Number(state.overtime_ms);
    btnPrev.disabled = state.current_index <= 0;
    btnNext.disabled = !(state.speakers || []).slice(state.current_index + 1).some(s => !s.is_finished);
    btnFinish.disabled = Boolean(speaker.is_finished);
    btnDeleteSpeaker.disabled = false;
    renderSpeakerList();
  }

  async function api(action) {
    const fd = new FormData(); fd.append("csrf", csrf);
    const response = await fetch(`/api/rooms/${DATA.room_id}/${action}`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
    if (response.status === 401) { sessionExpired = true; setStatus("نشست شما منقضی شده است؛ دوباره وارد شوید.", false); stopPolling(); return null; }
    if (!response.ok) {
      let msg = "عملیات ناموفق بود.";
      try { const body = await response.json(); if (body.detail) msg = body.detail; } catch (_) {}
      throw new Error(msg);
    }
    return response.json();
  }

  async function control(action) {
    [btnStart, btnPause, btnReset, btnPrev, btnNext, btnFinish, btnDeleteSpeaker].forEach(b => { if (b) b.disabled = true; });
    try { const state = await api(action); if (state) updateState(state); }
    catch (error) { alert(error.message || "عملیات ناموفق بود."); await syncOnce(); }
  }

  async function deleteCurrentSpeaker() {
    const id = Number(currentState?.current_speaker_id || 0);
    const speaker = speakerById(id);
    if (!id || !speaker) return;
    if (!confirm(`سخنران «${speaker.name || "بدون نام"}» حذف شود؟ در صورت حذف سخنران فعلی، سایت خودکار به سخنران بعدی فعال می‌رود.`)) return;
    const fd = new FormData(); fd.append("csrf", csrf);
    btnDeleteSpeaker.disabled = true;
    try {
      const response = await fetch(`/api/rooms/${DATA.room_id}/speakers/${id}/delete`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "حذف سخنران ناموفق بود."); }
      updateState(await response.json());
    } catch (e) { alert(e.message); btnDeleteSpeaker.disabled = false; }
  }

  async function syncOnce() {
    if (syncBusy || sessionExpired) return;
    syncBusy = true;
    try {
      const response = await fetch(`/api/rooms/${DATA.room_id}/state`, {credentials:"same-origin", headers:{"Accept":"application/json"}});
      if (response.status === 401) { sessionExpired = true; setStatus("نشست شما منقضی شده است؛ دوباره وارد شوید.", false); stopPolling(); return; }
      if (!response.ok) throw new Error("state failed");
      updateState(await response.json()); setStatus("همگام‌سازی فعال است", true);
    } catch (_) { setStatus("ارتباط با سرور قطع شده؛ تلاش مجدد…", false); }
    finally { syncBusy = false; }
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    if (document.hidden || sessionExpired) return;
    const interval = currentState?.running ? 1500 : 5000;
    pollTimer = setTimeout(async () => { await syncOnce(); schedulePoll(); }, interval);
  }
  function stopPolling() { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; }

  async function requestNotificationPermission() {
    if (notificationPermissionRequested) return;
    notificationPermissionRequested = true;
    if ("Notification" in window && Notification.permission === "default") {
      try { await Notification.requestPermission(); } catch (_) {}
    }
  }

  function openOvertimePrompt() {
    overtimeModal.hidden = false;
    const id = Number(currentState?.current_speaker_id || 0);
    const speaker = speakerById(id);
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification("زمان سخنران تمام شد", {body: `زمان مجاز «${speaker?.name || "سخنران"}» به پایان رسید.`}); } catch (_) {}
    }
  }
  function closeOvertimePrompt() { overtimeModal.hidden = true; }

  function chooseMimeType() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    return candidates.find(type => window.MediaRecorder?.isTypeSupported?.(type)) || "";
  }
  function extForMime(mime) {
    mime = String(mime || "").toLowerCase();
    if (mime.includes("ogg")) return "ogg";
    if (mime.includes("mp4")) return "m4a";
    if (mime.includes("mpeg")) return "mp3";
    return "webm";
  }
  function blobTooLarge(blob) {
    return Number(blob?.size || 0) > Number(DATA.max_upload_bytes || 0);
  }

  async function toggleRecording() {
    if (!recordBtn) return;
    if (recorder?.state === "recording") { recordBtn.disabled = true; recorder.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { recordStatus.textContent = "ضبط صوت در این مرورگر در دسترس نیست."; return; }
    await requestNotificationPermission();
    try {
      recorderStream = await navigator.mediaDevices.getUserMedia({audio:true});
      const mime = chooseMimeType();
      const options = {audioBitsPerSecond:Number(DATA.recording_bitrate_bps || 32000)};
      if (mime) options.mimeType = mime;
      recorder = new MediaRecorder(recorderStream, options);
      chunks = []; recordStartedAt = Date.now();
      clearTimeout(recordingLimitTimer);
      recordingLimitTimer = setTimeout(() => { if (recorder?.state === "recording") { recordStatus.textContent = "به سقف مدت ضبط رسید؛ در حال ذخیره…"; recorder.stop(); } }, Number(DATA.max_recording_seconds || 0) * 1000);
      recorder.ondataavailable = event => { if (event.data?.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        clearTimeout(recordingLimitTimer);
        const duration = Math.min(Number(DATA.max_recording_seconds || 0), Math.round((Date.now() - recordStartedAt) / 1000));
        const actualType = recorder?.mimeType || mime || "audio/webm";
        const blob = new Blob(chunks, {type:actualType});
        recorderStream?.getTracks().forEach(track => track.stop()); recorderStream = null; recorder = null; chunks = [];
        if (blobTooLarge(blob)) {
          const url = URL.createObjectURL(blob);
          recordDownload.hidden = false; recordDownload.href = url; recordDownload.download = `recording-${Date.now()}.${extForMime(actualType)}`;
          recordStatus.textContent = "فایل از سقف سرور بزرگ‌تر است. فایل برای ذخیره محلی آماده شد و به سرور ارسال نشد.";
          recordBtn.disabled = false; recordBtn.textContent = "● شروع ضبط"; return;
        }
        try {
          const fd = new FormData(); fd.append("csrf", csrf); fd.append("duration_seconds", String(Math.max(1, duration)));
          fd.append("file", blob, `recording-${new Date().toISOString().replace(/[:.]/g,"-")}.${extForMime(actualType)}`);
          recordStatus.textContent = "در حال ذخیره ضبط…";
          const response = await fetch(`/api/rooms/${DATA.room_id}/recording`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
          const saved = await response.json().catch(() => ({}));
          if (!response.ok) { throw new Error(saved.detail || "ذخیره ضبط ناموفق بود."); }
          if (saved.file) { DATA.recordings = [saved.file, ...(DATA.recordings || [])]; }
          recordDownload.hidden = true; recordStatus.textContent = "ضبط ذخیره شد."; renderRecordings();
        } catch (error) {
          const url = URL.createObjectURL(blob); recordDownload.hidden = false; recordDownload.href = url; recordDownload.download = `recording-${Date.now()}.${extForMime(actualType)}`;
          recordStatus.textContent = `${error.message || "ذخیره ضبط ناموفق بود."} فایل برای ذخیره محلی آماده شد.`;
        } finally { recordBtn.disabled = false; recordBtn.textContent = "● شروع ضبط"; recordingBox?.classList.remove("recording"); }
      };
      recorder.onerror = () => { clearTimeout(recordingLimitTimer); recorderStream?.getTracks().forEach(track => track.stop()); recorderStream = null; recorder = null; recordStatus.textContent = "ضبط با خطا متوقف شد."; recordBtn.disabled = false; recordBtn.textContent = "● شروع ضبط"; };
      recorder.start(1000); recordBtn.textContent = "■ توقف ضبط"; recordStatus.textContent = "در حال ضبط…"; recordingBox?.classList.add("recording");
      recordDownload.hidden = true;
    } catch (_) {
      clearTimeout(recordingLimitTimer); recorderStream?.getTracks().forEach(track => track.stop()); recorderStream = null;
      recordStatus.textContent = "اجازهٔ دسترسی به میکروفون داده نشد یا میکروفون در دسترس نیست."; recordBtn.disabled = false; recordBtn.textContent = "● شروع ضبط";
    }
  }

  btnStart?.addEventListener("click", () => { requestNotificationPermission(); control("start"); });
  btnPause?.addEventListener("click", () => control("pause"));
  btnReset?.addEventListener("click", () => control("reset"));
  btnNext?.addEventListener("click", () => control("next"));
  btnPrev?.addEventListener("click", () => control("prev"));
  btnFinish?.addEventListener("click", () => control("finish"));
  btnDeleteSpeaker?.addEventListener("click", deleteCurrentSpeaker);
  overtimeContinue?.addEventListener("click", async () => { closeOvertimePrompt(); await control("continue_overtime"); });
  overtimeFinish?.addEventListener("click", async () => { closeOvertimePrompt(); await control("finish"); });
  recordBtn?.addEventListener("click", toggleRecording);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopPolling(); else { syncOnce(); schedulePoll(); } });
  window.addEventListener("beforeunload", event => { if (recorder?.state === "recording") { event.preventDefault(); event.returnValue = "ضبط صدا هنوز فعال است."; } });

  updateState(currentState || {speakers:DATA.speakers || [], current_speaker_id:null, total_speakers:0});
  renderRecordings();
  raf = requestAnimationFrame(renderTimer);
  syncOnce().finally(schedulePoll);
})();
