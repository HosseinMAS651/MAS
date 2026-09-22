import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api/client';
import { TimerState, Speaker, SpeechFile } from '../types';
import { formatMs, formatBytes } from '../utils/formatters';
import { AudioRecorder } from '../utils/audioRecorder';
import { OvertimeModal } from '../components/OvertimeModal';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { QrModal } from '../components/QrModal';

export const PlayPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();

  const [state, setState] = useState<TimerState | null>(null);
  const [roomName, setRoomName] = useState<string>('');
  const [publicToken, setPublicToken] = useState<string | null>(null);
  const [recordingEnabled, setRecordingEnabled] = useState<boolean>(false);
  const [liveFilesEnabled, setLiveFilesEnabled] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');

  // نمایش محلی روان تایمر بدون انتظار برای پاسخ شبکه
  const [displayElapsedMs, setDisplayElapsedMs] = useState<number>(0);
  const [displayOvertimeMs, setDisplayOvertimeMs] = useState<number>(0);

  // وضعیت ضبط صدا
  const [recState, setRecState] = useState<'inactive' | 'recording' | 'paused' | 'saving'>('inactive');
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const recorderRef = useRef<AudioRecorder | null>(null);

  // دیالوگ‌های کنترلی
  const [showOvertimeModal, setShowOvertimeModal] = useState<boolean>(false);
  const [showQrModal, setShowQrModal] = useState<boolean>(false);

  // پرسش ذخیره در زمان حذف سخنران در حین ضبط فعال (درخواست کاربر)
  const [deletingSpeakerPrompt, setDeletingSpeakerPrompt] = useState<{
    speakerId: number;
    speakerName: string;
  } | null>(null);

  const etagRef = useRef<string>('');
  const animFrameRef = useRef<number | null>(null);

  // دریافت مشخصات کلی اتاق (فقط یک‌بار در ابتدا)
  useEffect(() => {
    const fetchRoomMeta = async () => {
      try {
        const data = await api.get(`/api/rooms/${id}`);
        setRoomName(data.room.name);
        setPublicToken(data.room.public_token);
        setRecordingEnabled(data.room.recording_enabled);
        setLiveFilesEnabled(data.room.live_files_enabled);
      } catch (err: any) {
        setError(err.message || 'خطا در بارگذاری مشخصات اتاق.');
      }
    };
    fetchRoomMeta();
  }, [id]);

  // شروع یا همگام‌سازی ضبط صدای مرورگر همگام با شروع تایمر
  const handleStartRecording = useCallback(async (currentSp: Speaker | null) => {
    if (!recordingEnabled || !currentSp) return;

    // اگر ضبط از قبل در مرورگر در حال اجراست و فقط متوقف شده بود:
    if (recorderRef.current && recorderRef.current.getState() === 'paused') {
      recorderRef.current.resume();
      setRecState('recording');
      return;
    }

    try {
      // دریافت یا ایجاد نشست ضبط در سرور
      const statusRes = await api.get(`/api/rooms/${id}/recording/status`);
      let sId = statusRes?.session?.session_id;

      if (!sId) {
        // ایجاد مجدد یا بازیابی وضعیت از طریق تایمر
        sId = 0;
      }
      setActiveSessionId(sId);

      const rec = new AudioRecorder();
      recorderRef.current = rec;

      await rec.start({
        timesliceMs: 4000,
        onChunk: async (chunkBlob: Blob, seq: number) => {
          // اگر هنوز شناسه نشست در دست نیست، مجدد وضعیت را می‌خوانیم
          let targetSessionId = activeSessionId;
          if (!targetSessionId) {
            const st = await api.get(`/api/rooms/${id}/recording/status`);
            targetSessionId = st?.session?.session_id;
            setActiveSessionId(targetSessionId);
          }
          if (targetSessionId) {
            const fd = new FormData();
            fd.append('session_id', String(targetSessionId));
            fd.append('seq', String(seq));
            fd.append('chunk', chunkBlob, `chunk_${seq}.bin`);
            await api.upload(`/api/rooms/${id}/recording/chunk`, fd);
          }
        },
        onError: (err) => {
          console.error('خطای ضبط:', err);
        },
      });

      setRecState('recording');
    } catch (err) {
      console.warn('امکان دسترسی به میکروفون وجود ندارد یا مجوز رد شد:', err);
    }
  }, [id, recordingEnabled, activeSessionId]);

  const handlePauseRecording = useCallback(() => {
    if (recorderRef.current && recorderRef.current.getState() === 'recording') {
      recorderRef.current.pause();
      setRecState('paused');
    }
  }, []);

  const handleStopRecording = useCallback(async (save: boolean = true) => {
    if (recorderRef.current) {
      recorderRef.current.stop();
      recorderRef.current = null;
    }
    setRecState('saving');
    try {
      await api.post(`/api/rooms/${id}/recording/finish`, { save });
    } catch (err) {
      console.warn('خطا در ذخیره ضبط:', err);
    } finally {
      setRecState('inactive');
      setActiveSessionId(null);
    }
  }, [id]);

  // درخواست دریافت وضعیت تایمر با بهینه‌سازی ETag
  const pollTimerState = useCallback(async () => {
    try {
      const headers: Record<string, string> = {};
      if (etagRef.current) {
        headers['If-None-Match'] = etagRef.current;
      }
      const res = await api.get(`/api/rooms/${id}/timer/state`, headers);
      if (res && res.state) {
        setState(res.state);

        // شرط کاربر: اگر زمان به اتمام رسید و در انتظار تصمیم بود، اعلان نمایش داده شود
        if (res.state.awaiting_decision && !res.state.running) {
          setShowOvertimeModal(true);
          handlePauseRecording();
        }

        // همگام‌سازی وضعیت ضبط صوت
        if (res.state.running && recState === 'inactive' && recordingEnabled) {
          handleStartRecording(res.state.current_speaker);
        } else if (!res.state.running && recState === 'recording') {
          handlePauseRecording();
        }
      }
    } catch (err: any) {
      console.warn('خطا در دریافت وضعیت تایمر:', err);
    } finally {
      setLoading(false);
    }
  }, [id, recState, recordingEnabled, handleStartRecording, handlePauseRecording]);

  // حلقهٔ دوره‌ای Polling (هر ۱ ثانیه)
  useEffect(() => {
    pollTimerState();
    const interval = setInterval(pollTimerState, 1000);
    return () => clearInterval(interval);
  }, [pollTimerState]);

  // رندر بلادرنگ روان تایمر روی فریم‌های مرورگر (بدون رندرهای سنگین)
  useEffect(() => {
    const tick = () => {
      if (state) {
        if (state.running) {
          if (!state.awaiting_decision) {
            setDisplayElapsedMs(state.elapsed_ms);
            setDisplayOvertimeMs(0);
          } else {
            setDisplayElapsedMs(state.limit_ms);
            setDisplayOvertimeMs(state.overtime_ms);
          }
        } else {
          setDisplayElapsedMs(state.elapsed_ms);
          setDisplayOvertimeMs(state.overtime_ms);
        }
      }
      animFrameRef.current = requestAnimationFrame(tick);
    };
    animFrameRef.current = requestAnimationFrame(tick);
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [state]);

  // اکشن‌های کنترل تایمر
  const handleAction = async (action: string, speakerId?: number) => {
    try {
      const res = await api.post(`/api/rooms/${id}/timer/action`, {
        action,
        speaker_id: speakerId,
      });
      if (res?.state) {
        setState(res.state);

        if (action === 'start' || action === 'resume' || action === 'continue_overtime') {
          setShowOvertimeModal(false);
          await handleStartRecording(res.state.current_speaker);
        } else if (action === 'pause') {
          handlePauseRecording();
        } else if (action === 'finish' || action === 'finish_overtime') {
          setShowOvertimeModal(false);
          await handleStopRecording(true);
        } else if (action === 'reset') {
          await handleStopRecording(false);
        }
      }
    } catch (err: any) {
      alert(err.message || 'خطا در اعمال دستور تایمر.');
    }
  };

  // حذف سخنران در صفحه پخش با بررسی ضبط فعال (درخواست کاربر)
  const attemptDeleteSpeaker = async (sp: Speaker) => {
    // اگر سخنران دارای ضبط فعال باشد، از کاربر سؤال می‌شود
    if (recState === 'recording' || recState === 'paused') {
      if (state?.current_speaker_id === sp.id) {
        setDeletingSpeakerPrompt({ speakerId: sp.id, speakerName: sp.name || 'سخنران' });
        return;
      }
    }

    try {
      await api.delete(`/api/rooms/${id}/speakers/${sp.id}`);
      await pollTimerState();
    } catch (err: any) {
      if (err.code === 'RECORDING_ACTIVE_PROMPT_REQUIRED') {
        setDeletingSpeakerPrompt({ speakerId: sp.id, speakerName: sp.name || 'سخنران' });
      } else {
        alert(err.message || 'خطا در حذف سخنران.');
      }
    }
  };

  const confirmDeleteSpeakerWithRecording = async (saveRecording: boolean) => {
    if (!deletingSpeakerPrompt) return;
    try {
      await api.delete(`/api/rooms/${id}/speakers/${deletingSpeakerPrompt.speakerId}?save_recording=${saveRecording}`);
      setDeletingSpeakerPrompt(null);
      if (recorderRef.current) {
        recorderRef.current.stop();
        recorderRef.current = null;
      }
      setRecState('inactive');
      await pollTimerState();
    } catch (err: any) {
      alert(err.message || 'خطا در حذف سخنران.');
    }
  };

  if (loading && !state) {
    return <div className="text-center py-24 text-gray-400 font-bold">در حال آماده‌سازی اتاق پخش…</div>;
  }
  if (error || !state) {
    return <div className="p-8 text-center text-red-600 font-bold">{error || 'اطلاعات اتاق یافت نشد.'}</div>;
  }

  const currentSp = state.current_speaker;
  const limitMs = state.limit_ms || 300000;
  const remainingMs = Math.max(0, limitMs - displayElapsedMs);
  const progressPercent = Math.min(100, (displayElapsedMs / limitMs) * 100);

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-900 text-white flex flex-col justify-between">
      {/* نوار بالایی هدر اتاق پخش */}
      <div className="px-6 py-4 bg-slate-950/60 backdrop-blur-md border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to={`/rooms/${id}`} className="text-xs font-bold text-slate-400 hover:text-white transition-colors">
            ✕ خروج از پخش
          </Link>
          <div className="h-4 w-px bg-slate-800"></div>
          <h1 className="text-base font-black text-slate-100">{roomName}</h1>
        </div>

        <div className="flex items-center gap-3">
          {/* نشانگر وضعیت ضبط (۳ حالت خواسته شده: در حال ضبط / متوقف / ذخیره) */}
          {recordingEnabled && (
            <div className="flex items-center gap-2 px-3 py-1 bg-slate-900 border border-slate-800 rounded-xl text-xs">
              {recState === 'recording' ? (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse"></span>
                  <span className="text-red-400 font-bold">در حال ضبط صدا…</span>
                </>
              ) : recState === 'paused' ? (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500"></span>
                  <span className="text-amber-400 font-bold">ضبط متوقف (Pause)</span>
                </>
              ) : recState === 'saving' ? (
                <>
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-spin"></span>
                  <span className="text-blue-400 font-bold">در حال ذخیره ضبط…</span>
                </>
              ) : (
                <span className="text-slate-500 font-medium">ضبط خودکار آماده</span>
              )}
            </div>
          )}

          {publicToken && (
            <button
              onClick={() => setShowQrModal(true)}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold rounded-xl transition-all flex items-center gap-1.5"
            >
              <span>📱</span> نمایش QR تماشاگران
            </button>
          )}
        </div>
      </div>

      {/* بخش اصلی استیج سخنران و تایمر */}
      <div className="max-w-4xl mx-auto w-full px-4 py-8 flex flex-col items-center justify-center text-center space-y-6">
        {/* نوبت و نام سخنران */}
        <div className="space-y-2">
          <span className="px-4 py-1.5 bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-bold rounded-full inline-block">
            سخنران {state.current_index + 1} از {state.total_speakers}
          </span>
          <h2 className="text-4xl sm:text-5xl font-black text-white tracking-tight">
            {currentSp ? currentSp.name || 'سخنران بدون نام' : 'سخنرانی برای اجرا وجود ندارد'}
          </h2>
          {currentSp?.description && (
            <p className="text-sm text-slate-400 max-w-lg mx-auto">{currentSp.description}</p>
          )}
        </div>

        {/* نمایش ارقام تایمر بزرگ */}
        <div className="space-y-3 my-4">
          <div
            className={`font-mono text-7xl sm:text-9xl font-black tracking-tighter tabular-nums ${
              state.awaiting_decision || displayOvertimeMs > 0
                ? 'text-amber-500 animate-pulse'
                : state.running
                ? 'text-white'
                : 'text-slate-400'
            }`}
          >
            {displayOvertimeMs > 0 ? `+${formatMs(displayOvertimeMs)}` : formatMs(remainingMs)}
          </div>

          {displayOvertimeMs > 0 ? (
            <div className="text-sm font-bold text-amber-400 bg-amber-500/10 border border-amber-500/20 px-4 py-1.5 rounded-full inline-block">
              زمان اضافه سخنرانی در حال محاسبه است
            </div>
          ) : (
            <div className="text-xs text-slate-500 font-mono">
              زمان مصرف‌شده: {formatMs(displayElapsedMs)} / سقف مجاز: {formatMs(limitMs)}
            </div>
          )}
        </div>

        {/* نوار پیشرفت زمان */}
        <div className="w-full max-w-xl bg-slate-800 h-3 rounded-full overflow-hidden p-0.5 border border-slate-700/50">
          <div
            className={`h-full rounded-full transition-all duration-300 ${
              displayOvertimeMs > 0 ? 'bg-amber-500' : 'bg-blue-500 shadow-lg shadow-blue-500/50'
            }`}
            style={{ width: `${displayOvertimeMs > 0 ? 100 : progressPercent}%` }}
          />
        </div>

        {/* دکمه‌های کنترل پخش */}
        <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
          {!state.running ? (
            <button
              onClick={() => handleAction(displayElapsedMs > 0 ? 'resume' : 'start')}
              disabled={!currentSp || currentSp.is_finished}
              className="px-8 py-4 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-extrabold text-lg rounded-2xl shadow-xl shadow-blue-600/30 transition-all hover:scale-105 active:scale-95 disabled:opacity-40"
            >
              {displayElapsedMs > 0 ? '▶ ادامه تایمر' : '▶ شروع تایمر'}
            </button>
          ) : (
            <button
              onClick={() => handleAction('pause')}
              className="px-8 py-4 bg-amber-600 hover:bg-amber-500 active:bg-amber-700 text-white font-extrabold text-lg rounded-2xl shadow-xl shadow-amber-600/30 transition-all hover:scale-105 active:scale-95"
            >
              ⏸ توقف موقت (Pause)
            </button>
          )}

          <button
            onClick={() => handleAction('finish')}
            disabled={!currentSp || currentSp.is_finished}
            className="px-6 py-4 bg-slate-800 hover:bg-slate-700 text-slate-200 font-bold text-sm rounded-2xl border border-slate-700 transition-all hover:scale-105 active:scale-95 disabled:opacity-40"
          >
            ✓ اتمام سخنرانی {recordingEnabled && '(ذخیره ضبط)'}
          </button>

          <button
            onClick={() => handleAction('reset')}
            disabled={!currentSp || displayElapsedMs === 0}
            className="px-4 py-4 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white font-bold text-xs rounded-2xl border border-slate-700 transition-all disabled:opacity-40"
          >
            بازنشانی
          </button>
        </div>
      </div>

      {/* نوار پایینی لیست سخنرانان برای جابجایی سریع */}
      <div className="bg-slate-950 border-t border-slate-800 p-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between gap-4 overflow-x-auto pb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-slate-400 whitespace-nowrap ml-2">سخنرانان:</span>
            {state.speakers.map((sp, idx) => {
              const isCurrent = state.current_speaker_id === sp.id;
              return (
                <div
                  key={sp.id}
                  className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-bold border transition-all whitespace-nowrap ${
                    isCurrent
                      ? 'bg-blue-600 border-blue-500 text-white shadow-md shadow-blue-600/40'
                      : sp.is_finished
                      ? 'bg-slate-900 border-slate-800 text-slate-500'
                      : 'bg-slate-800/80 border-slate-700 text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  <button
                    onClick={() => handleAction('goto', sp.id)}
                    className="flex items-center gap-1.5 outline-none"
                  >
                    <span>{idx + 1}.</span>
                    <span>{sp.name || 'بدون نام'}</span>
                    {sp.is_finished && <span className="text-[10px] text-slate-400">(فریز)</span>}
                  </button>

                  <button
                    onClick={() => attemptDeleteSpeaker(sp)}
                    title="حذف این سخنران"
                    className="text-slate-400 hover:text-red-400 p-0.5"
                  >
                    ✕
                  </button>
                </div>
              );
            })}
          </div>

          <div className="flex items-center gap-2 whitespace-nowrap">
            <button
              onClick={() => handleAction('reset_all')}
              className="text-xs text-slate-400 hover:text-white underline p-1"
            >
              بازنشانی همه سخنران‌ها
            </button>
          </div>
        </div>
      </div>

      {/* مودال اعلان اتمام وقت سخنرانی (شرط کاربر) */}
      <OvertimeModal
        isOpen={showOvertimeModal}
        speakerName={currentSp?.name || ''}
        isRecording={recordingEnabled}
        onContinue={() => handleAction('continue_overtime')}
        onFinish={() => handleAction('finish_overtime')}
      />

      {/* مودال تأیید ذخیره ضبط هنگام حذف سخنران (شرط کاربر) */}
      <Modal
        isOpen={Boolean(deletingSpeakerPrompt)}
        onClose={() => setDeletingSpeakerPrompt(null)}
        title="تکلیف ضبط صوت سخنران جاری"
        maxWidth="max-w-md"
      >
        <div className="space-y-4 text-slate-800 text-right">
          <p className="text-sm">
            شما در حال حذف سخنران «{deletingSpeakerPrompt?.speakerName}» هستید که برای آن ضبط صوت فعال بوده است.
            آیا مایلید فایل صوتی ضبط‌شده تا این لحظه ذخیره شود یا دور ریخته شود؟
          </p>

          <div className="flex flex-col sm:flex-row gap-3 pt-3">
            <button
              onClick={() => confirmDeleteSpeakerWithRecording(true)}
              className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-xs"
            >
              ذخیره در آرشیو ضبط‌ها
            </button>
            <button
              onClick={() => confirmDeleteSpeakerWithRecording(false)}
              className="flex-1 px-4 py-2.5 bg-red-600 hover:bg-red-700 text-white font-bold rounded-xl text-xs"
            >
              دور ریختن ضبط
            </button>
          </div>
        </div>
      </Modal>

      {/* مودال QR کد */}
      {showQrModal && (
        <QrModal
          isOpen={true}
          onClose={() => setShowQrModal(false)}
          roomName={roomName}
          publicToken={publicToken}
        />
      )}
    </div>
  );
};
