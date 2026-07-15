import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "../context/AuthContext";
import { useAuthDialog } from "../context/AuthDialogContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const { openLogin, openRegister } = useAuthDialog();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate("/");
  }

  return (
    <nav className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-7 py-1.5">
      {/* LICENSE (Branding & Attribution Requirement, item 1): the FPGA
          Vision Remote Lab logo and the Hochschule Bonn-Rhein-Sieg logo
          below must not be removed, replaced, resized down, or hidden in
          any deployment. */}
      <div className="flex items-center gap-4">
        <Link to="/">
          <img src="/logo.png" alt="FPGA Remote Lab" className="h-16 w-auto" />
        </Link>
        <span className="h-11 w-px bg-border" />
        <a href="https://www.h-brs.de/de" target="_blank" rel="noopener noreferrer">
          <img src="/bonn-logo.png" alt="Hochschule Bonn-Rhein-Sieg" className="h-11 w-auto" />
        </a>
      </div>
      <div className="flex items-center gap-5 text-sm">
        {user ? (
          <>
            <Link to="/dashboard" className="font-medium text-muted-foreground hover:text-foreground">
              Dashboard
            </Link>
            <Link to="/labs" className="font-medium text-muted-foreground hover:text-foreground">
              Labs
            </Link>
            <Link to="/calendar" className="font-medium text-muted-foreground hover:text-foreground">
              Calendar
            </Link>
            {user.role === "admin" && (
              <Link to="/admin/users" className="font-medium text-muted-foreground hover:text-foreground">
                Admin
              </Link>
            )}
            <Link
              to="/profile"
              className="border-l border-border pl-4 font-medium text-muted-foreground hover:text-foreground"
            >
              {user.username}
            </Link>
            <Button variant="link" className="h-auto p-0" onClick={handleLogout}>
              Log out
            </Button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={openLogin}
              className="font-medium text-muted-foreground hover:text-foreground"
            >
              Sign in
            </button>
            <Button size="sm" onClick={openRegister}>
              Register
            </Button>
          </>
        )}
      </div>
    </nav>
  );
}
