import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { Navbar } from './components/Navbar';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { ProfilePage } from './pages/ProfilePage';
import { RoomsListPage } from './pages/RoomsListPage';
import { RoomDetailPage } from './pages/RoomDetailPage';
import { RoomEditPage } from './pages/RoomEditPage';
import { PlayPage } from './pages/PlayPage';
import { PublicRoomPage } from './pages/PublicRoomPage';
import { AdminDashboardPage } from './pages/AdminDashboardPage';

const ProtectedRoute: React.FC<{ children: React.ReactNode; adminOnly?: boolean }> = ({
  children,
  adminOnly = false,
}) => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400 font-bold">
        در حال بررسی دسترسی…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (adminOnly && user.role !== 'admin') {
    return <Navigate to="/rooms" replace />;
  }

  return <>{children}</>;
};

export const AppContent: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50/50">
      <Routes>
        {/* مسیر تماشاگر عمومی نیازی به Navbar ندارد */}
        <Route path="/public/:token" element={<PublicRoomPage />} />

        {/* سایر مسیرها با Navbar اختصاصی */}
        <Route
          path="*"
          element={
            <>
              <Navbar />
              <main className="flex-1">
                <Routes>
                  <Route path="/" element={<Navigate to="/rooms" replace />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/register" element={<RegisterPage />} />

                  <Route
                    path="/profile"
                    element={
                      <ProtectedRoute>
                        <ProfilePage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/rooms"
                    element={
                      <ProtectedRoute>
                        <RoomsListPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/rooms/:id"
                    element={
                      <ProtectedRoute>
                        <RoomDetailPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/rooms/:id/edit"
                    element={
                      <ProtectedRoute>
                        <RoomEditPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/rooms/:id/play"
                    element={
                      <ProtectedRoute>
                        <PlayPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/admin"
                    element={
                      <ProtectedRoute adminOnly>
                        <AdminDashboardPage />
                      </ProtectedRoute>
                    }
                  />

                  <Route path="*" element={<Navigate to="/rooms" replace />} />
                </Routes>
              </main>
            </>
          }
        />
      </Routes>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </BrowserRouter>
  );
};
