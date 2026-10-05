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
  const [recoveryCode, setRecoveryCode] = useState('');
  const [copied, setCopied] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await register({
        ...form,
        age: form.age ? parseInt(form.age, 10) : null,
      });
      setRecoveryCode(result.recoveryCode);
    } catch (err: any) {
      setError(err.message || 'خطا در ثبت‌نام. لطفاً اطلاعات را بررسی کنید.');
    } finally {
      setLoading(false);
    }
  };

  const copyRecoveryCode = async () => {
    try {
      await navigator.clipboard.writeText(recoveryCode);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  if (recoveryCode) {
    return (
      <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-gradient-to-b from-blue-50/50 to-white dark:from-slate-950 dark:to-slate-900">
        <div className="max-w-lg w-full bg-white dark:bg-slate-900 rounded-3xl border border-amber-200 dark:border-amber-900 p-8 space-y-5 text-center shadow-xl">
          <div className="text-4xl">🔐</div>
          <h2 className="text-2xl font-black text-gray-900 dark:text-white">کد بازیابی یک‌بارمصرف شما</h2>
          <p className="text-sm text-gray-600 dark:text-slate-300 leading-7">
            این کد را اکنون یادداشت و در جای امن نگه‌داری کنید. سامانه فقط هش آن را ذخیره می‌کند و دوباره قابل نمایش نیست؛
            اگر آن را گم کنید، پس از ورود می‌توانید کد تازه بسازید.
          </p>
          <code dir="ltr" className="block rounded-2xl bg-gray-100 dark:bg-slate-800 px-4 py-5 text-xl sm:text-2xl font-black tracking-widest text-blue-700 dark:text-blue-300 select-all">
            {recoveryCode}
          </code>
          <button type="button" onClick={copyRecoveryCode} className="px-4 py-2 rounded-xl border border-gray-200 dark:border-slate-700 text-sm font-bold text-gray-700 dark:text-slate-200">
            {copied ? 'کپی شد ✓' : 'کپی کد'}
          </button>
          <button type="button" onClick={() => navigate('/rooms')} className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold">
            کد را نگه داشتم؛ ورود به اتاق‌ها
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-gradient-to-b from-blue-50/50 to-white dark:from-slate-950 dark:to-slate-900 transition-colors">
      <div className="max-w-lg w-full bg-white dark:bg-slate-900 rounded-3xl shadow-xl shadow-blue-900/5 dark:shadow-black/40 border border-gray-100 dark:border-slate-800 p-8 space-y-6 transition-colors">
        <div className="text-center space-y-2">
          <div className="w-14 h-14 bg-blue-600 text-white rounded-2xl flex items-center justify-center text-2xl font-black mx-auto shadow-lg shadow-blue-600/30">
            مـاس
          </div>
          <h2 className="text-2xl font-black text-gray-900 dark:text-white">ساخت حساب کاربری جدید</h2>
          <p className="text-sm text-gray-500 dark:text-slate-400">برای شروع مدیریت زمان‌بندی سخنرانی‌ها ثبت‌نام کنید</p>
        </div>

        {error && (
          <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm font-medium rounded-2xl">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">
                نام کاربری <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="حداقل ۳ کاراکتر"
                dir="ltr"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">
                رمز عبور <span className="text-red-500">*</span>
              </label>
              <input
                type="password"
                required
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="حداقل ۸ کاراکتر"
                dir="ltr"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">نام و نام خانوادگی</label>
              <input
                type="text"
                value={form.account_name}
                onChange={(e) => setForm({ ...form, account_name: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="مثال: علی رضایی"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">شغل یا سمت</label>
              <input
                type="text"
                value={form.job}
                onChange={(e) => setForm({ ...form, job: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm"
                placeholder="مثال: دبیر همایش"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">تقویم نمایشی</label>
              <select
                value={form.calendar}
                onChange={(e) => setForm({ ...form, calendar: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm font-medium"
              >
                <option value="jalali">هجری شمسی (ایران)</option>
                <option value="gregorian">میلادی (Gregorian)</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-1.5">منطقه زمانی</label>
              <select
                value={form.timezone}
                onChange={(e) => setForm({ ...form, timezone: e.target.value })}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 text-gray-900 dark:text-white rounded-xl focus:bg-white dark:focus:bg-slate-900 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm font-medium"
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

        <p className="text-center text-xs text-gray-500 dark:text-slate-400">
          قبلاً حساب ساخته‌اید؟{' '}
          <Link to="/login" className="text-blue-600 dark:text-blue-400 font-bold hover:underline">
            ورود به حساب
          </Link>
        </p>
      </div>
    </div>
  );
};
