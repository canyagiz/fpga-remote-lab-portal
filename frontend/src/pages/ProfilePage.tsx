import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import * as api from "../api/client";
import { Profile } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

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
};

export default function ProfilePage() {
  const { user } = useAuth();
  const { showError, showSuccess } = useToast();
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Your profile</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {user?.username} &middot; {user?.email}
      </p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">About you</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
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
                <Label htmlFor="school">School</Label>
                <Input
                  id="school"
                  value={profile.school ?? ""}
                  onChange={(e) => updateField("school", e.target.value || null)}
                  placeholder="Hochschule Bonn-Rhein-Sieg"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="department">Department</Label>
                <Input
                  id="department"
                  value={profile.department ?? ""}
                  onChange={(e) => updateField("department", e.target.value || null)}
                  placeholder="Electrical Engineering"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="age">Age</Label>
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
              <Label htmlFor="bio">Bio</Label>
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
            <CardTitle className="text-lg">Social media</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {SOCIAL_PLATFORMS.map(({ key, label, placeholder }) => (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`social-${key}`}>{label}</Label>
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
    </div>
  );
}
