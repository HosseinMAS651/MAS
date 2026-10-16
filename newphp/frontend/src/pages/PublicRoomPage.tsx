import React, { useEffect, useState, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import { alertManager } from '../utils/alerts';
import { AudioRecorder } from '../utils/audioRecorder';
import { PublicRoomState, SpeechFile } from '../types';
import { formatMs, formatBytes } from '../utils/formatters';
import { QrModal } from '../components/QrModal';
import { FloatingReactions } from '../components/FloatingReactions';
import { ThemeToggle } from '../components/ThemeToggle';

const REACTIONS = [
  { key: 'heart', label: '❤️' },
  { key: 'clap', label: '👏' },
  { key: 'like', label: '👍' },
  { key: 'fire', label: '🔥' },
  { key: 'star', label: '⭐' },
];

type PublicSpeakerSession = { sessionToken: string; speakerId: number; name: string };
type PublicRoleChoice = 'viewer' | 'speaker' | null;

const sessionStorageKey = (token?: string) => token ? `mas:speaker-session:${token}` : '';
const recordingStorageKey = (token?: string) => token ? `mas:speaker-recording:${token}` : '';

function readSpeakerSession(token?: string): PublicSpeakerSession | null {
  if (!token || typeof window === 'undefined') return null;
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(sessionStorageKey(token)) || 'null');
    if (saved && typeof saved.sessionToken === 'string' && Number.isInteger(saved.speakerId)) return saved;
  } catch { /* storage may be disabled */ }
  return null;
}

