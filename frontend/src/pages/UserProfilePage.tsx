import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import * as api from "../api/client";
import { PublicProfile } from "../api/types";
import { useToast } from "../context/ToastContext";

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

  const socialEntries = Object.entries(profile.social_links ?? {}).filter(([, v]) => v);

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">{profile.full_name || profile.username}</h1>
      <p className="mt-1 text-sm text-muted-foreground">@{profile.username}</p>

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
