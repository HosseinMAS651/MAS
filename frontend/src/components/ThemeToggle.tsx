import React from 'react';
import { useTheme } from '../context/ThemeContext';

export const ThemeToggle: React.FC<{ className?: string }> = ({ className = '' }) => {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={theme === 'dark' ? 'حالت روز' : 'حالت شب'}
      aria-label="تغییر پوسته"
      className={`p-2 rounded-xl border transition-all text-xs flex items-center justify-center ${
        theme === 'dark'
          ? 'bg-slate-800 border-slate-700 text-amber-300 hover:bg-slate-700'
          : 'bg-white border-gray-200 text-slate-700 hover:bg-gray-50 shadow-sm'
      } ${className}`}
    >
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
};
