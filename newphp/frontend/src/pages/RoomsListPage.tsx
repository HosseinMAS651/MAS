import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { RoomSummary } from '../types';
import { formatBytes } from '../utils/formatters';
import { Modal } from '../components/Modal';
import { QrModal } from '../components/QrModal';

export const RoomsListPage: React.FC = () => {
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // مودال ایجاد اتاق
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: '',
    capacity: 10,
    description: '',
    recording_enabled: true,
    live_files_enabled: true,
    timing_mode: 'global',
    global_seconds: 300,
    order_mode: 'manual',
  });
  const [creating, setCreating] = useState(false);

  // مودال QR
  const [qrModalRoom, setQrModalRoom] = useState<{ name: string; token: string } | null>(null);

  const fetchRooms = async () => {
    try {
      const data = await api.get('/api/rooms');
      setRooms(data.rooms || []);
    } catch (err: any) {
      setError(err.message || 'خطا در دریافت لیست اتاق‌ها.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRooms();
  }, []);

  const handleCreateRoom = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    try {
      await api.post('/api/rooms', createForm);
      setShowCreateModal(false);
      setCreateForm({
        name: '',
        capacity: 10,
        description: '',
        recording_enabled: true,
        live_files_enabled: true,
        timing_mode: 'global',
        global_seconds: 300,
        order_mode: 'manual',
      });
      await fetchRooms();
    } catch (err: any) {
      alert(err.message || 'خطا در ساخت اتاق.');
    } finally {
      setCreating(false);
    }
  };

  const openQrForRoom = async (roomId: number, roomName: string) => {
    try {
      const res = await api.get(`/api/rooms/${roomId}`);
      if (!res.room?.public_enabled || !res.room?.public_token) {
        alert('ابتدا دسترسی عمومی اتاق را از بخش تنظیمات فعال کنید.');
        return;
      }
      setQrModalRoom({ name: roomName, token: res.room.public_token });
    } catch (err: any) {
      alert(err.message || 'خطا در باز کردن لینک عمومی.');
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-gray-100 dark:border-slate-800 pb-6 transition-colors">
        <div>
          <h1 className="text-3xl font-black text-gray-900 dark:text-white tracking-tight">اتاق‌های سخنرانی من</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">مدیریت، زمان‌بندی و برگزاری جلسات و همایش‌ها</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="px-5 py-3 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-2xl shadow-lg shadow-blue-600/25 transition-all flex items-center gap-2 hover:-translate-y-0.5 active:translate-y-0 text-sm"
        >
          <span className="text-lg">+</span>
          ایجاد اتاق جدید
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm font-medium rounded-2xl">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-20 text-gray-400 dark:text-slate-500 font-bold">در حال بارگذاری اطلاعات اتاق‌ها…</div>
      ) : rooms.length === 0 ? (
        <div className="text-center py-20 bg-white dark:bg-slate-900 rounded-3xl border-2 border-dashed border-gray-200 dark:border-slate-800 space-y-4 transition-colors">
          <div className="w-16 h-16 bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 rounded-2xl flex items-center justify-center text-3xl mx-auto font-black">
            🎙
          </div>
          <h3 className="text-lg font-bold text-gray-800 dark:text-slate-200">هنوز اتاقی نساخته‌اید</h3>
          <p className="text-sm text-gray-500 dark:text-slate-400 max-w-sm mx-auto">
            برای شروع زمان‌بندی سخنرانی‌ها و دسترسی به امکاناتی چون ضبط خودکار صدا و لینک تماشاگران، اولین اتاق خود را بسازید.
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-sm transition-all"
          >
            ایجاد اولین اتاق
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {rooms.map((r) => (
            <div
              key={r.id}
              className="bg-white dark:bg-slate-900 rounded-3xl border border-gray-100 dark:border-slate-800 shadow-sm hover:shadow-xl hover:shadow-blue-900/5 transition-all p-6 flex flex-col justify-between group"
            >
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-xl font-bold text-gray-900 dark:text-white group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-1">
                    {r.name}
                  </h2>
                  <span className="px-2.5 py-1 bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-300 text-xs font-bold rounded-lg whitespace-nowrap">
                    ظرفیت {r.capacity} نفر
                  </span>
                </div>

                {r.description && (
                  <p className="text-xs text-gray-500 dark:text-slate-400 line-clamp-2 leading-relaxed">{r.description}</p>
                )}

                <div className="flex flex-wrap gap-2 pt-1">
                  {r.recording_enabled && (
                    <span className="px-2.5 py-0.5 bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-300 text-[11px] font-bold rounded-md flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
                      ضبط خودکار
                    </span>
                  )}
                  {r.live_files_enabled && (
                    <span className="px-2.5 py-0.5 bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-300 text-[11px] font-bold rounded-md">
                      فایل زنده
                    </span>
                  )}
                  {r.public_enabled && (
                    <span className="px-2.5 py-0.5 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 text-[11px] font-bold rounded-md flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                      تماشاگر فعال
                    </span>
                  )}
                </div>

                <div className="bg-gray-50/70 dark:bg-slate-800/60 p-3 rounded-2xl flex items-center justify-between text-xs text-gray-500 dark:text-slate-400">
                  <span>سخنرانان ثبت‌شده: <b className="text-gray-800 dark:text-slate-200">{r.active_speaker_count}</b> از {r.capacity}</span>
                  <span>حجم فایل‌ها: <b className="text-gray-800 dark:text-slate-200">{formatBytes(r.storage_used_bytes)}</b></span>
                </div>
              </div>

              <div className="pt-6 border-t border-gray-100 dark:border-slate-800 mt-6 space-y-2">
                <Link
                  to={`/rooms/${r.id}/play`}
                  className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-center block text-sm shadow-md shadow-blue-600/20 transition-all hover:-translate-y-0.5"
                >
                  ورود به اتاق پخش و تایمر ▷
                </Link>

                <div className="grid grid-cols-3 gap-2">
                  <Link
                    to={`/rooms/${r.id}`}
                    className="py-2 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-200 font-bold rounded-xl text-center text-xs transition-colors"
                  >
                    سخنران‌ها
                  </Link>
                  <Link
                    to={`/rooms/${r.id}/edit`}
                    className="py-2 bg-gray-50 dark:bg-slate-800 hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-700 dark:text-slate-200 font-bold rounded-xl text-center text-xs transition-colors"
                  >
                    تنظیمات
                  </Link>
                  <button
                    onClick={() => openQrForRoom(r.id, r.name)}
                    className="py-2 bg-gray-50 dark:bg-slate-800 hover:bg-blue-50 dark:hover:bg-blue-950/40 text-blue-600 dark:text-blue-400 font-bold rounded-xl text-center text-xs transition-colors"
                  >
                    کیوآرکد QR
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* مودال ساخت اتاق جدید */}
      <Modal isOpen={showCreateModal} onClose={() => setShowCreateModal(false)} title="ایجاد اتاق سخنرانی جدید">
        <form onSubmit={handleCreateRoom} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">
              نام اتاق <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={createForm.name}
              onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
              className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              placeholder="مثال: کنفرانس سالانه هوش مصنوعی"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">ظرفیت سخنرانان (نفر)</label>
              <input
                type="number"
                min={1}
                max={100}
                required
                value={createForm.capacity}
                onChange={(e) => setCreateForm({ ...createForm, capacity: parseInt(e.target.value, 10) || 1 })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">زمان پیش‌فرض هر سخنران (دقیقه)</label>
              <input
                type="number"
                min={1}
                max={1440}
                value={Math.floor(createForm.global_seconds / 60)}
                onChange={(e) => setCreateForm({ ...createForm, global_seconds: (parseInt(e.target.value, 10) || 5) * 60 })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1">توضیحات اتاق (اختیاری)</label>
            <textarea
              rows={2}
              value={createForm.description}
              onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
              className="w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              placeholder="موضوع همایش، مخاطبان یا نکات اجرایی"
            />
          </div>

          <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-slate-800">
            <label className="flex items-center gap-2 cursor-pointer text-xs font-bold text-gray-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={createForm.recording_enabled}
                onChange={(e) => setCreateForm({ ...createForm, recording_enabled: e.target.checked })}
                className="w-4 h-4 text-blue-600 rounded"
              />
              فعال‌سازی ضبط خودکار صدای سخنرانان در زمان اجرای تایمر
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-xs font-bold text-gray-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={createForm.live_files_enabled}
                onChange={(e) => setCreateForm({ ...createForm, live_files_enabled: e.target.checked })}
                className="w-4 h-4 text-blue-600 rounded"
              />
              امکان نمایش زنده فایل‌ها در صفحه پخش و تماشاگران
            </label>
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={() => setShowCreateModal(false)}
              className="px-4 py-2.5 border border-gray-200 dark:border-slate-700 rounded-xl text-sm font-bold text-gray-600 dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-800"
            >
              انصراف
            </button>
            <button
              type="submit"
              disabled={creating}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-sm shadow-md shadow-blue-600/20 transition-all"
            >
              {creating ? 'در حال ساخت…' : 'ایجاد اتاق'}
            </button>
          </div>
        </form>
      </Modal>

      {/* مودال QR کد */}
      {qrModalRoom && (
        <QrModal
          isOpen={true}
          onClose={() => setQrModalRoom(null)}
          roomName={qrModalRoom.name}
          publicToken={qrModalRoom.token}
        />
      )}
    </div>
  );
};
