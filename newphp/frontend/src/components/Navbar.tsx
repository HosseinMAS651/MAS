import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ThemeToggle } from './ThemeToggle';
import { GuideTourModal } from './GuideTourModal';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [showGuide, setShowGuide] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <>
      <header className="sticky top-0 z-40 bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-gray-100 dark:border-slate-800 shadow-sm transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-2 group">
              <span className="w-10 h-10 rounded-xl bg-blue-600 text-white font-extrabold flex items-center justify-center text-xl shadow-md shadow-blue-600/30 group-hover:scale-105 transition-transform">
                مـاس
              </span>
              <span className="font-extrabold text-lg text-gray-900 dark:text-white tracking-tight hidden sm:inline">
                مدیریت زمان سخنرانی
              </span>
            </Link>

            {user && (
              <nav className="flex items-center gap-2 sm:gap-4">
                <Link
                  to="/rooms"
                  className="px-3 py-1.5 rounded-lg text-sm font-bold text-gray-700 dark:text-slate-200 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50/60 dark:hover:bg-slate-800 transition-colors"
                >
                  اتاق‌ها
                </Link>
                {user.role === 'admin' && (
                  <Link
                    to="/admin"
                    className="px-3 py-1.5 rounded-lg text-sm font-bold text-indigo-700 dark:text-indigo-400 hover:text-indigo-900 hover:bg-indigo-50/60 dark:hover:bg-indigo-950/40 transition-colors flex items-center gap-1.5"
                  >
                    <span className="w-2 h-2 rounded-full bg-indigo-600 dark:bg-indigo-400"></span>
                    پنل مدیریت
                  </Link>
                )}
              </nav>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* دکمه راهنمای سامانه */}
            <button
              type="button"
              onClick={() => setShowGuide(true)}
              className="px-3 py-1.5 rounded-xl border border-gray-200 dark:border-slate-700 text-xs font-bold text-gray-700 dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800 flex items-center gap-1.5 transition-colors"
            >
              <span>💡</span>
              <span className="hidden sm:inline">راهنمای سامانه</span>
            </button>

            {/* سوئیچ حالت تاریک/روشن */}
            <ThemeToggle />

            {user ? (
              <div className="flex items-center gap-3">
                <Link
                  to="/profile"
                  className="flex items-center gap-2 p-1.5 pr-3 pl-2 rounded-xl border border-gray-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-500 hover:bg-blue-50/30 dark:hover:bg-slate-800 transition-all text-xs"
                >
                  <span className="font-bold text-gray-800 dark:text-slate-200">{user.account_name || user.username}</span>
                  <span className="w-6 h-6 rounded-full bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300 font-bold flex items-center justify-center text-xs">
                    {user.username.slice(0, 1).toUpperCase()}
                  </span>
                </Link>
                <button
                  onClick={handleLogout}
                  className="px-3 py-1.5 text-xs font-bold text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 rounded-xl transition-colors"
                >
                  خروج
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link
                  to="/login"
                  className="px-4 py-2 text-sm font-bold text-gray-700 dark:text-slate-200 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
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

      <GuideTourModal isOpen={showGuide} onClose={() => setShowGuide(false)} />
    </>
  );
};
