import { FormEvent, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import * as api from "../api/client";
import { AdminEntry, AdminUserDetail, AdminUserSummary } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { colorForUsername } from "@/lib/colors";

function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Avatar({ username }: { username: string }) {
  return (
    <span
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white"
      style={{ backgroundColor: colorForUsername(username) }}
    >
      {initials(username)}
    </span>
  );
}

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const { showError, showSuccess } = useToast();

  const [members, setMembers] = useState<AdminUserSummary[]>([]);
  const [admins, setAdmins] = useState<AdminEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [newAdminEmail, setNewAdminEmail] = useState("");

  async function refresh() {
    try {
      const [m, a] = await Promise.all([api.getAdminUsers(), api.getAdmins()]);
      setMembers(m);
      setAdmins(a);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load admin data");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function openDetail(id: number) {
    try {
      setDetail(await api.getAdminUserDetail(id));
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load member");
    }
  }

  async function handleDelete(u: AdminUserSummary) {
    if (!confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    setBusy(`del-${u.id}`);
    try {
      await api.deleteAdminUser(u.id);
      showSuccess(`Deleted ${u.username}`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to delete user");
    } finally {
      setBusy(null);
    }
  }

  async function handleGrant(e: FormEvent) {
    e.preventDefault();
    const email = newAdminEmail.trim();
    if (!email) return;
    setBusy("grant");
    try {
      const res = await api.grantAdmin(email);
      showSuccess(res.message);
      setNewAdminEmail("");
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to grant admin");
    } finally {
      setBusy(null);
    }
  }

  async function handleRevoke(email: string) {
    if (!confirm(`Revoke admin access for ${email}?`)) return;
    setBusy(`rev-${email}`);
    try {
      const res = await api.revokeAdmin(email);
      showSuccess(res.message);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to revoke admin");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Admin panel</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {members.length} member{members.length === 1 ? "" : "s"} · manage administrators below
      </p>

      {/* Members */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Completed labs</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        <Avatar username={u.username} />
                        {u.username}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{u.email}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Badge variant={u.role === "admin" ? "default" : "secondary"}>{u.role}</Badge>
                        {u.is_root_admin && (
                          <Badge variant="outline" title="Root admin defined in config">
                            root
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">{u.completed_labs}</span>
                      <span className="text-muted-foreground"> lab{u.completed_labs === 1 ? "" : "s"}</span>
                      {u.completed_sessions > 0 && (
                        <span className="text-muted-foreground">
                          {" "}
                          · {u.completed_sessions} session{u.completed_sessions === 1 ? "" : "s"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(u.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="secondary" onClick={() => openDetail(u.id)}>
                          View
                        </Button>
                        {u.id !== currentUser?.id && !u.is_root_admin && (
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy === `del-${u.id}`}
                            onClick={() => handleDelete(u)}
                          >
                            Delete
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Administrators */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Administrators</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleGrant} className="mb-2 flex flex-col gap-2 sm:flex-row">
            <Input
              type="email"
              placeholder="new.admin@example.com"
              value={newAdminEmail}
              onChange={(e) => setNewAdminEmail(e.target.value)}
              className="sm:max-w-sm"
            />
            <Button type="submit" disabled={busy === "grant" || !newAdminEmail.trim()}>
              Grant admin
            </Button>
          </form>
          <p className="mb-5 text-xs text-muted-foreground">
            The address becomes an admin as soon as it registers and verifies its email — you can pre-authorize
            someone before they sign up.
          </p>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {admins.map((a) => (
                  <TableRow key={a.email}>
                    <TableCell className="font-medium">
                      {a.email}
                      {a.username && <span className="ml-2 text-muted-foreground">({a.username})</span>}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {a.is_root_admin ? (
                          <Badge variant="outline">root</Badge>
                        ) : (
                          <Badge variant="default">granted</Badge>
                        )}
                        {!a.is_registered && (
                          <Badge variant="secondary" title="No account with this address yet">
                            pending
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      {!a.is_root_admin && (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={busy === `rev-${a.email}`}
                          onClick={() => handleRevoke(a.email)}
                        >
                          Revoke
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Member detail */}
      <Dialog open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent>
          {detail && (
            <div className="max-h-[75vh] overflow-y-auto">
              <div className="flex items-center gap-3">
                <Avatar username={detail.username} />
                <div>
                  <h2 className="text-lg font-semibold">{detail.username}</h2>
                  <p className="text-sm text-muted-foreground">{detail.email}</p>
                </div>
                <div className="ml-auto flex items-center gap-1">
                  <Badge variant={detail.role === "admin" ? "default" : "secondary"}>{detail.role}</Badge>
                  {detail.is_root_admin && <Badge variant="outline">root</Badge>}
                </div>
              </div>

              <section className="mt-5">
                <h3 className="text-sm font-semibold">Profile</h3>
                {detail.profile ? (
                  <dl className="mt-2 grid grid-cols-[7rem_1fr] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-muted-foreground">Full name</dt>
                    <dd>{detail.profile.full_name || "—"}</dd>
                    <dt className="text-muted-foreground">School</dt>
                    <dd>{detail.profile.school || "—"}</dd>
                    <dt className="text-muted-foreground">Department</dt>
                    <dd>{detail.profile.department || "—"}</dd>
                    <dt className="text-muted-foreground">Age</dt>
                    <dd>{detail.profile.age ?? "—"}</dd>
                    <dt className="text-muted-foreground">Bio</dt>
                    <dd className="whitespace-pre-wrap">{detail.profile.bio || "—"}</dd>
                    <dt className="text-muted-foreground">Visibility</dt>
                    <dd>{detail.profile.is_public ? "Public" : "Private"}</dd>
                    {detail.profile.social_links &&
                      Object.entries(detail.profile.social_links).map(([k, v]) => (
                        <div key={k} className="contents">
                          <dt className="text-muted-foreground capitalize">{k}</dt>
                          <dd className="truncate">
                            <a href={v} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                              {v}
                            </a>
                          </dd>
                        </div>
                      ))}
                  </dl>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">No profile filled in.</p>
                )}
              </section>

              <section className="mt-5">
                <h3 className="text-sm font-semibold">Reservation history ({detail.reservations.length})</h3>
                {detail.reservations.length === 0 ? (
                  <p className="mt-1 text-sm text-muted-foreground">No reservations yet.</p>
                ) : (
                  <div className="mt-2 overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Lab</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>When</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.reservations.map((r) => (
                          <TableRow key={r.id}>
                            <TableCell className="font-medium">{r.lab_name}</TableCell>
                            <TableCell>
                              <Badge
                                variant={
                                  r.status === "completed"
                                    ? "default"
                                    : r.status === "active"
                                      ? "secondary"
                                      : "outline"
                                }
                              >
                                {r.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {formatDate(r.usage_start_time ?? r.created_at)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </section>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
