import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/login");
  }

  return (
    <nav className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-7 py-1.5">
      <Link to="/" className="flex items-center gap-4 font-bold tracking-tight text-foreground">
        <img src="/logo.png" alt="" className="h-16 w-auto" />
        <span className="text-xl">FPGA Remote Lab</span>
        <span className="h-11 w-px bg-border" />
        <img src="/bonn-logo.png" alt="Hochschule Bonn-Rhein-Sieg" className="h-11 w-auto" />
      </Link>
      <div className="flex items-center gap-5 text-sm">
        {user ? (
          <>
            <Link to="/dashboard" className="font-medium text-muted-foreground hover:text-foreground">
              Dashboard
            </Link>
            <Link to="/labs" className="font-medium text-muted-foreground hover:text-foreground">
              Labs
            </Link>
            {user.role === "admin" && (
              <Link to="/admin/users" className="font-medium text-muted-foreground hover:text-foreground">
                Users
              </Link>
            )}
            <span className="border-l border-border pl-4 text-muted-foreground">{user.username}</span>
            <Button variant="link" className="h-auto p-0" onClick={handleLogout}>
              Log out
            </Button>
          </>
        ) : (
          <>
            <Link to="/login" className="font-medium text-muted-foreground hover:text-foreground">
              Sign in
            </Link>
            <Button asChild size="sm">
              <Link to="/register">Register</Link>
            </Button>
          </>
        )}
      </div>
    </nav>
  );
}
