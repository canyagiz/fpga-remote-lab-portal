import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <nav className="navbar">
      <span className="nav-brand">FPGA Remote Lab</span>
      <div className="nav-links">
        <Link to="/dashboard">Dashboard</Link>
        <Link to="/labs">Labs</Link>
        {user.role === "admin" && <Link to="/admin/users">Users</Link>}
        <span className="nav-user">{user.username}</span>
        <button className="link-button" onClick={handleLogout}>
          Log out
        </button>
      </div>
    </nav>
  );
}
