import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const RegisterPage: React.FC = () => {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    username: '',
    password: '',
    account_name: '',
    age: '',
    job: '',
    timezone: 'Asia/Tehran',
    calendar: 'jalali',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await register({
        ...form,
        age: form.age ? parseInt(form.age, 10) : null,
      });
      navigate('/rooms');
    } catch (err: any) {
      setError(err.message || 'خطا در ثبت‌نام. لطفاً اطلاعات را بررسی کنید.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-gradient-to-b from-blue-50/50 to-white">
      <div className="max-w-lg w-full bg-white rounded-3xl shadow-xl shadow-blue-900/5 border border-gray-100 p-8 space-y-6">
        <div className="text-center space-y-2">
          <div className="w-14 h-14 bg-blue-600 text-white rounded-2xl flex items-center justify-center text-2xl font-black mx-auto shadow-lg shadow-blue-600/30">
            مـاس
          </div>
          <h2 className="text-2xl font-black text-gray-900">ساخت حساب کاربری جدید</h2>
          <p className="text-sm text-gray-500">برای شروع مدیریت زمان‌بندی سخنرانی‌ها ثبت‌نام کنید</p>
        </div>

        {error && (
          <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm font-medium rounded-2xl">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">
                نام کاربری <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="حداقل ۳ کاراکتر"
                dir="ltr"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">
                رمز عبور <span className="text-red-500">*</span>
              </label>
              <input
                type="password"
                required
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="حداقل ۸ کاراکتر"
                dir="ltr"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">نام و نام خانوادگی</label>
              <input
                type="text"
                value={form.account_name}
                onChange={(e) => setForm({ ...form, account_name: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="مثال: علی رضایی"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">شغل یا سمت</label>
              <input
                type="text"
                value={form.job}
                onChange={(e) => setForm({ ...form, job: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="مثال: دبیر همایش"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">تقویم نمایشی</label>
              <select
                value={form.calendar}
                onChange={(e) => setForm({ ...form, calendar: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm font-medium"
              >
                <option value="jalali">هجری شمسی (ایران)</option>
                <option value="gregorian">میلادی (Gregorian)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1.5">منطقه زمانی</label>
              <select
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm font-medium"
                dir="ltr"
              >
                <option value="Asia/Tehran">Asia/Tehran (+03:30)</option>
                <option value="UTC">UTC (+00:00)</option>
                <option value="Europe/London">Europe/London</option>
                <option value="America/New_York">America/New_York</option>
                <option value="Asia/Dubai">Asia/Dubai (+04:00)</option>
              </select>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-600/25 transition-all disabled:opacity-50 hover:-translate-y-0.5 active:translate-y-0 mt-2"
          >
            {loading ? 'در حال ثبت‌نام…' : 'ایجاد حساب کاربری'}
          </button>
        </form>

        <p className="text-center text-xs text-gray-500">
          قبلاً حساب ساخته‌اید؟{' '}
          <Link to="/login" className="text-blue-600 font-bold hover:underline">
            ورود به حساب
          </Link>
        </p>
      </div>
    </div>
  );
};
