import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
      navigate('/rooms');
    } catch (err: any) {
      setError(err.message || 'نام کاربری یا رمز عبور نادرست است.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-gradient-to-b from-blue-50/50 to-white">
      <div className="max-w-md w-full bg-white rounded-3xl shadow-xl shadow-blue-900/5 border border-gray-100 p-8 space-y-6">
        <div className="text-center space-y-2">
          <div className="w-14 h-14 bg-blue-600 text-white rounded-2xl flex items-center justify-center text-2xl font-black mx-auto shadow-lg shadow-blue-600/30">
            مـاس
          </div>
          <h2 className="text-2xl font-black text-gray-900">ورود به حساب کاربری</h2>
          <p className="text-sm text-gray-500">برای مدیریت اتاق‌ها و زمان‌بندی سخنرانی وارد شوید</p>
        </div>

        {error && (
          <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm font-medium rounded-2xl animate-shake">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1.5">نام کاربری</label>
            <input
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm transition-all"
              placeholder="مثال: ali_rezaei"
              dir="ltr"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-gray-700 mb-1.5">رمز عبور</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-600 outline-none text-sm transition-all"
              placeholder="••••••••"
              dir="ltr"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-xl shadow-lg shadow-blue-600/25 transition-all disabled:opacity-50 hover:-translate-y-0.5 active:translate-y-0"
          >
            {loading ? 'در حال ورود…' : 'ورود به سامانه'}
          </button>
        </form>

        <p className="text-center text-xs text-gray-500">
          حساب کاربری ندارید؟{' '}
          <Link to="/register" className="text-blue-600 font-bold hover:underline">
            ثبت‌نام رایگان
          </Link>
        </p>
      </div>
    </div>
  );
};
