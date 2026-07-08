import { useEffect, useState } from "react";
import * as api from "../api/client";
import { User } from "../api/types";
import { useAuth } from "../context/AuthContext";

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function refresh() {
    try {
      setUsers(await api.getUsers());
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to load users");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleDelete(id: number, username: string) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;

    setBusyId(id);
    setError(null);
    try {
      await api.deleteUser(id);
      await refresh();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to delete user");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="page">
      <h1>Users</h1>
      {error && <p className="error">{error}</p>}
      <table className="user-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Email</th>
            <th>Role</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>{u.email}</td>
              <td>{u.role}</td>
              <td>
                {u.id !== currentUser?.id && (
                  <button
                    className="secondary"
                    disabled={busyId === u.id}
                    onClick={() => handleDelete(u.id, u.username)}
                  >
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
