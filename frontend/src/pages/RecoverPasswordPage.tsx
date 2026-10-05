import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export const RecoverPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [recoveryCode, setRecoveryCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      await api.post('/api/auth/recover-password', {
        username,
        recovery_code: recoveryCode,
        new_password: newPassword,
      });
      setSuccess('رمز عبور بازنشانی شد. این کد بازیابی دیگر قابل استفاده نیست.');
      setTimeout(() => navigate('/login'), 1200);
    } catch (err: any) {
      setError(err.message || 'نام کاربری یا کد بازیابی معتبر نیست.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-gradient-to-b from-blue-50/50 to-white dark:from-slate-950 dark:to-slate-900">
      <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-3xl shadow-xl border border-gray-100 dark:border-slate-800 p-8 space-y-6">
        <div className="text-center space-y-2">
          <div className="text-4xl">🔑</div>
          <h1 className="text-2xl font-black text-gray-900 dark:text-white">بازیابی رمز عبور</h1>
          <p className="text-sm text-gray-500 dark:text-slate-400 leading-6">نام کاربری، کد بازیابی یک‌بارمصرف و رمز جدید را وارد کنید.</p>
        </div>
        {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">{error}</div>}
        {success && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">{success}</div>}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-bold text-gray-700 dark:text-slate-300">نام کاربری</label>
            <input required value={username} onChange={(event) => setUsername(event.target.value)} dir="ltr" autoComplete="username" className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none focus:border-blue-600 dark:border-slate-700 dark:bg-slate-800 dark:text-white" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold text-gray-700 dark:text-slate-300">کد بازیابی</label>
            <input required value={recoveryCode} onChange={(event) => setRecoveryCode(event.target.value)} dir="ltr" autoComplete="one-time-code" className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm font-mono tracking-wider text-gray-900 outline-none focus:border-blue-600 dark:border-slate-700 dark:bg-slate-800 dark:text-white" placeholder="ABCDE-FG234-HJKLM-N5678" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-bold text-gray-700 dark:text-slate-300">رمز عبور جدید</label>
            <input required type="password" minLength={8} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} dir="ltr" autoComplete="new-password" className="w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-900 outline-none focus:border-blue-600 dark:border-slate-700 dark:bg-slate-800 dark:text-white" />
          </div>
          <button disabled={loading} className="w-full rounded-xl bg-blue-600 py-3 font-bold text-white hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'در حال بازنشانی…' : 'بازنشانی رمز عبور'}
          </button>
        </form>
        <p className="text-center text-xs text-gray-500 dark:text-slate-400">کد بازیابی ندارید؟ برای حساب‌های قدیمی از مدیر سامانه بخواهید رمز را از سرور بازنشانی کند.</p>
        <div className="text-center"><Link to="/login" className="text-sm font-bold text-blue-600 dark:text-blue-400">بازگشت به ورود</Link></div>
      </div>
    </div>
  );
};
