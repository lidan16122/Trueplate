import { useAuth } from "@/hooks/useAuth";
import { profileApi } from "@/services/profile";
import type { Profile as ProfileData, Targets } from "@/types/profile";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";


/** Coordinates profile writes and dependent reads so the account and target displays stay together. */
export function useProfile() {
  const { user, signOut, refreshUser } = useAuth();
  const navigate = useNavigate();

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [targets, setTargets] = useState<Targets | null>(null);
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void Promise.allSettled([
      profileApi.read().then(setProfile),
      profileApi.targets().then(setTargets),
    ]);
  }, []);

  /** Every field here feeds the target, so each save returns the new breakdown. */
  const save = useCallback(async (patch: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      setTargets(await profileApi.update(patch));
      setProfile(await profileApi.read());
      await refreshUser();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }, [refreshUser]);

  const handleSignOut = useCallback(async () => {
    await signOut();
    navigate("/signin", { replace: true });
  }, [signOut, navigate]);


  return {
    user,
    navigate,
    profile,
    targets,
    firstName,
    setFirstName,
    lastName,
    setLastName,
    error,
    saving,
    save,
    handleSignOut,
  };
}
