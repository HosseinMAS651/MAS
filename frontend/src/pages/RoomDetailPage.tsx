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
    return <div className="text-center py-24 text-gray-400 font-bold">در حال دریافت اطلاعات اتاق…</div>;
  }
  if (error || !room) {
    return <div className="p-8 text-center text-red-600 font-bold">{error || 'اتاق یافت نشد.'}</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* سربرگ اتاق */}
      <div className="bg-white p-6 sm:p-8 rounded-3xl border border-gray-100 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-black text-gray-900">{room.name}</h1>
            <span className="px-3 py-1 bg-blue-50 text-blue-700 text-xs font-bold rounded-xl">
              ظرفیت {room.capacity} نفر
            </span>
          </div>
          {room.description && <p className="text-sm text-gray-500 max-w-2xl">{room.description}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
          <Link
            to={`/rooms/${room.id}/play`}
            className="flex-1 md:flex-none px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-2xl shadow-lg shadow-blue-600/20 transition-all text-center text-sm"
          >
            ورود به اتاق پخش ▷
          </Link>
          <button
            onClick={() => setShowQr(true)}
            className="px-4 py-3 bg-emerald-50 hover:bg-emerald-100 text-emerald-800 font-bold rounded-2xl transition-all text-sm flex items-center gap-1.5"
          >
            <span>📱</span> لینک تماشاگر و QR
          </button>
          <Link
            to={`/rooms/${room.id}/edit`}
            className="px-4 py-3 bg-gray-50 hover:bg-gray-100 text-gray-700 font-bold rounded-2xl transition-all text-sm"
          >
            ⚙ تنظیمات
          </Link>
        </div>
      </div>

      {/* بخش سخنرانان */}
      <div className="bg-white p-6 sm:p-8 rounded-3xl border border-gray-100 shadow-sm space-y-6">
        <div className="flex items-center justify-between border-b border-gray-100 pb-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900">لیست و نوبت سخنرانان</h2>
            <p className="text-xs text-gray-500 mt-1">مشخصات، زمان هر فرد و وضعیت فریز/اتمام سخنرانی</p>
          </div>
          <span className="text-xs font-bold text-gray-500 bg-gray-50 px-3 py-1.5 rounded-xl border border-gray-100">
            {room.active_speaker_count} سخنران نام‌گذاری‌شده
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-right border-collapse">
            <thead>
              <tr className="border-b border-gray-100 text-xs font-bold text-gray-400">
                <th className="pb-3 px-3">ردیف</th>
                <th className="pb-3 px-3">نام سخنران</th>
                <th className="pb-3 px-3">جنسیت / سن</th>
                <th className="pb-3 px-3">مدت زمان مجاز</th>
                <th className="pb-3 px-3">زمان مصرف‌شده</th>
                <th className="pb-3 px-3">وضعیت</th>
                <th className="pb-3 px-3 text-center">عملیات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 text-sm">
              {room.speakers.map((sp, idx) => (
                <tr key={sp.id} className="hover:bg-blue-50/20 transition-colors">
                  <td className="py-3 px-3 text-xs font-bold text-gray-400">{idx + 1}</td>
                  <td className="py-3 px-3 font-bold text-gray-800">
                    {sp.name ? sp.name : <span className="text-gray-300 font-normal">اسلات خالی</span>}
                  </td>
                  <td className="py-3 px-3 text-xs text-gray-500">
                    {[
                      sp.gender === 'male' ? 'مرد' : sp.gender === 'female' ? 'زن' : '',
                      sp.age ? `${sp.age} سال` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </td>
                  <td className="py-3 px-3 text-xs font-mono text-gray-700">
                    {Math.floor(sp.speaking_seconds / 60)} دقیقه ({sp.speaking_seconds}s)
                  </td>
                  <td className="py-3 px-3 text-xs font-mono text-gray-700">
                    {formatMs(sp.elapsed_ms)}
                    {sp.overtime_ms > 0 && <span className="text-amber-600 mr-1">+{formatMs(sp.overtime_ms)}</span>}
                  </td>
                  <td className="py-3 px-3">
                    {sp.is_finished ? (
                      <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-md text-[11px] font-bold">
                        فریز / پایان
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded-md text-[11px] font-bold">
                        آماده
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-center space-x-2 space-x-reverse">
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
                      className="text-xs font-bold text-blue-600 hover:text-blue-800 p-1"
                    >
                      ویرایش
                    </button>
                    <button
                      onClick={() => setDeletingSpeakerId(sp.id)}
                      className="text-xs font-bold text-red-600 hover:text-red-800 p-1"
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

      {/* بخش فایل‌ها و ضبط‌های صوتی */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* فایل‌های نمایش زنده و پیوست */}
        <div className="bg-white p-6 sm:p-8 rounded-3xl border border-gray-100 shadow-sm space-y-6">
          <div className="border-b border-gray-100 pb-4">
            <h2 className="text-lg font-bold text-gray-900">فایل‌های پیوست و نمایش زنده</h2>
            <p className="text-xs text-gray-500 mt-1">فایل‌های PDF، اسلایدها و صوت‌های مشترک یا اختصاصی سخنران</p>
          </div>

          <form onSubmit={handleUploadFile} className="p-4 bg-gray-50 rounded-2xl border border-gray-100 space-y-3">
            <input
              type="file"
              required
              onChange={(e) => setUploadFileObj(e.target.files?.[0] || null)}
              className="w-full text-xs text-gray-600 file:mr-0 file:ml-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-bold file:bg-blue-600 file:text-white hover:file:bg-blue-700 cursor-pointer"
            />
            <div className="flex gap-2">
              <select
                value={uploadSpeakerId}
                onChange={(e) => setUploadSpeakerId(e.target.value)}
                className="flex-1 px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-xl"
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
                {uploading ? 'در حال آپلود…' : 'آپلود فایل'}
              </button>
            </div>
          </form>

          <div className="space-y-2">
            {room.files.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-6">هنوز فایلی آپلود نشده است.</p>
            ) : (
              room.files.map((f) => (
                <div
                  key={f.id}
                  className="p-3 bg-gray-50/70 hover:bg-gray-50 rounded-xl border border-gray-100 flex items-center justify-between text-xs"
                >
                  <div className="space-y-0.5">
                    <p className="font-bold text-gray-800 line-clamp-1">{f.filename}</p>
                    <span className="text-[11px] text-gray-400">
                      {f.upload_type === 'common' ? 'فایل مشترک' : `سخنران: ${f.speaker_name || 'اختصاصی'}`} ·{' '}
                      {formatBytes(f.size_bytes)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={`/api/rooms/${room.id}/files/${f.id}/download`}
                      download
                      className="text-blue-600 hover:underline font-bold"
                    >
                      دانلود
                    </a>
                    <button
                      onClick={() => handleDeleteFile(f.id)}
                      className="text-red-600 hover:underline font-bold"
                    >
                      حذف
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* آرشیو ضبط‌های صوتی */}
        <div className="bg-white p-6 sm:p-8 rounded-3xl border border-gray-100 shadow-sm space-y-6">
          <div className="border-b border-gray-100 pb-4">
            <h2 className="text-lg font-bold text-gray-900">آرشیو ضبط‌های صدا</h2>
            <p className="text-xs text-gray-500 mt-1">
              فایل‌های ضبط‌شده خودکار با نام استاندارد «نام اتاق - نام سخنران»
            </p>
          </div>

          <div className="space-y-3">
            {room.recordings.length === 0 ? (
              <div className="text-center py-10 space-y-2">
                <span className="text-3xl block">🎙</span>
                <p className="text-xs text-gray-400">هنوز فایلی برای این اتاق ضبط نشده است.</p>
                <p className="text-[11px] text-gray-400">
                  با شروع تایمر در صفحهٔ پخش، صدای سخنران به صورت خودکار ضبط خواهد شد.
                </p>
              </div>
            ) : (
              room.recordings.map((rec) => (
                <div
                  key={rec.id}
                  className="p-4 bg-gray-50 rounded-2xl border border-gray-100 space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="text-xs font-bold text-gray-900">{rec.filename}</h4>
                      <span className="text-[11px] text-gray-400">
                        سخنران: {rec.speaker_name} · حجم: {formatBytes(rec.size_bytes)}
                        {rec.duration_ms && ` · مدت: ${formatMs(rec.duration_ms)}`}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <a
                        href={`/api/rooms/${room.id}/files/${rec.id}/download`}
                        download={rec.filename}
                        className="px-3 py-1 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-bold rounded-lg"
                      >
                        دانلود فایل
                      </a>
                      <button
                        onClick={() => handleDeleteFile(rec.id)}
                        className="text-red-500 hover:text-red-700 text-xs font-bold"
                      >
                        حذف
                      </button>
                    </div>
                  </div>

                  <audio
                    controls
                    preload="none"
                    src={`/api/rooms/${room.id}/files/${rec.id}/download`}
                    className="w-full h-8 pt-1"
                  />
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* مودال ویرایش سخنران */}
      <Modal isOpen={Boolean(editingSpeaker)} onClose={() => setEditingSpeaker(null)} title="ویرایش اسلات سخنران">
        <form onSubmit={handleSaveSpeaker} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1">نام و نام خانوادگی سخنران</label>
            <input
              type="text"
              value={speakerForm.name}
              onChange={(e) => setSpeakerForm({ ...speakerForm, name: e.target.value })}
              className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              placeholder="مثال: دکتر احمد حسینی"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">جنسیت</label>
              <select
                value={speakerForm.gender}
                onChange={(e) => setSpeakerForm({ ...speakerForm, gender: e.target.value })}
                className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-xl text-xs font-medium"
              >
                <option value="">نامشخص</option>
                <option value="male">مرد</option>
                <option value="female">زن</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">سن</label>
              <input
                type="number"
                value={speakerForm.age}
                onChange={(e) => setSpeakerForm({ ...speakerForm, age: e.target.value })}
                className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1">مدت زمان اختصاصی (ثانیه)</label>
            <input
              type="number"
              min={10}
              max={86400}
              value={speakerForm.speaking_seconds}
              onChange={(e) =>
                setSpeakerForm({ ...speakerForm, speaking_seconds: parseInt(e.target.value, 10) || 300 })
              }
              className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-sm"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1">عنوان یا چکیدهٔ سخنرانی</label>
            <textarea
              rows={2}
              value={speakerForm.description}
              onChange={(e) => setSpeakerForm({ ...speakerForm, description: e.target.value })}
              className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-sm"
              placeholder="موضوع ارائه و نکات کلیدی"
            />
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={() => setEditingSpeaker(null)}
              className="px-4 py-2 border border-gray-200 rounded-xl text-xs font-bold text-gray-600"
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

      {/* تأییدیه حذف سخنران */}
      <ConfirmDialog
        isOpen={Boolean(deletingSpeakerId)}
        onClose={() => setDeletingSpeakerId(null)}
        onConfirm={handleDeleteSpeaker}
        title="حذف سخنران"
        message="آیا از حذف این سخنران اطمینان دارید؟ با حذف سخنران، نوبت سایر سخنرانان به صورت خودکار بازشماری خواهد شد."
        confirmText="حذف قطعی"
      />

      {/* مودال QR کد */}
      {showQr && (
        <QrModal
          isOpen={true}
          onClose={() => setShowQr(false)}
          roomName={room.name}
          publicToken={room.public_token}
        />
      )}
    </div>
  );
};
