import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import * as api from "../api/client";
import { PublicProfile } from "../api/types";
import { useToast } from "../context/ToastContext";
import { colorForUsername } from "../lib/colors";

const SOCIAL_LABELS: Record<string, string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  instagram: "Instagram",
  x: "X / Twitter",
  website: "Website",
};

export default function UserProfilePage() {
  const { username } = useParams<{ username: string }>();
  const { showError } = useToast();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setNotFound(false);
    api
      .getUserProfile(username)
      .then(setProfile)
      .catch((err) => {
        if (err instanceof api.ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          showError(err instanceof api.ApiError ? err.message : "Failed to load profile");
        }
      })
      .finally(() => setLoading(false));
  }, [username]);

  if (loading) return <p className="p-6 text-sm text-muted-foreground">Loading...</p>;
  if (notFound || !profile) {
    return <p className="p-6 text-sm text-muted-foreground">No user found with that username.</p>;
  }

  const avatarColor = colorForUsername(profile.username);
  const initial = (profile.full_name || profile.username).trim().charAt(0).toUpperCase();

  if (!profile.is_public) {
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
            <h1 className="text-2xl font-bold tracking-tight">@{profile.username}</h1>
          </div>
        </div>
        <Card className="mt-8">
          <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
            <Lock className="size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">This user hasn't chosen to share their profile.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const socialEntries = Object.entries(profile.social_links ?? {}).filter(([, v]) => v);

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
          <h1 className="text-2xl font-bold tracking-tight">{profile.full_name || profile.username}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">@{profile.username}</p>
        </div>
      </div>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle className="text-lg">About</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {profile.school && (
            <p>
              <span className="text-muted-foreground">School:</span> {profile.school}
            </p>
          )}
          {profile.department && (
            <p>
              <span className="text-muted-foreground">Department:</span> {profile.department}
            </p>
          )}
          {profile.bio && <p className="whitespace-pre-wrap">{profile.bio}</p>}
          {!profile.school && !profile.department && !profile.bio && (
            <p className="text-muted-foreground">This user hasn't added any details yet.</p>
          )}
        </CardContent>
      </Card>

      {socialEntries.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="text-lg">Social media</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {socialEntries.map(([key, value]) => (
              <p key={key}>
                <span className="text-muted-foreground">{SOCIAL_LABELS[key] ?? key}:</span>{" "}
                <a href={value} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                  {value}
                </a>
              </p>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
