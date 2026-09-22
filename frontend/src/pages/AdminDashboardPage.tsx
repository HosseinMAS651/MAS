import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { AdminStats, AdminUser, AdminRoom, AuditLog } from '../types';
import { formatBytes, formatDate } from '../utils/formatters';

export const AdminDashboardPage: React.FC = () => {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [rooms, setRooms] = useState<AdminRoom[]>([]);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [activeTab, setActiveTab] = useState<'users' | 'rooms' | 'logs'>('users');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>('');

  const fetchAdminData = async () => {
    try {
      const [statsRes, usersRes, roomsRes, logsRes] = await Promise.all([
        api.get('/api/admin/stats'),
        api.get('/api/admin/users'),
        api.get('/api/admin/rooms'),
        api.get('/api/admin/audit-logs'),
      ]);
      setStats(statsRes.stats);
      setUsers(usersRes.users || []);
      setRooms(roomsRes.rooms || []);
      setLogs(logsRes.logs || []);
    } catch (err: any) {
      setError(err.message || 'خطا در بارگذاری اطلاعات پنل مدیریت.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAdminData();
  }, []);

  const handleToggleUser = async (userId: number) => {
    try {
      await api.post(`/api/admin/users/${userId}/toggle-active`);
      await fetchAdminData();
    } catch (err: any) {
      alert(err.message || 'خطا در تغییر وضعیت کاربر.');
    }
  };

  if (loading) {
    return <div className="text-center py-24 text-gray-400 font-bold">در حال بارگذاری پنل مدیریت…</div>;
  }
  if (error) {
    return <div className="p-8 text-center text-red-600 font-bold">{error}</div>;
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      <div>
        <h1 className="text-3xl font-black text-gray-900 tracking-tight">پنل مدیریت سامانه (Admin)</h1>
        <p className="text-sm text-gray-500 mt-1">نظارت بر مصرف منابع، کاربران، جلسات و لاگ‌های امنیتی</p>
      </div>

      {/* کارت‌های آمار کلیدی */}
      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-1">
            <span className="text-xs font-bold text-gray-400">تعداد کل کاربران</span>
            <div className="text-3xl font-black text-blue-600">{stats.users_count}</div>
          </div>
          <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-1">
            <span className="text-xs font-bold text-gray-400">تعداد کل اتاق‌ها</span>
            <div className="text-3xl font-black text-indigo-600">{stats.rooms_count}</div>
          </div>
          <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-1">
            <span className="text-xs font-bold text-gray-400">ضبط‌های ذخیره‌شده</span>
            <div className="text-3xl font-black text-emerald-600">{stats.recordings_count}</div>
          </div>
          <div className="bg-white p-6 rounded-3xl border border-gray-100 shadow-sm space-y-1">
            <span className="text-xs font-bold text-gray-400">مجموع فضای اشغال‌شده</span>
            <div className="text-3xl font-black text-amber-600">{formatBytes(stats.total_storage_bytes)}</div>
          </div>
        </div>
      )}

      {/* تب‌های مدیریت */}
      <div className="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex border-b border-gray-100 px-6 pt-4 gap-6 text-sm font-bold">
          <button
            onClick={() => setActiveTab('users')}
            className={`pb-4 border-b-2 transition-all ${
              activeTab === 'users' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            کاربران ({users.length})
          </button>
          <button
            onClick={() => setActiveTab('rooms')}
            className={`pb-4 border-b-2 transition-all ${
              activeTab === 'rooms' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            اتاق‌ها ({rooms.length})
          </button>
          <button
            onClick={() => setActiveTab('logs')}
            className={`pb-4 border-b-2 transition-all ${
              activeTab === 'logs' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            لاگ‌های ممیزی و امنیت ({logs.length})
          </button>
        </div>

        <div className="p-6 overflow-x-auto">
          {activeTab === 'users' && (
            <table className="w-full text-right border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs font-bold text-gray-400">
                  <th className="pb-3 px-3">شناسه</th>
                  <th className="pb-3 px-3">نام کاربری</th>
                  <th className="pb-3 px-3">نام نمایشی</th>
                  <th className="pb-3 px-3">نقش</th>
                  <th className="pb-3 px-3">اتاق‌ها</th>
                  <th className="pb-3 px-3">فضای مصرفی</th>
                  <th className="pb-3 px-3">وضعیت</th>
                  <th className="pb-3 px-3 text-center">عملیات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-gray-50/50">
                    <td className="py-3 px-3 text-xs text-gray-400 font-mono">{u.id}</td>
                    <td className="py-3 px-3 font-bold text-gray-800" dir="ltr">
                      {u.username}
                    </td>
                    <td className="py-3 px-3 text-gray-600">{u.account_name || '—'}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
                          u.role === 'admin' ? 'bg-indigo-50 text-indigo-700' : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {u.role === 'admin' ? 'مدیر' : 'کاربر'}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-xs font-bold">{u.rooms_count}</td>
                    <td className="py-3 px-3 text-xs text-gray-500">{formatBytes(u.storage_used_bytes)}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
                          u.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
                        }`}
                      >
                        {u.is_active ? 'فعال' : 'مسدود'}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-center">
                      <button
                        onClick={() => handleToggleUser(u.id)}
                        className={`text-xs font-bold px-2 py-1 rounded-lg ${
                          u.is_active ? 'text-red-600 hover:bg-red-50' : 'text-emerald-600 hover:bg-emerald-50'
                        }`}
                      >
                        {u.is_active ? 'مسدودسازی' : 'فعال‌سازی'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {activeTab === 'rooms' && (
            <table className="w-full text-right border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs font-bold text-gray-400">
                  <th className="pb-3 px-3">شناسه</th>
                  <th className="pb-3 px-3">نام اتاق</th>
                  <th className="pb-3 px-3">مالک</th>
                  <th className="pb-3 px-3">ظرفیت</th>
                  <th className="pb-3 px-3">سخنرانان</th>
                  <th className="pb-3 px-3">فضای اشغال‌شده</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rooms.map((r) => (
                  <tr key={r.id} className="hover:bg-gray-50/50">
                    <td className="py-3 px-3 text-xs text-gray-400 font-mono">{r.id}</td>
                    <td className="py-3 px-3 font-bold text-gray-800">{r.name}</td>
                    <td className="py-3 px-3 text-gray-600" dir="ltr">
                      {r.owner_username}
                    </td>
                    <td className="py-3 px-3 text-xs font-bold">{r.capacity} نفر</td>
                    <td className="py-3 px-3 text-xs text-gray-500">{r.speakers_count}</td>
                    <td className="py-3 px-3 text-xs text-gray-500">{formatBytes(r.storage_used_bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {activeTab === 'logs' && (
            <table className="w-full text-right border-collapse text-xs">
              <thead>
                <tr className="border-b border-gray-100 font-bold text-gray-400">
                  <th className="pb-3 px-3">زمان</th>
                  <th className="pb-3 px-3">سطح</th>
                  <th className="pb-3 px-3">اقدام</th>
                  <th className="pb-3 px-3">کاربر</th>
                  <th className="pb-3 px-3">آی‌پی (IP)</th>
                  <th className="pb-3 px-3">جزئیات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50 font-mono">
                {logs.map((l) => (
                  <tr key={l.id} className="hover:bg-gray-50/50">
                    <td className="py-2.5 px-3 text-gray-500 whitespace-nowrap">{formatDate(l.created_at_ms)}</td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          l.severity === 'warning'
                            ? 'bg-amber-50 text-amber-700'
                            : l.severity === 'error'
                            ? 'bg-red-50 text-red-700'
                            : 'bg-blue-50 text-blue-700'
                        }`}
                      >
                        {l.severity}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 font-bold text-gray-800">{l.action}</td>
                    <td className="py-2.5 px-3 text-gray-600">{l.actor_username || 'سیستم'}</td>
                    <td className="py-2.5 px-3 text-gray-400">{l.ip || '—'}</td>
                    <td className="py-2.5 px-3 text-gray-500 truncate max-w-xs">{l.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
};
