import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import * as api from "../api/client";
import { User } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const { showError } = useToast();
  const [users, setUsers] = useState<User[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function refresh() {
    try {
      setUsers(await api.getUsers());
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load users");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleDelete(id: number, username: string) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;

    setBusyId(id);
    try {
      await api.deleteUser(id);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to delete user");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Users</h1>
      <div className="mt-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Username</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.username}</TableCell>
                <TableCell className="text-muted-foreground">{u.email}</TableCell>
                <TableCell>
                  <Badge variant={u.role === "admin" ? "default" : "secondary"}>{u.role}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {u.id !== currentUser?.id && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busyId === u.id}
                      onClick={() => handleDelete(u.id, u.username)}
                    >
                      Delete
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
