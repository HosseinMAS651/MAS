import React, { useEffect, useState, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { api, isNotModified } from '../api/client';
import { PublicRoomState } from '../types';
import { formatMs, formatBytes } from '../utils/formatters';
import { QrModal } from '../components/QrModal';

export const PublicRoomPage: React.FC = () => {
  const { token } = useParams<{ token: string }>();

  const [state, setState] = useState<PublicRoomState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');
  const [showQr, setShowQr] = useState<boolean>(false);

  const etagRef = useRef<string>('');

  const fetchPublicState = async () => {
    if (!token) return;
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
    }
  };

  useEffect(() => {
    fetchPublicState();
    const interval = setInterval(fetchPublicState, 1500);
    return () => clearInterval(interval);
  }, [token]);

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
    <div className="min-h-screen bg-slate-900 text-white flex flex-col justify-between selection:bg-blue-600">
      {/* سربرگ تماشاگر */}
      <header className="px-6 py-4 bg-slate-950/70 backdrop-blur-md border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-xl bg-blue-600 text-white font-black flex items-center justify-center text-lg shadow-md shadow-blue-600/30">
            مـاس
          </span>
          <div>
            <h1 className="text-base font-extrabold text-white leading-tight">{state.room_name}</h1>
            <span className="text-[11px] text-slate-400">صفحهٔ زندهٔ تماشاگران</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {state.running ? (
            <span className="px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-bold rounded-full flex items-center gap-1.5 animate-pulse">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              در حال پخش زنده
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

      {/* بخش نمایش اصلی سخنران جاری و تایمر بزرگ */}
      <main className="max-w-4xl mx-auto w-full px-4 py-8 flex flex-col items-center justify-center text-center space-y-6">
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

        {/* ارقام تایمر */}
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

        {/* فایل‌های نمایش زنده برای تماشاگران */}
        {state.live_files && state.live_files.length > 0 && (
          <div className="w-full max-w-2xl bg-slate-950/80 border border-slate-800 rounded-3xl p-6 text-right mt-6 space-y-4">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <span>📄</span> فایل‌های قابل مشاهدهٔ سخنرانی
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {state.live_files.map((f) => (
                <div
                  key={f.id}
                  className="p-3 bg-slate-900 border border-slate-800 rounded-xl flex items-center justify-between text-xs"
                >
                  <div className="space-y-0.5">
                    <p className="font-bold text-slate-200 line-clamp-1">{f.filename}</p>
                    <span className="text-[11px] text-slate-500">{formatBytes(f.size_bytes)}</span>
                  </div>
                  <a
                    href={`/api/public/${token}/files/${f.id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="px-3 py-1.5 bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded-lg font-bold transition-colors"
                  >
                    مشاهده ↗
                  </a>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      {/* نوار پایینی: اسامی سخنرانان برای تماشاگران */}
      <footer className="bg-slate-950 border-t border-slate-800 p-4">
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
