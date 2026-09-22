import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, setCsrfToken } from '../api/client';
import { User } from '../types';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: str) => Promise<User>;
  register: (payload: any) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

type str = string;

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const refreshUser = async () => {
    try {
      const data = await api.get('/api/auth/me');
      if (data?.user) {
        setUser(data.user);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshUser();
  }, []);

  const login = async (username: string, password: str) => {
    const data = await api.post('/api/auth/login', { username, password });
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    setUser(data.user);
    return data.user;
  };

  const register = async (payload: any) => {
    const data = await api.post('/api/auth/register', payload);
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try {
      await api.post('/api/auth/logout');
    } finally {
      setUser(null);
      setCsrfToken('');
    }
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
