import { Navigate, Route, Routes } from "react-router-dom";
import Navbar from "./components/Navbar";
import ProtectedRoute from "./components/ProtectedRoute";
import { useAuth } from "./context/AuthContext";
import AdminUsersPage from "./pages/AdminUsersPage";
import DashboardPage from "./pages/DashboardPage";
import LabsPage from "./pages/LabsPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <p className="hint">Loading...</p>;

  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/labs"
          element={
            <ProtectedRoute>
              <LabsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <ProtectedRoute adminOnly>
              <AdminUsersPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to={user ? "/dashboard" : "/login"} replace />} />
      </Routes>
    </>
  );
}