function readRecordingSessionId(token?: string): number | null {
  if (!token || typeof window === 'undefined') return null;
  const parsed = Number(window.sessionStorage.getItem(recordingStorageKey(token)) || 0);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export const PublicRoomPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [state, setState] = useState<PublicRoomState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [showQr, setShowQr] = useState<boolean>(false);
  const [speakerSession, setSpeakerSession] = useState<PublicSpeakerSession | null>(() => readSpeakerSession(token));
  const [speakerChoice, setSpeakerChoice] = useState<PublicRoleChoice>(() => readSpeakerSession(token) ? 'speaker' : null);
  const [speakerCode, setSpeakerCode] = useState('');
  const [speakerStatus, setSpeakerStatus] = useState<'offline' | 'connected' | 'ready'>('offline');
  const [microphoneReady, setMicrophoneReady] = useState(false);
  const [speakerError, setSpeakerError] = useState('');
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const [recordingRevision, setRecordingRevision] = useState(0);
  const [speakerUploadFile, setSpeakerUploadFile] = useState<File | null>(null);
  const [speakerUploadMessage, setSpeakerUploadMessage] = useState('');
  const [uploadingSpeakerFile, setUploadingSpeakerFile] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermission | 'unsupported'>(() =>
    typeof window !== 'undefined' && 'Notification' in window ? Notification.permission : 'unsupported'
  );

  // فایل در حال نمایش درون‌صفحه‌ای (Inline Presentation View)
  const [activeInlineFile, setActiveInlineFile] = useState<SpeechFile | null>(null);

  // واکنش‌های زنده
  const [recentReactions, setRecentReactions] = useState<Array<{ id: string; emoji: string }>>([]);
  const [reactionsEnabled, setReactionsEnabled] = useState<boolean>(true);
  const [sendingReaction, setSendingReaction] = useState<boolean>(false);

  const etagRef = useRef<string>('');
  const statePollRunningRef = useRef(false);
  const reactionsPollRunningRef = useRef(false);
  const latestStateRef = useRef<PublicRoomState | null>(null);
  const speakerRecorderRef = useRef<AudioRecorder | null>(null);
  const recordingSessionIdRef = useRef<number | null>(readRecordingSessionId(token));
  const recordingTransitionRef = useRef(false);
  const lastAlertedTurnRef = useRef<string>('');

  const speakerAuthHeaders = (
    activeSession: PublicSpeakerSession | null = speakerSession,
  ): Record<string, string> => activeSession ? { Authorization: `Bearer ${activeSession.sessionToken}` } : {};

  const clearSpeakerSession = () => {
    try {
      if (token) window.sessionStorage.removeItem(sessionStorageKey(token));
    } catch { /* storage may be disabled */ }
    setSpeakerSession(null);
    setSpeakerStatus('offline');
    setMicrophoneReady(false);
  };

  const enterSpeaker = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token || speakerBusy) return;
    setSpeakerBusy(true);
    setSpeakerError('');
    try {
      const result = await api.post(`/api/public/${token}/speaker/enter`, { code: speakerCode });
      const nextSession: PublicSpeakerSession = {
        sessionToken: result.session_token,
        speakerId: result.speaker.id,
        name: result.speaker.name || 'سخنران',
      };
      try { window.sessionStorage.setItem(sessionStorageKey(token), JSON.stringify(nextSession)); } catch { /* session can continue in memory */ }
      setSpeakerSession(nextSession);
      setSpeakerChoice('speaker');
      setSpeakerStatus('connected');
      setMicrophoneReady(false);
      setSpeakerCode('');
      setSpeakerError('');
    } catch (err: any) {
      setSpeakerError(err.message || 'ورود با کد سخنران انجام نشد.');
    } finally {
      setSpeakerBusy(false);
    }
  };

  const enableSpeakerMicrophone = async () => {
    if (!speakerSession || !token || speakerBusy) return;
    setSpeakerBusy(true);
    setSpeakerError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('مرورگر یا اتصال امن فعلی امکان دسترسی به میکروفون را نمی‌دهد.');
      alertManager.prepare();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      await api.postWithHeaders(
        `/api/public/${token}/speaker/heartbeat`,
        { microphone_ready: true },
        speakerAuthHeaders(),
      );
      setMicrophoneReady(true);
      setSpeakerStatus('ready');
      setSpeakerError('');
      setRecordingRevision((revision) => revision + 1);
    } catch (err: any) {
      setMicrophoneReady(false);
      setSpeakerStatus('connected');
      setSpeakerError(err.message || 'اجازهٔ میکروفون فعال نشد. دسترسی مرورگر و تنظیمات دستگاه را بررسی کنید.');
    } finally {
      setSpeakerBusy(false);
    }
  };

  const finishSpeakerRecording = async (save: boolean): Promise<boolean> => {
    if (recordingTransitionRef.current) return false;
    recordingTransitionRef.current = true;
    let shouldSave = save;
    let finalized = true;
    try {
      const recorder = speakerRecorderRef.current;
      if (recorder) {
        try {
          await recorder.stop();
        } catch (err: any) {
          setSpeakerError(err.message || 'بخشی از صدای ضبط‌شده ارسال نشد؛ تلاش می‌کنیم قطعه‌های موجود را ذخیره کنیم.');
        }
        speakerRecorderRef.current = null;
      }
      const recordingId = recordingSessionIdRef.current;
      if (recordingId && token && speakerSession) {
        await api.postWithHeaders(
          `/api/public/${token}/speaker/recording/finish`,
          { session_id: recordingId, save: shouldSave },
          speakerAuthHeaders(),
        );
        recordingSessionIdRef.current = null;
        try { window.sessionStorage.removeItem(recordingStorageKey(token)); } catch { /* storage may be disabled */ }
      }
    } catch (err: any) {
      finalized = false;
      setSpeakerError(err.message || 'پایان ضبط به سرور نرسید؛ اتصال را بررسی کنید.');
    } finally {
      recordingTransitionRef.current = false;
      if (finalized) setRecordingRevision((revision) => revision + 1);
    }
    return finalized;
  };

  const startSpeakerRecording = async () => {
    if (!token || !speakerSession || !microphoneReady || recordingTransitionRef.current) return;
    const currentRecorder = speakerRecorderRef.current;
    if (currentRecorder) {
      if (currentRecorder.getState() === 'paused') currentRecorder.resume();
      return;
    }

    recordingTransitionRef.current = true;
    const targetSpeakerId = speakerSession.speakerId;
    let createdRecordingId: number | null = null;
    let startedSuccessfully = false;
    try {
      if (!AudioRecorder.isSupported()) throw new Error('ضبط صدا در این مرورگر پشتیبانی نمی‌شود. از مرورگر به‌روز و اتصال HTTPS استفاده کنید.');
      const mimeType = AudioRecorder.getSupportedMimeType() || 'audio/webm';
      const result = await api.postWithHeaders(
        `/api/public/${token}/speaker/recording/start`,
        { mime_type: mimeType },
        speakerAuthHeaders(),
      );
      createdRecordingId = Number(result.session_id);
      if (!Number.isInteger(createdRecordingId) || createdRecordingId <= 0) throw new Error('شناسهٔ نشست ضبط از سرور دریافت نشد.');
      recordingSessionIdRef.current = createdRecordingId;
      try { window.sessionStorage.setItem(recordingStorageKey(token), String(createdRecordingId)); } catch { /* session can continue in memory */ }

      const chunkExtension = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm';
      const activeSession = speakerSession;
      const recorder = new AudioRecorder();
      speakerRecorderRef.current = recorder;
      await recorder.start({
        timesliceMs: 5_000,
        initialSeq: Number(result.next_seq || 0),
        onChunk: async (chunk, seq) => {
          const form = new FormData();
          form.append('session_id', String(createdRecordingId));
          form.append('seq', String(seq));
          form.append('chunk', chunk, `speaker-${seq}.${chunkExtension}`);
          await api.uploadWithHeaders(
            `/api/public/${token}/speaker/recording/chunk`,
            form,
            speakerAuthHeaders(activeSession),
          );
        },
        onError: (err) => setSpeakerError(err.message || 'آپلود بخشی از ضبط ناموفق بود.'),
      });
      startedSuccessfully = true;
      setSpeakerError('');
    } catch (err: any) {
      speakerRecorderRef.current = null;
      if (createdRecordingId && token && speakerSession) {
        try {
          await api.postWithHeaders(
            `/api/public/${token}/speaker/recording/finish`,
            { session_id: createdRecordingId, save: false },
            speakerAuthHeaders(),
          );
          recordingSessionIdRef.current = null;
          try { window.sessionStorage.removeItem(recordingStorageKey(token)); } catch { /* ignore */ }
        } catch { /* the cleanup worker will recover an abandoned empty recording */ }
      }
      setSpeakerError(err.message || 'ضبط خودکار صدا آغاز نشد.');
    } finally {
      recordingTransitionRef.current = false;
      const latest = latestStateRef.current;
      if (startedSuccessfully || !latest?.running || latest.current_speaker?.id !== targetSpeakerId) {
        setRecordingRevision((revision) => revision + 1);
      }
    }
  };

  const leaveSpeaker = async () => {
    if (!token || !speakerSession || speakerBusy) return;
    setSpeakerBusy(true);
    try {
      if (recordingTransitionRef.current) {
        setSpeakerError('ضبط در حال شروع یا پایان است؛ چند لحظه صبر کنید و دوباره تلاش کنید.');
        return;
      }
      const recordingFinalized = await finishSpeakerRecording(true);
      if (!recordingFinalized) return;
      await api.postWithHeaders(`/api/public/${token}/speaker/leave`, {}, speakerAuthHeaders());
      clearSpeakerSession();
      setSpeakerChoice('viewer');
      setSpeakerError('');
    } catch (err: any) {
      setSpeakerError(err.message || 'خروج از نشست سخنران انجام نشد.');
    } finally {
      setSpeakerBusy(false);
    }
  };

  const requestBrowserNotifications = async () => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setNotificationPermission('unsupported');
      return;
    }
    try {
      const permission = await Notification.requestPermission();
      setNotificationPermission(permission);
      if (permission !== 'granted') setSpeakerError('اعلان مرورگر فعال نشد؛ صدای صفحه و لرزش دستگاه همچنان بسته به پشتیبانی مرورگر در دسترس‌اند.');
      else setSpeakerError('');
    } catch {
      setSpeakerError('مرورگر اجازهٔ درخواست اعلان را نداد.');
    }
  };

  const uploadSpeakerFile = async () => {
    if (!token || !speakerSession || !speakerUploadFile || uploadingSpeakerFile) return;
    setUploadingSpeakerFile(true);
    setSpeakerUploadMessage('');
    setSpeakerError('');
    try {
      const form = new FormData();
      form.append('file', speakerUploadFile);
      await api.uploadWithHeaders(`/api/public/${token}/speaker/files`, form, speakerAuthHeaders());
      setSpeakerUploadFile(null);
      setSpeakerUploadMessage('فایل برای بررسی مالک فرستاده شد و تا زمان تأیید عمومی نمی‌شود.');
    } catch (err: any) {
      setSpeakerError(err.message || 'آپلود فایل انجام نشد.');
    } finally {
      setUploadingSpeakerFile(false);
    }
  };

  const fetchPublicState = async () => {
    if (!token || statePollRunningRef.current) return;
    statePollRunningRef.current = true;
    try {
      const headers: Record<string, string> = {};
      if (etagRef.current) headers['If-None-Match'] = etagRef.current;
      const result = await api.getWithMeta(`/api/public/${token}/state`, headers);
      if (result.etag) etagRef.current = result.etag;
      if (result.notModified) return;
      if (result.data?.state) {
        latestStateRef.current = result.data.state;
        setState(result.data.state);
        setError('');
      }
    } catch (err: any) {
      if (!latestStateRef.current) {
        setError(err.message || 'اتاق عمومی یافت نشد یا دسترسی غیرفعال است.');
      }
    } finally {
      setLoading(false);
      statePollRunningRef.current = false;
    }
  };

  const pollReactions = async () => {
    if (!token || reactionsPollRunningRef.current) return;
    reactionsPollRunningRef.current = true;
    try {
      const res = await api.get(`/api/public/${token}/reactions`);
      if (res && res.ok) {
        setReactionsEnabled(res.reactions_enabled ?? true);
        if (res.reactions && res.reactions.length > 0) {
          setRecentReactions(res.reactions);
        }
      }
    } catch {
      // نادیده گرفتن خطای دوره‌ای
    } finally {
      reactionsPollRunningRef.current = false;
    }
  };

  useEffect(() => {
    etagRef.current = '';
    latestStateRef.current = null;
    const savedSpeakerSession = readSpeakerSession(token);
    setSpeakerSession(savedSpeakerSession);
    setSpeakerChoice(savedSpeakerSession ? 'speaker' : null);
    setMicrophoneReady(false);
    setSpeakerStatus(savedSpeakerSession ? 'connected' : 'offline');
    recordingSessionIdRef.current = readRecordingSessionId(token);
    setState(null);
    setError('');
    setLoading(true);
    fetchPublicState();
    pollReactions();
    const intervalState = setInterval(fetchPublicState, 1500);
    const intervalReactions = setInterval(pollReactions, 2000);
    return () => {
      clearInterval(intervalState);
      clearInterval(intervalReactions);
    };
  }, [token]);

  useEffect(() => {
    if (!speakerSession || !token || !state?.speaker_mode_enabled) return;
    let disposed = false;
    const heartbeat = async () => {
      try {
        const result = await api.postWithHeaders(
          `/api/public/${token}/speaker/heartbeat`,
          { microphone_ready: microphoneReady },
          speakerAuthHeaders(speakerSession),
        );
        if (!disposed) setSpeakerStatus(result.presence_status);
      } catch (err: any) {
        if (disposed) return;
        if (err.status === 401 || err.status === 404) {
          if (speakerRecorderRef.current) void finishSpeakerRecording(false);
          clearSpeakerSession();
          setSpeakerChoice('speaker');
          setSpeakerError('نشست این دستگاه منقضی یا با دستگاه دیگری جایگزین شده است؛ دوباره کد سخنران را وارد کنید.');
        } else {
          setSpeakerError(err.message || 'ارتباط با نشست سخنران موقتاً قطع شده است.');
        }
      }
    };
    void heartbeat();
    const interval = window.setInterval(() => { void heartbeat(); }, 15_000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [token, speakerSession, microphoneReady, state?.speaker_mode_enabled]);

  useEffect(() => {
    if (!state || !speakerSession) return;
    const isMyTurn = state.current_speaker?.id === speakerSession.speakerId;
    if (state.running && isMyTurn) {
      const turnKey = `${speakerSession.speakerId}:${state.current_index}`;
      if (lastAlertedTurnRef.current !== turnKey) {
        lastAlertedTurnRef.current = turnKey;
        alertManager.playTurnAlert();
        if (typeof document !== 'undefined' && document.visibilityState === 'hidden'
          && typeof window !== 'undefined' && 'Notification' in window
          && Notification.permission === 'granted') {
          const notification = new Notification('نوبت شما رسیده است', {
            body: `زمان سخنرانی شما در «${state.room_name}» آغاز شد.`,
            tag: `mas-speaker-turn-${speakerSession.speakerId}`,
          });
          notification.onclick = () => window.focus();
        }
      }
    }
  }, [state?.running, state?.current_speaker?.id, state?.current_index, speakerSession?.speakerId]);

  useEffect(() => {
    if (!speakerSession) {
      if (speakerRecorderRef.current) void finishSpeakerRecording(true);
      return;
    }
    if (!state) return;
    if (!state.speaker_mode_enabled) {
      if (speakerRecorderRef.current || recordingSessionIdRef.current) void finishSpeakerRecording(true);
      clearSpeakerSession();
      return;
    }

    const isMyTurn = state.current_speaker?.id === speakerSession.speakerId;
    const recorder = speakerRecorderRef.current;
    if (microphoneReady && isMyTurn && state.running) {
      void startSpeakerRecording();
      return;
    }
    if (recorder) {
      if (isMyTurn && recorder.getState() === 'recording') recorder.pause();
      else if (!isMyTurn) void finishSpeakerRecording(true);
    } else if (!isMyTurn && recordingSessionIdRef.current) {
      void finishSpeakerRecording(true);
    }
  }, [
    state?.speaker_mode_enabled,
    state?.running,
    state?.current_speaker?.id,
    speakerSession,
    microphoneReady,
    token,
    recordingRevision,
  ]);

  // بررسی خودکار باز بودن فایلی که شاید در لیست جدید دیگر در دسترس نباشد
  useEffect(() => {
    if (activeInlineFile && state?.live_files) {
      const stillExists = state.live_files.some((f) => f.id === activeInlineFile.id);
      if (!stillExists) {
        setActiveInlineFile(null);
      }
    }
  }, [state?.live_files, activeInlineFile]);

  const sendEmojiReaction = async (emojiKey: string) => {
    if (!reactionsEnabled || sendingReaction || !token) return;
    setSendingReaction(true);
    try {
      await api.post(`/api/public/${token}/reactions`, { emoji: emojiKey });
      // فوراً به‌صورت محلی هم نشان دهیم
      setRecentReactions((prev) => [
        ...prev,
        { id: Math.random().toString(), emoji: emojiKey },
      ]);
    } catch {
      // واکنش با شکست مواجه شد
    } finally {
      setTimeout(() => setSendingReaction(false), 300);
    }
  };

  if (loading && !state) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center text-slate-400 font-bold">
        در حال اتصال به اتاق پخش زنده…
      </div>
    );
  }

  if (!state) {
    return (
      <div className="min-h-screen bg-slate-900 flex flex-col items-center justify-center p-4 text-center space-y-4">
        <div className="w-16 h-16 bg-red-500/10 text-red-400 rounded-full flex items-center justify-center text-3xl font-bold">
          ✕
        </div>
        <h2 className="text-xl font-bold text-white">اتاق پخش در دسترس نیست</h2>
        <p className="text-sm text-slate-400 max-w-md">{error || 'لینک نامعتبر است یا جلسه به اتمام رسیده است.'}</p>
      </div>
    );
  }

  const curSp = state.current_speaker;
  const limitMs = state.limit_ms || 300000;
  const remainingMs = Math.max(0, limitMs - state.elapsed_ms);
  const progressPercent = Math.min(100, (state.elapsed_ms / limitMs) * 100);

  return (
    <div className="min-h-screen bg-slate-900 text-white flex flex-col justify-between selection:bg-blue-600 relative overflow-x-hidden">
      {/* انیمیشن شناور واکنش‌های زنده (Instagram Live style) */}
      <FloatingReactions reactions={recentReactions} />

      {/* سربرگ تماشاگر */}
      <header className="px-6 py-4 bg-slate-950/70 backdrop-blur-md border-b border-slate-800 flex items-center justify-between sticky top-0 z-30">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-xl bg-blue-600 text-white font-black flex items-center justify-center text-lg shadow-md shadow-blue-600/30">
            مـاس
          </span>
          <div>
            <h1 className="text-base font-extrabold text-white leading-tight">{state.room_name}</h1>
            <span className="text-[11px] text-slate-400">صفحهٔ زندهٔ تماشاگران</span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* دانلود گزارش رسمی رویداد */}
          <a
            href={`/api/public/${token}/report/pdf`}
            download
            className="px-3 py-1.5 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-colors"
            title="دانلود گزارش رسمی PDF رویداد"
          >
            <span>📊</span>
            <span className="hidden sm:inline">گزارش PDF</span>
          </a>

          {/* سوئیچ پوسته */}
          <ThemeToggle className="bg-slate-800 border-slate-700 text-slate-300" />

          {state.running ? (
            <span className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-bold rounded-full flex items-center gap-1.5 animate-pulse">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span className="hidden sm:inline">در حال پخش زنده</span>
              <span className="sm:hidden">پخش</span>
            </span>
          ) : (
            <span className="px-3 py-1 bg-slate-800 border border-slate-700 text-slate-400 text-xs font-bold rounded-full">
              متوقف
            </span>
          )}

          <button
            onClick={() => setShowQr(true)}
            className="p-2 bg-slate-800 hover:bg-slate-700 rounded-xl text-slate-300 transition-colors"
            title="نمایش QR کد"
          >
            📱
          </button>
        </div>
      </header>

      {/* بخش نمایش اصلی یا نمایش ترکیبی با فایل زنده (Inline Presentation View) */}
      <main className="max-w-6xl mx-auto w-full px-4 py-8 flex flex-col items-center justify-center text-center space-y-6 flex-1">
        {state.speaker_mode_enabled && (
          <section dir="rtl" className="w-full max-w-2xl bg-slate-950/90 border border-slate-700 rounded-3xl p-5 sm:p-6 text-right space-y-4 shadow-xl">
            <div>
              <h2 className="text-lg font-black text-white">ورود سخنران با کد</h2>
              <p className="mt-1 text-xs sm:text-sm text-slate-400 leading-6">
                تماشاگران می‌توانند فقط صفحه را ببینند؛ برای ضبط صدای نوبت، سخنران باید با کد وارد شود و میکروفون همین دستگاه را صریحاً فعال کند. شروع و توقف تایمر فقط در اختیار مالک اتاق است.
              </p>
            </div>

            {!speakerSession && speakerChoice === null && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setSpeakerChoice('viewer')}
                  className="px-4 py-3 rounded-2xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-white font-bold transition-colors"
                >
                  ورود به‌عنوان تماشاگر
                </button>
                <button
                  type="button"
                  onClick={() => { setSpeakerChoice('speaker'); setSpeakerError(''); }}
                  className="px-4 py-3 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-bold transition-colors"
                >
                  ورود به‌عنوان سخنران
                </button>
              </div>
            )}

            {!speakerSession && speakerChoice === 'viewer' && (
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-2xl bg-slate-900 border border-slate-800">
                <span className="text-sm text-slate-300">شما به‌عنوان تماشاگر وارد شده‌اید؛ نیازی به فعال‌سازی میکروفون نیست.</span>
                <button type="button" onClick={() => setSpeakerChoice(null)} className="text-xs text-blue-400 hover:text-blue-300 font-bold">
                  تغییر نقش
                </button>
              </div>
            )}

            {!speakerSession && speakerChoice === 'speaker' && (
              <form onSubmit={enterSpeaker} className="space-y-3">
                <label htmlFor="public-speaker-code" className="block text-sm font-bold text-slate-200">کد چهارحرفی/رقمی سخنران</label>
                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    id="public-speaker-code"
                    value={speakerCode}
                    onChange={(event) => setSpeakerCode(event.currentTarget.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 4))}
                    inputMode="text"
                    autoComplete="one-time-code"
                    maxLength={4}
                    required
                    dir="ltr"
                    aria-label="کد چهارکاراکتری سخنران"
                    className="flex-1 px-4 py-3 rounded-xl bg-slate-900 border border-slate-700 text-white text-center tracking-[0.4em] font-black text-xl focus:outline-none focus:border-blue-500"
                    placeholder="AB23"
                  />
                  <button disabled={speakerBusy || speakerCode.length !== 4} className="px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-bold">
                    {speakerBusy ? 'در حال بررسی…' : 'ورود'}
                  </button>
                </div>
                <p className="text-[11px] text-slate-500">کد را از مالک اتاق دریافت کنید. ورود، این دستگاه را برای همان کد فعال می‌کند و دستگاه قبلی را خارج می‌سازد.</p>
                <button type="button" onClick={() => { setSpeakerChoice(null); setSpeakerError(''); }} className="text-xs text-slate-400 hover:text-white font-bold">
                  بازگشت به انتخاب نقش
                </button>
              </form>
            )}

            {speakerSession && speakerChoice === 'speaker' && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-900 border border-slate-800 p-4">
                  <div>
                    <p className="font-bold text-white">{speakerSession.name}</p>
                    <p className={`mt-1 text-xs font-bold ${speakerStatus === 'ready' ? 'text-emerald-400' : speakerStatus === 'connected' ? 'text-amber-300' : 'text-slate-500'}`}>
                      {speakerStatus === 'ready' ? 'آماده؛ میکروفون این دستگاه فعال است' : speakerStatus === 'connected' ? 'متصل؛ برای آماده‌شدن میکروفون را فعال کنید' : 'آفلاین'}
                    </p>
                  </div>
                  <button type="button" disabled={speakerBusy} onClick={enableSpeakerMicrophone} className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-bold">
                    {speakerBusy ? 'در حال بررسی…' : microphoneReady ? 'بررسی دوبارهٔ میکروفون' : 'فعال‌سازی میکروفون'}
                  </button>
                </div>

                <div className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-4 text-xs text-slate-300 leading-6">
                  {state.current_speaker?.id === speakerSession.speakerId && state.running
                    ? 'نوبت شما فعال است؛ ضبط صدا از همین دستگاه و ارسال تکه‌ای آغاز می‌شود.'
                    : 'تا وقتی مالک تایمر را برای شما فعال نکند، صدایی ضبط نمی‌شود. برای ضبط، این صفحه را باز نگه دارید و دسترسی میکروفون را مجاز کنید.'}
                  <p className="mt-1 text-[11px] text-slate-500">هشدار صدا/لرزش و اعلان پس‌زمینه به پشتیبانی و مجوزهای مرورگر و دستگاه وابسته‌اند؛ پس از بستن صفحه یا قفل‌شدن گوشی تضمین نمی‌شوند.</p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button type="button" disabled={notificationPermission === 'unsupported' || notificationPermission === 'granted' || notificationPermission === 'denied'} onClick={requestBrowserNotifications} className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-bold">
                    {notificationPermission === 'granted' ? 'اعلان مرورگر فعال است' : notificationPermission === 'denied' ? 'اعلان در تنظیمات مرورگر مسدود است' : notificationPermission === 'unsupported' ? 'اعلان مرورگر پشتیبانی نمی‌شود' : 'فعال‌کردن اعلان پس‌زمینه'}
                  </button>
                  <button type="button" disabled={speakerBusy} onClick={leaveSpeaker} className="px-3 py-2 rounded-xl bg-red-950/60 hover:bg-red-900 border border-red-900/60 text-red-200 text-xs font-bold">
                    خروج از حالت سخنران
                  </button>
                </div>

                {state.speaker_uploads_enabled && (
                  <div className="border-t border-slate-800 pt-4 space-y-2">
                    <label htmlFor="speaker-file-upload" className="block text-sm font-bold text-slate-200">ارسال فایل برای بررسی مالک</label>
                    <div className="flex flex-col sm:flex-row gap-2">
                      <input id="speaker-file-upload" type="file" onChange={(event) => setSpeakerUploadFile(event.currentTarget.files?.[0] || null)} className="flex-1 min-w-0 text-xs text-slate-300 file:mr-2 file:px-3 file:py-2 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
                      <button type="button" disabled={!speakerUploadFile || uploadingSpeakerFile} onClick={uploadSpeakerFile} className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white text-xs font-bold">
                        {uploadingSpeakerFile ? 'در حال ارسال…' : 'ارسال برای تأیید'}
                      </button>
                    </div>
                    <p className="text-[11px] text-slate-500">فایل تا تأیید مالک خصوصی می‌ماند و برای تماشاگران نمایش داده نمی‌شود.</p>
                    {speakerUploadMessage && <p role="status" className="text-xs text-emerald-300">{speakerUploadMessage}</p>}
                  </div>
                )}
              </div>
            )}

            {speakerError && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{speakerError}</p>}
          </section>
        )}

        {/* اگر فایلی برای نمایش زنده باز شده باشد، پنل نمایش درون‌صفحه‌ای ظاهر می‌شود */}
        {activeInlineFile && (
          <div className="w-full bg-slate-950 border border-slate-800 rounded-3xl p-4 sm:p-6 text-right space-y-4 shadow-2xl transition-all">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-xl">📊</span>
                <span className="font-bold text-white text-sm line-clamp-1">{activeInlineFile.filename}</span>
              </div>
              <div className="flex items-center gap-3">
                <a
                  href={`/api/public/${token}/files/${activeInlineFile.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-blue-400 hover:text-blue-300 font-bold"
                >
                  باز کردن در برگه جدید ↗
                </a>
                <button
                  onClick={() => setActiveInlineFile(null)}
                  className="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-lg transition-colors"
                >
                  بستن پیش‌نمایش ✕
                </button>
              </div>
            </div>

            <div className="w-full h-[450px] sm:h-[600px] rounded-2xl overflow-hidden bg-slate-900 border border-slate-800 flex items-center justify-center">
              {activeInlineFile.content_type.startsWith('image/') ? (
                <img
                  src={`/api/public/${token}/files/${activeInlineFile.id}`}
                  alt={activeInlineFile.filename}
                  className="max-w-full max-h-full object-contain mx-auto"
                />
              ) : activeInlineFile.content_type.startsWith('audio/') ? (
                <audio
                  controls
                  src={`/api/public/${token}/files/${activeInlineFile.id}`}
                  className="w-full max-w-md"
                />
              ) : activeInlineFile.content_type.startsWith('video/') ? (
                <video
                  controls
                  playsInline
                  src={`/api/public/${token}/files/${activeInlineFile.id}`}
                  className="w-full h-full object-contain"
                />
              ) : activeInlineFile.content_type === 'application/pdf' || activeInlineFile.content_type.startsWith('text/') ? (
                <iframe
                  src={`/api/public/${token}/files/${activeInlineFile.id}`}
                  title={activeInlineFile.filename}
                  sandbox="allow-same-origin"
                  className="w-full h-full border-0"
                />
              ) : (
                <div className="flex flex-col items-center justify-center gap-4 px-6 text-center">
                  <div className="w-16 h-16 rounded-2xl bg-slate-800 flex items-center justify-center text-3xl">📄</div>
                  <p className="text-sm font-bold text-slate-300">این نوع فایل پیش‌نمایش مستقیم مرورگر را پشتیبانی نمی‌کند.</p>
                  <a
                    href={`/api/public/${token}/files/${activeInlineFile.id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold transition-colors"
                  >
                    باز کردن فایل ↗
                  </a>
                </div>
              )}
            </div>
          </div>
        )}

        {/* مشخصات سخنران جاری */}
        <div className="space-y-2">
          <span className="px-4 py-1 bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-bold rounded-full inline-block">
            سخنران {state.current_index + 1} از {state.total_speakers}
          </span>
          <h2 className="text-4xl sm:text-6xl font-black text-white tracking-tight">
            {curSp ? curSp.name || 'سخنران' : 'سخنرانی فعالی وجود ندارد'}
          </h2>
          {curSp?.description && (
            <p className="text-sm sm:text-base text-slate-400 max-w-xl mx-auto leading-relaxed">
              {curSp.description}
            </p>
          )}
        </div>

        {/* ارقام تایمر با فونت خوانا و روان */}
        <div className="my-2">
          <div
            className={`font-mono text-7xl sm:text-9xl font-black tracking-tighter tabular-nums ${
              state.overtime_ms > 0
                ? 'text-amber-500 animate-pulse'
                : state.running
                ? 'text-white'
                : 'text-slate-400'
            }`}
          >
            {state.overtime_ms > 0 ? `+${formatMs(state.overtime_ms)}` : formatMs(remainingMs)}
          </div>
          {state.overtime_ms > 0 && (
            <span className="text-sm font-bold text-amber-400 block mt-2">
              زمان اضافه سخنرانی (+{formatMs(state.overtime_ms)})
            </span>
          )}
        </div>

        {/* نوار پیشرفت */}
        <div className="w-full max-w-xl bg-slate-800 h-3 rounded-full overflow-hidden p-0.5 border border-slate-700/50">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              state.overtime_ms > 0 ? 'bg-amber-500' : 'bg-blue-500 shadow-lg shadow-blue-500/50'
            }`}
            style={{ width: `${state.overtime_ms > 0 ? 100 : progressPercent}%` }}
          />
        </div>

        {/* فایل‌های نمایش زنده سخنرانی (فیلترشده بر اساس سخنران فعال یا مشترک) */}
        {state.live_files && state.live_files.length > 0 && (
          <div className="w-full max-w-2xl bg-slate-950/80 border border-slate-800 rounded-3xl p-6 text-right mt-6 space-y-4">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <span>📄</span> اسلایدها و فایل‌های سخنرانی جاری
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {state.live_files.map((f) => {
                const isActive = activeInlineFile?.id === f.id;
                return (
                  <div
                    key={f.id}
                    className={`p-3 rounded-xl border flex items-center justify-between text-xs transition-colors ${
                      isActive
                        ? 'bg-blue-900/30 border-blue-500 text-white'
                        : 'bg-slate-900 border-slate-800'
                    }`}
                  >
                    <div className="space-y-0.5 max-w-[65%]">
                      <p className="font-bold text-slate-200 line-clamp-1">{f.filename}</p>
                      <span className="text-[11px] text-slate-500">
                        {f.upload_type === 'common' ? 'مشترک' : 'اختصاصی'} · {formatBytes(f.size_bytes)}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setActiveInlineFile(isActive ? null : f)}
                      className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                        isActive
                          ? 'bg-blue-600 text-white'
                          : 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/30'
                      }`}
                    >
                      {isActive ? 'بستن ✕' : 'نمایش زنده 👁'}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* دکمه‌های ارسال واکنش زنده (Floating Reactions Bar) */}
        {reactionsEnabled && (
          <div className="pt-4 flex flex-col items-center gap-2">
            <span className="text-xs text-slate-400 font-bold">ارسال واکنش زنده برای سخنران:</span>
            <div className="flex items-center gap-3 p-2 bg-slate-950/80 border border-slate-800 rounded-2xl shadow-xl backdrop-blur-md">
              {REACTIONS.map((r) => (
                <button
                  key={r.key}
                  type="button"
                  onClick={() => sendEmojiReaction(r.key)}
                  className="w-11 h-11 text-2xl hover:scale-125 active:scale-95 transition-transform flex items-center justify-center rounded-xl hover:bg-slate-800"
                  title={r.key}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* نوار پایینی: اسامی سخنرانان برای تماشاگران */}
      <footer className="bg-slate-950 border-t border-slate-800 p-4 sticky bottom-0 z-20">
        <div className="max-w-7xl mx-auto flex items-center gap-2 overflow-x-auto pb-1">
          <span className="text-xs font-bold text-slate-500 whitespace-nowrap ml-2">لیست نوبت‌ها:</span>
          {state.speakers.map((sp, idx) => {
            const isCur = state.current_speaker?.id === sp.id;
            return (
              <div
                key={sp.id}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold whitespace-nowrap border ${
                  isCur
                    ? 'bg-blue-600 border-blue-500 text-white shadow-md'
                    : sp.is_finished
                    ? 'bg-slate-900 border-slate-800 text-slate-500'
                    : 'bg-slate-800/60 border-slate-800 text-slate-300'
                }`}
              >
                <span>{idx + 1}.</span> {sp.name || 'بدون نام'}
                {sp.is_finished && ' ✓'}
              </div>
            );
          })}
        </div>
      </footer>

      {/* مودال QR کد */}
      {showQr && (
        <QrModal
          isOpen={true}
          onClose={() => setShowQr(false)}
          roomName={state.room_name}
          publicToken={token || null}
        />
      )}
    </div>
  );
};
