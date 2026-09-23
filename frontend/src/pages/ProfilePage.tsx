import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import { formatBytes, formatDate } from '../utils/formatters';

export const ProfilePage: React.FC = () => {
  const { user, refreshUser } = useAuth();

  const [accountName, setAccountName] = useState(user?.account_name || '');
  const [job, setJob] = useState(user?.job || '');
  const [age, setAge] = useState(user?.age ? String(user.age) : '');
  const [timezone, setTimezone] = useState(user?.timezone || 'Asia/Tehran');
  const [calendar, setCalendar] = useState<'jalali' | 'gregorian'>(user?.calendar || 'jalali');

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [profileMsg, setProfileMsg] = useState({ type: '', text: '' });
  const [passwordMsg, setPasswordMsg] = useState({ type: '', text: '' });
  const [loadingProfile, setLoadingProfile] = useState(false);
  const [loadingPassword, setLoadingPassword] = useState(false);

  if (!user) return null;

  const handleUpdateProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileMsg({ type: '', text: '' });
    setLoadingProfile(true);
    try {
      await api.post('/api/auth/profile', {
        account_name: accountName,
        job,
        age: age ? parseInt(age, 10) : null,
        timezone,
        calendar,
      });
      await refreshUser();
      setProfileMsg({ type: 'success', text: 'اطلاعات پروفایل با موفقیت ذخیره شد.' });
    } catch (err: any) {
      setProfileMsg({ type: 'error', text: err.message || 'خطا در ذخیره پروفایل.' });
    } finally {
      setLoadingProfile(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordMsg({ type: '', text: '' });
    setLoadingPassword(true);
    try {
      await api.post('/api/auth/change-password', {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword('');
      setNewPassword('');
      setPasswordMsg({ type: 'success', text: 'رمز عبور با موفقیت به‌روزرسانی شد.' });
    } catch (err: any) {
      setPasswordMsg({ type: 'error', text: err.message || 'خطا در تغییر رمز عبور.' });
    } finally {
      setLoadingPassword(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      <div className="flex items-center justify-between border-b border-gray-100 pb-4">
        <div>
          <h1 className="text-2xl font-black text-gray-900">پروفایل کاربری</h1>
          <p className="text-sm text-gray-500 mt-1">مشاهده و ویرایش مشخصات حساب کاربری و تنظیمات سامانه</p>
        </div>
        <div className="text-left bg-blue-50 border border-blue-100 px-4 py-2 rounded-2xl">
          <span className="text-xs text-blue-600 block font-bold">مصرف کل فضای شما:</span>
          <span className="text-base font-black text-blue-900">{formatBytes(user.storage_used_bytes)}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* مشخصات کاربری */}
        <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-4">
          <h2 className="text-lg font-bold text-gray-800 border-b border-gray-100 pb-3">اطلاعات فردی و منطقه زمانی</h2>

          {profileMsg.text && (
            <div
              className={`p-3 text-xs font-bold rounded-xl ${
                profileMsg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
              }`}
            >
              {profileMsg.text}
            </div>
          )}

          <form onSubmit={handleUpdateProfile} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-gray-500 mb-1">نام کاربری (غیرقابل تغییر)</label>
              <input
                type="text"
                disabled
                value={user.username}
                dir="ltr"
                className="w-full px-4 py-2.5 bg-gray-100 border border-gray-200 rounded-xl text-gray-500 text-sm font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">نام و نام خانوادگی</label>
              <input
                type="text"
                value={accountName}
                onChange={(e) => setAccountName(e.target.value)}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">سمت / شغل</label>
                <input
                  type="text"
                  value={job}
                  onChange={(e) => setJob(e.target.value)}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                />
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">سن</label>
                <input
                  type="number"
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">تقویم</label>
                <select
                  value={calendar}
                  onChange={(e) => setCalendar(e.target.value as any)}
                  className="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-xs font-medium"
                >
                  <option value="jalali">هجری شمسی</option>
                  <option value="gregorian">میلادی</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">منطقه زمانی</label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-xs font-medium"
                  dir="ltr"
                >
                  <option value="Asia/Tehran">Asia/Tehran</option>
                  <option value="UTC">UTC</option>
                  <option value="Europe/London">Europe/London</option>
                  <option value="America/New_York">America/New_York</option>
                </select>
              </div>
            </div>

            <button
              type="submit"
              disabled={loadingProfile}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-md shadow-blue-600/20 transition-all text-sm mt-2"
            >
              {loadingProfile ? 'در حال ذخیره…' : 'ذخیره تغییرات'}
            </button>
          </form>
        </div>

        {/* تغییر رمز عبور */}
        <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <h2 className="text-lg font-bold text-gray-800 border-b border-gray-100 pb-3">امنیت و تغییر رمز عبور</h2>

            {passwordMsg.text && (
              <div
                className={`p-3 text-xs font-bold rounded-xl ${
                  passwordMsg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                }`}
              >
                {passwordMsg.text}
              </div>
            )}

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">رمز عبور فعلی</label>
                <input
                  type="password"
                  required
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                  dir="ltr"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">رمز عبور جدید</label>
                <input
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                  placeholder="حداقل ۸ کاراکتر"
                  dir="ltr"
                />
              </div>

              <button
                type="submit"
                disabled={loadingPassword}
                className="w-full py-2.5 bg-gray-800 hover:bg-black text-white font-bold rounded-xl shadow-md transition-all text-sm mt-4"
              >
                {loadingPassword ? 'در حال تغییر…' : 'تغییر رمز عبور'}
              </button>
            </form>
          </div>

          <div className="pt-4 border-t border-gray-100 text-xs text-gray-400">
            تاریخ عضویت: {formatDate(user.created_at_ms, user.calendar, user.timezone)}
          </div>
        </div>
      </div>
    </div>
  );
};
