import { Navigate, Route, Routes } from "react-router-dom";
import AuthDialog from "./components/AuthDialog";
import Navbar from "./components/Navbar";
import ProtectedRoute from "./components/ProtectedRoute";
import { useAuth } from "./context/AuthContext";
import AdminUsersPage from "./pages/AdminUsersPage";
import CalendarPage from "./pages/CalendarPage";
import DashboardPage from "./pages/DashboardPage";
import FleetGraphPage from "./pages/FleetGraphPage";
import FleetPage from "./pages/FleetPage";
import HomePage from "./pages/HomePage";
import LabsPage from "./pages/LabsPage";
import ProfilePage from "./pages/ProfilePage";
import UserProfilePage from "./pages/UserProfilePage";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <p className="p-6 text-sm text-muted-foreground">Loading...</p>;

  return (
    <>
      <Navbar />
      <Routes>
        <Route path="/" element={<HomePage />} />
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
          path="/calendar"
          element={
            <ProtectedRoute>
              <CalendarPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/users/:username"
          element={
            <ProtectedRoute>
              <UserProfilePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/fleet/graph"
          element={
            <ProtectedRoute adminOnly>
              <FleetGraphPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin/fleet"
          element={
            <ProtectedRoute adminOnly>
              <FleetPage />
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
        <Route path="*" element={<Navigate to={user ? "/dashboard" : "/"} replace />} />
      </Routes>
      <AuthDialog />
    </>
  );
}
