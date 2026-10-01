import React, { useEffect, useState, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { api, isNotModified } from '../api/client';
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

export const PublicRoomPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [state, setState] = useState<PublicRoomState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [showQr, setShowQr] = useState<boolean>(false);

  // فایل در حال نمایش درون‌صفحه‌ای (Inline Presentation View)
  const [activeInlineFile, setActiveInlineFile] = useState<SpeechFile | null>(null);

  // واکنش‌های زنده
  const [recentReactions, setRecentReactions] = useState<Array<{ id: string; emoji: string }>>([]);
  const [reactionsEnabled, setReactionsEnabled] = useState<boolean>(true);
  const [sendingReaction, setSendingReaction] = useState<boolean>(false);

  const etagRef = useRef<string>('');
  const statePollRunningRef = useRef(false);

  const fetchPublicState = async () => {
    if (!token || statePollRunningRef.current) return;
    statePollRunningRef.current = true;
    try {
      const headers: Record<string, string> = {};
      if (etagRef.current) {
        headers['If-None-Match'] = etagRef.current;
      }
      const res = await api.get(`/api/public/${token}/state`, headers);
      if (isNotModified(res)) return;
      if (res && res.state) {
        setState(res.state);
      }
    } catch (err: any) {
      if (!state) {
        setError(err.message || 'اتاق عمومی یافت نشد یا دسترسی غیرفعال است.');
      }
    } finally {
      setLoading(false);
      statePollRunningRef.current = false;
    }
  };

  const pollReactions = async () => {
    if (!token) return;
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
    }
  };

  useEffect(() => {
    fetchPublicState();
    pollReactions();
    const intervalState = setInterval(fetchPublicState, 1500);
    const intervalReactions = setInterval(pollReactions, 2000);
    return () => {
      clearInterval(intervalState);
      clearInterval(intervalReactions);
    };
  }, [token]);

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

  if (error || !state) {
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
              ) : (
                <iframe
                  src={`/api/public/${token}/files/${activeInlineFile.id}`}
                  title={activeInlineFile.filename}
                  className="w-full h-full border-0"
                />
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
