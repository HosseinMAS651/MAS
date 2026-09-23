import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-gray-100 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2 group">
            <span className="w-10 h-10 rounded-xl bg-blue-600 text-white font-extrabold flex items-center justify-center text-xl shadow-md shadow-blue-600/30 group-hover:scale-105 transition-transform">
              مـاس
            </span>
            <span className="font-extrabold text-lg text-gray-900 tracking-tight hidden sm:inline">
              مدیریت زمان سخنرانی
            </span>
          </Link>

          {user && (
            <nav className="flex items-center gap-2 sm:gap-4">
              <Link
                to="/rooms"
                className="px-3 py-1.5 rounded-lg text-sm font-bold text-gray-700 hover:text-blue-600 hover:bg-blue-50/60 transition-colors"
              >
                اتاق‌ها
              </Link>
              {user.role === 'admin' && (
                <Link
                  to="/admin"
                  className="px-3 py-1.5 rounded-lg text-sm font-bold text-indigo-700 hover:text-indigo-900 hover:bg-indigo-50/60 transition-colors flex items-center gap-1.5"
                >
                  <span className="w-2 h-2 rounded-full bg-indigo-600"></span>
                  پنل مدیریت
                </Link>
              )}
            </nav>
          )}
        </div>

        <div className="flex items-center gap-3">
          {user ? (
            <div className="flex items-center gap-3">
              <Link
                to="/profile"
                className="flex items-center gap-2 p-1.5 pr-3 pl-2 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50/30 transition-all text-xs"
              >
                <span className="font-bold text-gray-800">{user.account_name || user.username}</span>
                <span className="w-6 h-6 rounded-full bg-blue-100 text-blue-700 font-bold flex items-center justify-center text-xs">
                  {user.username.slice(0, 1).toUpperCase()}
                </span>
              </Link>
              <button
                onClick={handleLogout}
                className="px-3 py-1.5 text-xs font-bold text-red-600 hover:bg-red-50 rounded-xl transition-colors"
              >
                خروج
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link
                to="/login"
                className="px-4 py-2 text-sm font-bold text-gray-700 hover:text-blue-600 transition-colors"
              >
                ورود
              </Link>
              <Link
                to="/register"
                className="px-4 py-2 text-sm font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md shadow-blue-600/20 transition-all"
              >
                ثبت‌نام رایگان
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
