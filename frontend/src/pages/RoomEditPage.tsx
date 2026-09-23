import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { api } from '../api/client';
import { RoomDetail } from '../types';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Modal } from '../components/Modal';

export const RoomEditPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    name: '',
    capacity: 10,
    description: '',
    recording_enabled: false,
    live_files_enabled: false,
    public_enabled: false,
    timing_mode: 'global',
    global_seconds: 300,
    order_mode: 'manual',
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // مودال تأیید کاهش ظرفیت (C-04)
  const [showShrinkModal, setShowShrinkModal] = useState(false);
  const [shrinkMsg, setShrinkMsg] = useState('');

  // مودال تأیید حذف اتاق (C-07)
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  useEffect(() => {
    const fetchRoom = async () => {
      try {
        const data = await api.get(`/api/rooms/${id}`);
        const r: RoomDetail = data.room;
        setForm({
          name: r.name,
          capacity: r.capacity,
          description: r.description,
          recording_enabled: r.recording_enabled,
          live_files_enabled: r.live_files_enabled,
          public_enabled: r.public_enabled,
          timing_mode: r.timing_mode,
          global_seconds: r.global_seconds,
          order_mode: r.order_mode,
        });
      } catch (err: any) {
        setError(err.message || 'خطا در بارگذاری اطلاعات اتاق.');
      } finally {
        setLoading(false);
      }
    };
    fetchRoom();
  }, [id]);

  const handleSubmit = async (e: React.FormEvent, confirmShrink = false) => {
    if (e) e.preventDefault();
    setSaving(true);
    setError('');
    setSuccess('');

    try {
      await api.put(`/api/rooms/${id}`, {
        ...form,
        confirm_shrink: confirmShrink,
      });
      setSuccess('تنظیمات اتاق با موفقیت ذخیره شد.');
      setShowShrinkModal(false);
    } catch (err: any) {
      if (err.code === 'CONFIRM_CAPACITY_SHRINK_REQUIRED') {
        setShrinkMsg(err.message);
        setShowShrinkModal(true);
      } else {
        setError(err.message || 'خطا در ذخیره تغییرات.');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteRoom = async () => {
    try {
      await api.delete(`/api/rooms/${id}`);
      navigate('/rooms');
    } catch (err: any) {
      alert(err.message || 'خطا در حذف اتاق.');
    }
  };

  if (loading) {
    return <div className="text-center py-24 text-gray-400 font-bold">در حال بارگذاری فرم…</div>;
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div className="flex items-center justify-between border-b border-gray-100 pb-4">
        <div>
          <h1 className="text-2xl font-black text-gray-900">تنظیمات و مشخصات اتاق</h1>
          <p className="text-sm text-gray-500 mt-1">ویرایش پارامترهای زمان‌بندی، ظرفیت و امکانات پخش</p>
        </div>
        <Link to={`/rooms/${id}`} className="text-xs font-bold text-blue-600 hover:underline">
          ← بازگشت به جزئیات اتاق
        </Link>
      </div>

      {error && <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm font-medium rounded-2xl">{error}</div>}
      {success && <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm font-medium rounded-2xl">{success}</div>}

      <form onSubmit={(e) => handleSubmit(e, false)} className="bg-white p-6 sm:p-8 rounded-3xl border border-gray-100 shadow-sm space-y-6">
        <div>
          <label className="block text-xs font-bold text-gray-700 mb-1.5">نام اتاق</label>
          <input
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1.5">ظرفیت سخنرانان (نفر)</label>
            <input
              type="number"
              min={1}
              max={100}
              required
              value={form.capacity}
              onChange={(e) => setForm({ ...form, capacity: parseInt(e.target.value, 10) || 1 })}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
            />
            <span className="text-[11px] text-gray-400 mt-1 block">حداقل ۱ و حداکثر ۱۰۰ نفر</span>
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1.5">زمان پیش‌فرض سخنرانی (دقیقه)</label>
            <input
              type="number"
              min={1}
              max={1440}
              value={Math.floor(form.global_seconds / 60)}
              onChange={(e) => setForm({ ...form, global_seconds: (parseInt(e.target.value, 10) || 5) * 60 })}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-bold text-gray-700 mb-1.5">نحوه زمان‌بندی</label>
          <select
            value={form.timing_mode}
            onChange={(e) => setForm({ ...form, timing_mode: e.target.value })}
            className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm font-medium"
          >
            <option value="global">زمان یکسان برای همهٔ سخنرانان (بر اساس زمان پیش‌فرض بالا)</option>
            <option value="individual">زمان مستقل و متغیر برای هر سخنران</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-bold text-gray-700 mb-1.5">نحوه مرتب‌سازی سخنرانان</label>
          <select
            value={form.order_mode}
            onChange={(e) => setForm({ ...form, order_mode: e.target.value })}
            className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm font-medium"
          >
            <option value="manual">دستی (بر اساس ترتیبی که در جدول می‌چینید)</option>
            <option value="alpha">الفبایی (بر اساس نام خانوادگی/نام)</option>
            <option value="age">بر اساس سن (از بزرگ‌تر به کوچک‌تر)</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-bold text-gray-700 mb-1.5">توضیحات و یادداشت‌های اتاق</label>
          <textarea
            rows={3}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="w-full px-4 py-2 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
          />
        </div>

        <div className="space-y-3 pt-4 border-t border-gray-100">
          <label className="flex items-center gap-2.5 cursor-pointer text-sm font-bold text-gray-800">
            <input
              type="checkbox"
              checked={form.recording_enabled}
              onChange={(e) => setForm({ ...form, recording_enabled: e.target.checked })}
              className="w-4 h-4 text-blue-600 rounded"
            />
            فعال بودن ضبط خودکار صدا در زمان حرکت تایمر
          </label>

          <label className="flex items-center gap-2.5 cursor-pointer text-sm font-bold text-gray-800">
            <input
              type="checkbox"
              checked={form.live_files_enabled}
              onChange={(e) => setForm({ ...form, live_files_enabled: e.target.checked })}
              className="w-4 h-4 text-blue-600 rounded"
            />
            امکان نمایش فایل‌های زنده برای تماشاگران
          </label>

          <label className="flex items-center gap-2.5 cursor-pointer text-sm font-bold text-gray-800">
            <input
              type="checkbox"
              checked={form.public_enabled}
              onChange={(e) => setForm({ ...form, public_enabled: e.target.checked })}
              className="w-4 h-4 text-blue-600 rounded"
            />
            فعال بودن لینک تماشاگر عمومی و کیوآرکد (بدون نیاز به لاگین)
          </label>
        </div>

        <div className="flex justify-between items-center pt-6 border-t border-gray-100">
          <button
            type="button"
            onClick={() => setShowDeleteModal(true)}
            className="px-4 py-2.5 text-xs font-bold text-red-600 hover:bg-red-50 rounded-xl transition-colors"
          >
            حذف کامل این اتاق…
          </button>

          <div className="flex gap-3">
            <Link
              to={`/rooms/${id}`}
              className="px-5 py-2.5 border border-gray-200 rounded-xl text-sm font-bold text-gray-600 hover:bg-gray-50 transition-colors"
            >
              انصراف
            </Link>
            <button
              type="submit"
              disabled={saving}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl text-sm shadow-md shadow-blue-600/20 transition-all"
            >
              {saving ? 'در حال ذخیره…' : 'ذخیره تغییرات'}
            </button>
          </div>
        </div>
      </form>

      {/* تأیید کاهش ظرفیت (باگ C-04) */}
      <ConfirmDialog
        isOpen={showShrinkModal}
        onClose={() => setShowShrinkModal(false)}
        onConfirm={() => handleSubmit(null as any, true)}
        title="هشدار کاهش ظرفیت اتاق"
        message={shrinkMsg || 'کاهش ظرفیت منجر به حذف اسلات‌های انتهایی می‌شود. آیا مایل به ادامه هستید؟'}
        confirmText="تأیید و کاهش ظرفیت"
      />

      {/* تأیید حذف اتاق (باگ C-07) */}
      <ConfirmDialog
        isOpen={showDeleteModal}
        onClose={() => setShowDeleteModal(false)}
        onConfirm={handleDeleteRoom}
        title="حذف کامل اتاق"
        message="آیا از حذف این اتاق اطمینان قطعی دارید؟ تمام فایل‌ها، ضبط‌ها و اطلاعات سخنرانان برای همیشه پاک خواهند شد."
        confirmText="حذف قطعی اتاق"
      />
    </div>
  );
};
