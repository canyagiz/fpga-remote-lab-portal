import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import * as api from "../api/client";
import { User } from "../api/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<{ requires2FA: boolean }>;
  verify2FA: (code: string) => Promise<void>;
  resend2FA: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    const result = await api.login(username, password);
    if (!result.require_2fa) {
      setUser(await api.getMe());
    }
    return { requires2FA: result.require_2fa };
  }

  async function verify2FA(code: string) {
    const verifiedUser = await api.verify2FA(code);
    setUser(verifiedUser);
  }

  async function resend2FA() {
    await api.resend2FA();
  }

  async function logout() {
    await api.logout();
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, verify2FA, resend2FA, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
