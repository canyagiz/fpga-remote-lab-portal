import { Building, Calendar, ExternalLink, Eye, EyeOff, Lock, Trash2, User } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import * as api from "../api/client";
import { Profile } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { colorForUsername } from "../lib/colors";

const SOCIAL_PLATFORMS: { key: string; label: string; placeholder: string }[] = [
  { key: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/..." },
  { key: "github", label: "GitHub", placeholder: "https://github.com/..." },
  { key: "instagram", label: "Instagram", placeholder: "https://instagram.com/..." },
  { key: "x", label: "X / Twitter", placeholder: "https://x.com/..." },
  { key: "website", label: "Website", placeholder: "https://..." },
];

const emptyProfile: Profile = {
  full_name: null,
  school: null,
  department: null,
  age: null,
  bio: null,
  social_links: null,
  is_public: true,
  hidden_fields: null,
};

// A small "hide this from my profile" toggle used next to every field.
// Disabled (but never reset) while the master switch is off - see the
// component's own comment on why toggling the master must not touch
// these values.
function FieldVisibilityToggle({
  hidden,
  disabledByMaster,
  onChange,
}: {
  hidden: boolean;
  disabledByMaster: boolean;
  onChange: (hidden: boolean) => void;
}) {
  return (
    <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
      {hidden ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
      Hide
      <Switch checked={!hidden} onCheckedChange={(visible) => onChange(!visible)} disabled={disabledByMaster} />
    </label>
  );
}

export default function ProfilePage() {
  const { user, logout } = useAuth();
  const { showError, showSuccess } = useToast();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);

  async function handleDeleteAccount() {
    if (!deletePassword) return;
    setDeleting(true);
    try {
      await api.deleteMyAccount(deletePassword);
      // Session is already cleared server-side; drop client auth state and
      // leave. logout() also pings /api/auth/logout, which is harmless.
      try {
        await logout();
      } catch {
        /* already signed out server-side */
      }
      showSuccess("Your account has been deleted");
      navigate("/");
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to delete account");
      setDeleting(false);
    }
  }

  useEffect(() => {
    api
      .getMyProfile()
      .then(setProfile)
      .catch((err) => showError(err instanceof api.ApiError ? err.message : "Failed to load profile"))
      .finally(() => setLoading(false));
  }, []);

  function updateField<K extends keyof Profile>(key: K, value: Profile[K]) {
    setProfile((p) => ({ ...p, [key]: value }));
  }

  function updateSocialLink(platform: string, value: string) {
    setProfile((p) => ({
      ...p,
      social_links: { ...p.social_links, [platform]: value },
    }));
  }

  // hidden_fields is a flat list of field names ("age", "bio", or
  // "social:github" for an individual link) - toggling one only ever
  // adds/removes its own entry, never touches is_public or any other
  // field's entry.
  function isHidden(fieldKey: string): boolean {
    return (profile.hidden_fields ?? []).includes(fieldKey);
  }

  function setHidden(fieldKey: string, hidden: boolean) {
    setProfile((p) => {
      const current = new Set(p.hidden_fields ?? []);
      if (hidden) current.add(fieldKey);
      else current.delete(fieldKey);
      return { ...p, hidden_fields: current.size > 0 ? Array.from(current) : null };
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      // Drop empty-string social links so clearing a field actually
      // removes it instead of persisting "".
      const social_links = profile.social_links
        ? Object.fromEntries(Object.entries(profile.social_links).filter(([, v]) => v))
        : null;
      const cleaned = { ...profile, social_links: Object.keys(social_links ?? {}).length ? social_links : null };
      const updated = await api.updateMyProfile(cleaned);
      setProfile(updated);
      showSuccess("Profile saved.");
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="p-6 text-sm text-muted-foreground">Loading...</p>;

  const initial = (profile.full_name || user?.username || "?").trim().charAt(0).toUpperCase();
  const avatarColor = colorForUsername(user?.username ?? "");

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <div className="flex items-center gap-4">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-2xl font-bold text-white shadow"
          style={{ backgroundColor: avatarColor }}
        >
          {initial}
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Your profile</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {user?.username} &middot; {user?.email}
          </p>
        </div>
      </div>

      {/* Master switch: while off, GET /api/profile/{username} shows nothing
          at all, regardless of any individual field switch below - those
          switches stay exactly as set (see setHidden/isHidden), they just
          stop mattering until sharing is turned back on. */}
      <Card className="mt-6 border-2" style={{ borderColor: profile.is_public ? undefined : "var(--warning)" }}>
        <CardContent className="flex items-center justify-between gap-4 py-4">
          <div className="flex items-center gap-3">
            {profile.is_public ? (
              <Eye className="size-5 text-success" />
            ) : (
              <Lock className="size-5 text-warning-muted-foreground" />
            )}
            <div>
              <p className="text-sm font-semibold">
                {profile.is_public ? "Your profile is visible to other users" : "Your profile is private"}
              </p>
              <p className="text-xs text-muted-foreground">
                {profile.is_public
                  ? "Anyone signed in can view it (e.g. by tapping your name on the Calendar)."
                  : "Nobody can view it until you share it again - your field settings below are kept as-is."}
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant={profile.is_public ? "outline" : "default"}
            size="sm"
            className="shrink-0"
            onClick={() => updateField("is_public", !profile.is_public)}
          >
            {profile.is_public ? "Don't share my profile" : "Share my profile"}
          </Button>
        </CardContent>
      </Card>

      <form onSubmit={handleSubmit} className="mt-6 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <User className="size-4.5 text-muted-foreground" />
              About you
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="full_name">Full name</Label>
              <Input
                id="full_name"
                value={profile.full_name ?? ""}
                onChange={(e) => updateField("full_name", e.target.value || null)}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="school" className="flex items-center gap-1.5">
                    <Building className="size-3.5 text-muted-foreground" /> School
                  </Label>
                  <FieldVisibilityToggle
                    hidden={isHidden("school")}
                    disabledByMaster={!profile.is_public}
                    onChange={(h) => setHidden("school", h)}
                  />
                </div>
                <Input
                  id="school"
                  value={profile.school ?? ""}
                  onChange={(e) => updateField("school", e.target.value || null)}
                  placeholder="Hochschule Bonn-Rhein-Sieg"
                />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="department">Department</Label>
                  <FieldVisibilityToggle
                    hidden={isHidden("department")}
                    disabledByMaster={!profile.is_public}
                    onChange={(h) => setHidden("department", h)}
                  />
                </div>
                <Input
                  id="department"
                  value={profile.department ?? ""}
                  onChange={(e) => updateField("department", e.target.value || null)}
                  placeholder="Electrical Engineering"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="age" className="flex items-center gap-1.5">
                  <Calendar className="size-3.5 text-muted-foreground" /> Age
                </Label>
                <FieldVisibilityToggle
                  hidden={isHidden("age")}
                  disabledByMaster={!profile.is_public}
                  onChange={(h) => setHidden("age", h)}
                />
              </div>
              <Input
                id="age"
                type="number"
                min={14}
                max={120}
                className="max-w-24"
                value={profile.age ?? ""}
                onChange={(e) => updateField("age", e.target.value ? parseInt(e.target.value, 10) : null)}
              />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="bio">Bio</Label>
                <FieldVisibilityToggle
                  hidden={isHidden("bio")}
                  disabledByMaster={!profile.is_public}
                  onChange={(h) => setHidden("bio", h)}
                />
              </div>
              <textarea
                id="bio"
                value={profile.bio ?? ""}
                onChange={(e) => updateField("bio", e.target.value || null)}
                rows={3}
                className="flex w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ExternalLink className="size-4.5 text-muted-foreground" />
              Social media
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {SOCIAL_PLATFORMS.map(({ key, label, placeholder }) => (
              <div key={key} className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor={`social-${key}`}>{label}</Label>
                  <FieldVisibilityToggle
                    hidden={isHidden(`social:${key}`)}
                    disabledByMaster={!profile.is_public}
                    onChange={(h) => setHidden(`social:${key}`, h)}
                  />
                </div>
                <Input
                  id={`social-${key}`}
                  value={profile.social_links?.[key] ?? ""}
                  onChange={(e) => updateSocialLink(key, e.target.value)}
                  placeholder={placeholder}
                />
              </div>
            ))}
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={saving}>
            Save changes
          </Button>
        </div>
      </form>

      {/* Danger zone */}
      <Card className="mt-8 border-2" style={{ borderColor: "var(--destructive)" }}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Trash2 className="h-5 w-5" style={{ color: "var(--destructive)" }} />
            Delete account
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            Permanently delete your account and all of your data, including your reservation history. This
            cannot be undone.
          </p>
          <Button
            type="button"
            variant="destructive"
            className="shrink-0"
            onClick={() => {
              setDeletePassword("");
              setDeleteOpen(true);
            }}
          >
            Delete account
          </Button>
        </CardContent>
      </Card>

      <Dialog
        open={deleteOpen}
        onOpenChange={(open) => {
          if (!deleting) setDeleteOpen(open);
        }}
      >
        <DialogContent>
          <h2 className="text-lg font-semibold">Delete your account?</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            This permanently deletes your account, profile, and all reservation history. Enter your password
            to confirm.
          </p>
          <div className="mt-4 space-y-2">
            <Label htmlFor="delete-password">Password</Label>
            <Input
              id="delete-password"
              type="password"
              value={deletePassword}
              autoComplete="current-password"
              onChange={(e) => setDeletePassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleDeleteAccount();
              }}
            />
          </div>
          <div className="mt-6 flex justify-end gap-2">
            <Button type="button" variant="secondary" disabled={deleting} onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting || !deletePassword}
              onClick={handleDeleteAccount}
            >
              {deleting ? "Deleting…" : "Delete account"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
