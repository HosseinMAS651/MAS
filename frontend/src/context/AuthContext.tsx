import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, setCsrfToken } from '../api/client';
import { User } from '../types';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  register: (payload: any) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  authError: string;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState('');

  const refreshUser = async () => {
    const maxAttempts = 3;
    try {
      setAuthError('');
      let lastError: any = null;

      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
          const data = await api.get('/api/auth/me');
          if (data?.user) setUser(data.user);
          return;
        } catch (err: any) {
          lastError = err;
          // 401 is a real logout; do not retry it. Other failures can be caused by
          // Render cold-starts or a brief database wake-up.
          if (err?.status === 401) {
            setUser(null);
            setCsrfToken('');
            setAuthError('');
            return;
          }
          if (attempt < maxAttempts) {
            await new Promise((resolve) => window.setTimeout(resolve, attempt * 2500));
          }
        }
      }

      throw lastError || new Error('ارتباط با سرور برقرار نشد.');
    } catch (err: any) {
      // Network/server outage is not the same thing as logout. Preserve current user state.
      setAuthError(err?.message || 'ارتباط با سرور برقرار نشد.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refreshUser(); }, []);

  const login = async (username: string, password: string) => {
    const data = await api.post('/api/auth/login', { username, password });
    setAuthError('');
    setUser(data.user);
    return data.user;
  };

  const register = async (payload: any) => {
    const data = await api.post('/api/auth/register', payload);
    setAuthError('');
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try { await api.post('/api/auth/logout'); } finally { setUser(null); setCsrfToken(''); }
  };

  return <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser, authError }}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};
