import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api/client';
import { RoomDetail, Speaker, SpeechFile } from '../types';
import { formatBytes, formatMs, formatDate } from '../utils/formatters';
import { Modal } from '../components/Modal';
import { QrModal } from '../components/QrModal';
import { ConfirmDialog } from '../components/ConfirmDialog';

export const RoomDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [room, setRoom] = useState<RoomDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // مودال ویرایش/افزودن سخنران
  const [editingSpeaker, setEditingSpeaker] = useState<Speaker | null>(null);
  const [speakerForm, setSpeakerForm] = useState({
    name: '',
    gender: '',
    age: '',
    description: '',
    speaking_seconds: 300,
  });

  // مودال حذف سخنران
  const [deletingSpeakerId, setDeletingSpeakerId] = useState<number | null>(null);

  // آپلود فایل
  const [uploading, setUploading] = useState(false);
  const [uploadFileObj, setUploadFileObj] = useState<File | null>(null);
  const [uploadSpeakerId, setUploadSpeakerId] = useState<string>('');

  // مودال QR
  const [showQr, setShowQr] = useState(false);

  // وضعیت جابه‌جایی دستی
  const [reordering, setReordering] = useState(false);

  const fetchRoom = async () => {
    try {
      const data = await api.get(`/api/rooms/${id}`);
      setRoom(data.room);
    } catch (err: any) {
      setError(err.message || 'خطا در بارگذاری مشخصات اتاق.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRoom();
  }, [id]);

  const handleSaveSpeaker = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingSpeaker) return;
    try {
      await api.put(`/api/rooms/${id}/speakers/${editingSpeaker.id}`, {
        name: speakerForm.name,
        gender: speakerForm.gender,
        age: speakerForm.age ? parseInt(speakerForm.age, 10) : null,
        description: speakerForm.description,
        speaking_seconds: speakerForm.speaking_seconds,
      });
      setEditingSpeaker(null);
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در ذخیره سخنران.');
    }
  };

  const handleDeleteSpeaker = async () => {
    if (!deletingSpeakerId) return;
    try {
      await api.delete(`/api/rooms/${id}/speakers/${deletingSpeakerId}`);
      setDeletingSpeakerId(null);
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در حذف سخنران.');
    }
  };

  const handleMoveSpeaker = async (index: number, direction: 'up' | 'down') => {
    if (!room || reordering) return;
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= room.speakers.length) return;

    const newSpeakers = [...room.speakers];
    const temp = newSpeakers[index];
    newSpeakers[index] = newSpeakers[targetIndex];
    newSpeakers[targetIndex] = temp;

    setReordering(true);
    try {
      await api.post(`/api/rooms/${id}/speakers/reorder`, {
        speaker_ids: newSpeakers.map((s) => s.id),
      });
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در جابه‌جایی نوبت سخنران.');
    } finally {
      setReordering(false);
    }
  };

  const handleUnfreeze = async (spId: number) => {
    try {
      await api.post(`/api/rooms/${id}/speakers/${spId}/unfreeze`);
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در رفع فریز سخنران.');
    }
  };

  const handleResetAll = async () => {
    if (!confirm('آیا از بازنشانی وضعیت همه سخنران‌ها و تایمر این اتاق اطمینان دارید؟')) return;
    try {
      await api.post(`/api/rooms/${id}/reset-all`);
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در بازنشانی سخنرانان.');
    }
  };

  const handleUploadFile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFileObj) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFileObj);
      if (uploadSpeakerId) {
        fd.append('upload_type', 'speaker');
        fd.append('speaker_id', uploadSpeakerId);
      } else {
        fd.append('upload_type', 'common');
      }
      await api.upload(`/api/rooms/${id}/files`, fd);
      setUploadFileObj(null);
      setUploadSpeakerId('');
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در آپلود فایل.');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteFile = async (fileId: number) => {
    if (!confirm('آیا از حذف این فایل مطمئن هستید؟')) return;
    try {
      await api.delete(`/api/rooms/${id}/files/${fileId}`);
      await fetchRoom();
    } catch (err: any) {
      alert(err.message || 'خطا در حذف فایل.');
    }
  };

  if (loading) {
    return <div className="text-center py-24 text-gray-400 dark:text-slate-500 font-bold">در حال دریافت اطلاعات اتاق…</div>;
  }
  if (error || !room) {
    return <div className="p-8 text-center text-red-600 dark:text-red-400 font-bold">{error || 'اتاق یافت نشد.'}</div>;
  }

  const orderModeLabel =
    room.order_mode === 'manual'
      ? 'دستی (تنظیم با دکمه‌های بالا/پایین)'
      : room.order_mode === 'alpha'
      ? 'الفبایی (خودکار)'
      : 'بر اساس سن (خودکار)';

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* سربرگ مشخصات اتاق */}
      <div className="bg-white dark:bg-slate-900 p-6 sm:p-8 rounded-3xl border border-gray-100 dark:border-slate-800 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6 transition-colors">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-black text-gray-900 dark:text-white">{room.name}</h1>
            <span className="px-3 py-1 bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 text-xs font-bold rounded-xl">
              ظرفیت {room.capacity} نفر
            </span>
            <span className="px-3 py-1 bg-gray-50 dark:bg-slate-800 text-gray-600 dark:text-slate-300 text-xs font-bold rounded-xl">
              ترتیب: {orderModeLabel}
            </span>
          </div>
          {room.description && <p className="text-sm text-gray-500 dark:text-slate-400 max-w-2xl">{room.description}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
          {/* دانلود گزارش رسمی PDF رویداد */}
          <a
            href={`/api/rooms/${room.id}/report/pdf`}
            download
            className="flex-1 md:flex-initial px-4 py-2.5 bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 font-bold rounded-xl text-xs flex items-center justify-center gap-2 border border-emerald-200 dark:border-emerald-800 transition-all"
          >
            <span>📊</span>
            دانلود گزارش PDF
          </a>

          {room.public_enabled && room.public_token && (
            <button
              onClick={() => setShowQr(true)}
              className="p-2.5 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:hover:bg-slate-700 rounded-xl text-gray-700 dark:text-slate-300 text-xs font-bold border border-gray-200 dark:border-slate-700 flex items-center gap-1.5 transition-colors"
              title="کد QR تماشاگران"
            >
              <span>📱</span>
              QR تماشاگران
            </button>
          )}

          <Link
            to={`/rooms/${room.id}/edit`}
            className="px-4 py-2.5 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-200 font-bold rounded-xl text-xs border border-gray-200 dark:border-slate-700 transition-colors"
          >
            تنظیمات اتاق
          </Link>

          <Link
            to={`/rooms/${room.id}/play`}
            className="flex-1 md:flex-initial px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-xs shadow-md shadow-blue-600/20 transition-all text-center flex items-center justify-center gap-1.5"
          >
            <span>▶</span>
            ورود به اتاق پخش
          </Link>
        </div>
      </div>

      {/* لیست سخنران‌ها */}
      <div className="bg-white dark:bg-slate-900 p-6 sm:p-8 rounded-3xl border border-gray-100 dark:border-slate-800 shadow-sm space-y-6 transition-colors">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-gray-100 dark:border-slate-800 pb-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">لیست و نوبت سخنرانان</h2>
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
              مشخصات، زمان هر فرد و اولویت اجرا ({orderModeLabel})
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleResetAll}
              className="text-xs font-bold text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 hover:bg-amber-100 dark:hover:bg-amber-900/40 px-3 py-1.5 rounded-xl border border-amber-200 dark:border-amber-800 transition-colors"
            >
              بازنشانی همهٔ تایمرها
            </button>
            <span className="text-xs font-bold text-gray-500 dark:text-slate-400 bg-gray-50 dark:bg-slate-800 px-3 py-1.5 rounded-xl border border-gray-100 dark:border-slate-800">
              {room.active_speaker_count} سخنران نام‌گذاری‌شده
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-right border-collapse">
            <thead>
              <tr className="border-b border-gray-100 dark:border-slate-800 text-xs font-bold text-gray-400 dark:text-slate-500">
                <th className="pb-3 px-3">ردیف</th>
                {room.order_mode === 'manual' && <th className="pb-3 px-3 text-center">جابه‌جایی</th>}
                <th className="pb-3 px-3">نام سخنران</th>
                <th className="pb-3 px-3">جنسیت / سن</th>
                <th className="pb-3 px-3">مدت زمان مجاز</th>
                <th className="pb-3 px-3">زمان مصرف‌شده</th>
                <th className="pb-3 px-3">وضعیت</th>
                <th className="pb-3 px-3 text-center">عملیات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-slate-800/60 text-sm">
              {room.speakers.map((sp, idx) => (
                <tr key={sp.id} className="hover:bg-blue-50/20 dark:hover:bg-slate-800/40 transition-colors">
                  <td className="py-3 px-3 text-xs font-bold text-gray-400 dark:text-slate-500">{idx + 1}</td>
                  {room.order_mode === 'manual' && (
                    <td className="py-3 px-3 text-center">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          disabled={idx === 0 || reordering}
                          onClick={() => handleMoveSpeaker(idx, 'up')}
                          title="انتقال به ردیف بالا"
                          className="w-7 h-7 rounded-lg bg-gray-100 dark:bg-slate-800 hover:bg-blue-100 dark:hover:bg-blue-900/60 text-gray-700 dark:text-slate-300 hover:text-blue-600 disabled:opacity-25 disabled:cursor-not-allowed flex items-center justify-center text-xs font-bold transition-colors"
                        >
                          ▲
                        </button>
                        <button
                          type="button"
                          disabled={idx === room.speakers.length - 1 || reordering}
                          onClick={() => handleMoveSpeaker(idx, 'down')}
                          title="انتقال به ردیف پایین"
                          className="w-7 h-7 rounded-lg bg-gray-100 dark:bg-slate-800 hover:bg-blue-100 dark:hover:bg-blue-900/60 text-gray-700 dark:text-slate-300 hover:text-blue-600 disabled:opacity-25 disabled:cursor-not-allowed flex items-center justify-center text-xs font-bold transition-colors"
                        >
                          ▼
                        </button>
                      </div>
                    </td>
                  )}
                  <td className="py-3 px-3 font-bold text-gray-800 dark:text-slate-200">
                    {sp.name ? sp.name : <span className="text-gray-300 dark:text-slate-600 font-normal">اسلات خالی</span>}
                  </td>
                  <td className="py-3 px-3 text-xs text-gray-500 dark:text-slate-400">
                    {[
                      sp.gender === 'male' ? 'مرد' : sp.gender === 'female' ? 'زن' : '',
                      sp.age ? `${sp.age} سال` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </td>
                  <td className="py-3 px-3 text-xs font-mono text-gray-700 dark:text-slate-300">
                    {Math.floor(sp.speaking_seconds / 60)} دقیقه ({sp.speaking_seconds}s)
                  </td>
                  <td className="py-3 px-3 text-xs font-mono text-gray-700 dark:text-slate-300">
                    {formatMs(sp.elapsed_ms)}
                    {sp.overtime_ms > 0 && <span className="text-amber-600 dark:text-amber-400 mr-1">+{formatMs(sp.overtime_ms)}</span>}
                  </td>
                  <td className="py-3 px-3">
                    {sp.is_finished ? (
                      <span className="px-2 py-0.5 bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 rounded-md text-[11px] font-bold">
                        فریز / پایان
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 rounded-md text-[11px] font-bold">
                        آماده
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-center space-x-2 space-x-reverse">
                    {sp.is_finished && (
                      <button
                        onClick={() => handleUnfreeze(sp.id)}
                        className="text-xs font-bold text-amber-600 hover:text-amber-700 p-1"
                        title="خروج از فریز و فعال‌سازی مجدد تایمر"
                      >
                        خروج از فریز
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setEditingSpeaker(sp);
                        setSpeakerForm({
                          name: sp.name,
                          gender: sp.gender,
                          age: sp.age ? String(sp.age) : '',
                          description: sp.description,
                          speaking_seconds: sp.speaking_seconds,
                        });
                      }}
                      className="text-xs font-bold text-blue-600 hover:text-blue-800 dark:text-blue-400 p-1"
                    >
                      ویرایش
                    </button>
                    <button
                      onClick={() => setDeletingSpeakerId(sp.id)}
                      className="text-xs font-bold text-red-600 hover:text-red-800 dark:text-red-400 p-1"
                    >
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* فایل‌های پیوست و فایل‌های زنده */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="bg-white dark:bg-slate-900 p-6 sm:p-8 rounded-3xl border border-gray-100 dark:border-slate-800 shadow-sm space-y-6 transition-colors">
          <div className="border-b border-gray-100 dark:border-slate-800 pb-4">
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">فایل‌های پیوست و نمایش زنده</h2>
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
              فایل‌های مشترک کل اتاق یا فایل‌های اختصاصی که فقط حین ارائه سخنران نمایش داده می‌شوند
            </p>
          </div>

          <form onSubmit={handleUploadFile} className="p-4 bg-gray-50 dark:bg-slate-800/60 rounded-2xl border border-gray-100 dark:border-slate-800 space-y-3">
            <input
              type="file"
              required
              onChange={(e) => setUploadFileObj(e.target.files?.[0] || null)}
              className="w-full text-xs text-gray-600 dark:text-slate-300 file:mr-0 file:ml-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-bold file:bg-blue-600 file:text-white hover:file:bg-blue-700 cursor-pointer"
            />
            <div className="flex gap-2">
              <select
                value={uploadSpeakerId}
                onChange={(e) => setUploadSpeakerId(e.target.value)}
                className="flex-1 px-3 py-1.5 text-xs bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded-xl text-gray-800 dark:text-slate-200"
              >
                <option value="">فایل مشترک (کل اتاق)</option>
                {room.speakers.filter((s) => s.name).map((s) => (
                  <option key={s.id} value={s.id}>
                    اختصاصی: {s.name}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={uploading || !uploadFileObj}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-xs disabled:opacity-50"
              >
                {uploading ? 'در حال آپلود…' : 'آپلود'}
              </button>
            </div>
          </form>

          <div className="space-y-2">
            {room.files.length === 0 ? (
              <p className="text-xs text-gray-400 dark:text-slate-500 text-center py-6">هیچ فایلی آپلود نشده است.</p>
            ) : (
              room.files.map((f) => (
                <div
                  key={f.id}
                  className="p-3 bg-gray-50/70 dark:bg-slate-800/40 hover:bg-gray-50 dark:hover:bg-slate-800 rounded-xl border border-gray-100 dark:border-slate-800 flex items-center justify-between text-xs"
                >
                  <div className="space-y-0.5">
                    <p className="font-bold text-gray-800 dark:text-slate-200 line-clamp-1">{f.filename}</p>
                    <span className="text-[11px] text-gray-400 dark:text-slate-500">
                      {f.upload_type === 'common' ? 'فایل مشترک' : `اختصاصی سخنران: ${f.speaker_name || '—'}`} ·{' '}
                      {formatBytes(f.size_bytes)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={`/api/rooms/${id}/files/${f.id}/download`}
                      className="text-blue-600 dark:text-blue-400 font-bold hover:underline"
                    >
                      دانلود
                    </a>
                    <button
                      onClick={() => handleDeleteFile(f.id)}
                      className="text-red-500 hover:text-red-700 font-bold"
                    >
                      حذف
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* آرشیو ضبط‌ها */}
        <div className="bg-white dark:bg-slate-900 p-6 sm:p-8 rounded-3xl border border-gray-100 dark:border-slate-800 shadow-sm space-y-6 transition-colors">
          <div className="border-b border-gray-100 dark:border-slate-800 pb-4">
            <h2 className="text-lg font-bold text-gray-900 dark:text-white">آرشیو ضبط‌های صدا</h2>
            <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">
              فایل‌های ضبط‌شده خودکار با نام استاندارد «نام اتاق - نام سخنران»
            </p>
          </div>

          <div className="space-y-3">
            {room.recordings.length === 0 ? (
              <div className="text-center py-10 space-y-2">
                <span className="text-3xl block">🎙</span>
                <p className="text-xs text-gray-400 dark:text-slate-500">
                  هنوز صدای ضبط‌شده‌ای در این اتاق ذخیره نشده است.
                </p>
              </div>
            ) : (
              room.recordings.map((rec) => (
                <div
                  key={rec.id}
                  className="p-4 bg-gray-50 dark:bg-slate-800/50 rounded-2xl border border-gray-100 dark:border-slate-800 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-gray-900 dark:text-white">{rec.filename}</h4>
                      <span className="text-[11px] text-gray-400 dark:text-slate-500">
                        سخنران: {rec.speaker_name} · حجم: {formatBytes(rec.size_bytes)}
                        {rec.duration_ms && ` · مدت: ${formatMs(rec.duration_ms)}`}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <a
                        href={`/api/rooms/${id}/files/${rec.id}/download`}
                        className="px-3 py-1 bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 font-bold text-xs rounded-lg hover:bg-blue-100"
                      >
                        دریافت
                      </a>
                      <button
                        onClick={() => handleDeleteFile(rec.id)}
                        className="text-red-500 hover:text-red-700 text-xs font-bold"
                      >
                        حذف
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* مودال ویرایش اسلات سخنران */}
      <Modal
        isOpen={Boolean(editingSpeaker)}
        onClose={() => setEditingSpeaker(null)}
        title="ویرایش مشخصات سخنران"
        maxWidth="max-w-md"
      >
        <form onSubmit={handleSaveSpeaker} className="space-y-4 text-right">
          <div>
            <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">نام و نام‌خانوادگی</label>
            <input
              type="text"
              required
              value={speakerForm.name}
              onChange={(e) => setSpeakerForm({ ...speakerForm, name: e.target.value })}
              className="w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 outline-none text-sm"
              placeholder="مثال: دکتر احمد حسینی"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">جنسیت</label>
              <select
                value={speakerForm.gender}
                onChange={(e) => setSpeakerForm({ ...speakerForm, gender: e.target.value })}
                className="w-full px-3 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl text-xs font-medium"
              >
                <option value="">نامشخص</option>
                <option value="male">مرد</option>
                <option value="female">زن</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">سن</label>
              <input
                type="number"
                min={1}
                max={120}
                value={speakerForm.age}
                onChange={(e) => setSpeakerForm({ ...speakerForm, age: e.target.value })}
                className="w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">مدت زمان اختصاصی (ثانیه)</label>
            <input
              type="number"
              min={10}
              max={86400}
              value={speakerForm.speaking_seconds}
              onChange={(e) =>
                setSpeakerForm({ ...speakerForm, speaking_seconds: parseInt(e.target.value, 10) || 300 })
              }
              className="w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl text-sm"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">عنوان یا چکیدهٔ سخنرانی</label>
            <textarea
              rows={2}
              value={speakerForm.description}
              onChange={(e) => setSpeakerForm({ ...speakerForm, description: e.target.value })}
              className="w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl text-sm"
              placeholder="موضوع ارائه و نکات کلیدی"
            />
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={() => setEditingSpeaker(null)}
              className="px-4 py-2 border border-gray-200 dark:border-slate-700 rounded-xl text-xs font-bold text-gray-600 dark:text-slate-300"
            >
              انصراف
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-xs"
            >
              ذخیره تغییرات
            </button>
          </div>
        </form>
      </Modal>

      {/* تأیید حذف سخنران */}
      <ConfirmDialog
        isOpen={Boolean(deletingSpeakerId)}
        onClose={() => setDeletingSpeakerId(null)}
        onConfirm={handleDeleteSpeaker}
        title="حذف سخنران"
        message="آیا از حذف این سخنران مطمئن هستید؟ در صورت وجود فایل‌های اختصاصی، آن‌ها نیز پاک خواهند شد."
        confirmText="بله، حذف شود"
      />

      {/* کد QR صفحه تماشاگران */}
      {room.public_token && (
        <QrModal
          isOpen={showQr}
          onClose={() => setShowQr(false)}
          token={room.public_token}
          roomName={room.name}
        />
      )}
    </div>
  );
};
