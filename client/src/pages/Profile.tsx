import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import { useAuth } from "@/auth/useAuth";
import { ErrorNote, Eyebrow, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { GOAL_OPTIONS, SEX_OPTIONS } from "@/lib/labels";
import type { Profile as ProfileData, Session, Targets } from "@/types/api";

export function Profile() {
  const { user, signOut, refreshUser } = useAuth();
  const navigate = useNavigate();

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [targets, setTargets] = useState<Targets | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void Promise.allSettled([
      api.profile.read().then(setProfile),
      api.profile.targets().then(setTargets),
      api.auth.sessions().then((r) => setSessions(r.sessions)),
    ]);
  }, []);

  /** Every field here feeds the target, so each save returns the new breakdown. */
  const save = useCallback(async (patch: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      setTargets(await api.profile.update(patch));
      setProfile(await api.profile.read());
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

  const revoke = useCallback(async (familyId: string) => {
    await api.auth.revokeSession(familyId);
    setSessions((prev) => prev.filter((s) => s.family_id !== familyId));
  }, []);

  const numberField = (
    label: string,
    value: number | null | undefined,
    unit: string,
    field: string,
    step = 1,
  ) => (
    <label key={field} className="flex flex-col gap-1.5">
      <span className="text-caption text-muted">{label}</span>
      <span className="flex items-center gap-2">
        <input
          type="number"
          step={step}
          defaultValue={value ?? ""}
          onBlur={(e) => {
            const parsed = Number.parseFloat(e.target.value);
            if (!Number.isNaN(parsed) && parsed !== value) void save({ [field]: parsed });
          }}
          className="tabular h-13 w-full rounded-card border border-line bg-surface px-4 font-mono text-lead text-ink outline-none focus:border-accent"
        />
        <span className="w-8 flex-none text-caption text-subtle">{unit}</span>
      </span>
    </label>
  );

  return (
    <div className="min-h-dvh bg-page">
      <header className="flex items-center justify-between border-b border-line-2 bg-surface px-6 py-4 md:px-8">
        <h1 className="text-[18px] font-semibold text-ink">Profile</h1>
        <button
          onClick={() => navigate("/today")}
          className="text-caption text-muted transition-colors hover:text-ink"
        >
          Done
        </button>
      </header>

      <main className="mx-auto flex w-full max-w-[760px] flex-col gap-10 px-6 py-8 md:px-8">
        {error && <ErrorNote>{error}</ErrorNote>}

        {/* Target */}
        {targets && (
          <section className="flex flex-col gap-2">
            <Eyebrow>Daily target</Eyebrow>
            <div className="flex items-baseline gap-3">
              <Stat value={targets.target_calories.toLocaleString()} size={52} />
              <span className="text-body text-subtle">kcal</span>
            </div>
            <p className="tabular font-mono text-caption text-muted">
              {targets.protein_g} P · {targets.carbs_g} C · {targets.fat_g} F
            </p>
          </section>
        )}

        {/* The design has no tab bar, so these two live here. Without a link
            from somewhere they are reachable only by typing the URL. */}
        <section className="flex flex-col gap-2">
          <Eyebrow>More</Eyebrow>
          <nav className="flex flex-col rounded-lg border border-line">
            {[
              { to: "/log", label: "Food log", note: "Everything logged, by day" },
              { to: "/progress", label: "Progress", note: "Weight trend and adherence" },
            ].map((item, i) => (
              <Link
                key={item.to}
                to={item.to}
                className={`flex items-baseline justify-between gap-4 px-5 py-3.5 transition-colors hover:bg-wash ${
                  i > 0 ? "border-t border-line-2" : ""
                }`}
              >
                <span className="text-caption text-ink">{item.label}</span>
                <span className="text-caption text-subtle">{item.note}</span>
              </Link>
            ))}
          </nav>
        </section>

        {/* Account */}
        <section className="flex flex-col gap-4">
          <Eyebrow>Account</Eyebrow>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-caption text-muted">First name</span>
              <input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                onBlur={() =>
                  firstName !== user?.first_name && void save({ first_name: firstName })
                }
                className="h-13 rounded-card border border-line bg-surface px-4 text-lead text-ink outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-caption text-muted">Last name</span>
              <input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                onBlur={() => lastName !== user?.last_name && void save({ last_name: lastName })}
                className="h-13 rounded-card border border-line bg-surface px-4 text-lead text-ink outline-none focus:border-accent"
              />
            </label>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-caption text-muted">Email (from Google, not editable)</span>
            <input
              value={user?.email ?? ""}
              readOnly
              className="h-13 cursor-default rounded-card border border-line bg-readonly px-4 text-lead text-subtle outline-none"
            />
          </label>
        </section>

        {/* Body */}
        <section className="flex flex-col gap-4">
          <Eyebrow>Body</Eyebrow>
          <div className="flex flex-wrap gap-2">
            {SEX_OPTIONS.map((option) => {
              const selected = profile?.sex === option.id;
              return (
                <button
                  key={option.id}
                  onClick={() => void save({ sex: option.id })}
                  className={`h-11 rounded-card border px-5 text-body transition-colors ${
                    selected
                      ? "border-ink bg-ink text-white"
                      : "border-line bg-surface text-muted hover:border-ink"
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {numberField("Age", profile?.age, "yr", "age")}
            {numberField("Height", profile?.height_cm, "cm", "height_cm")}
            {numberField("Weight", profile?.weight_kg, "kg", "weight_kg", 0.5)}
          </div>
        </section>

        {/* Goal */}
        <section className="flex flex-col gap-4">
          <Eyebrow>Goal</Eyebrow>
          <div className="flex flex-col gap-2">
            {GOAL_OPTIONS.map((option) => {
              const selected = targets?.goal_type === option.id;
              return (
                <button
                  key={option.id}
                  onClick={() => void save({ goal_type: option.id })}
                  disabled={saving}
                  className={`h-13 rounded-card border px-5 text-left text-caption transition-colors ${
                    selected
                      ? "border-ink bg-ink text-white"
                      : "border-line bg-surface text-muted hover:border-ink"
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
          {targets && targets.goal_type !== "maintain" && (
            <div className="md:max-w-[240px]">
              {numberField(
                "Target weight",
                targets.target_weight_kg,
                "kg",
                "target_weight_kg",
                0.5,
              )}
            </div>
          )}
        </section>

        {/* Devices — the refresh-token families, made visible. */}
        {sessions.length > 0 && (
          <section className="flex flex-col gap-4">
            <Eyebrow>Signed in on</Eyebrow>
            <ul className="flex flex-col gap-2">
              {sessions.map((session) => (
                <li
                  key={session.family_id}
                  className="flex items-center justify-between gap-4 rounded-card border border-line bg-surface px-4 py-3"
                >
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate text-body text-ink">
                      {session.device_label}
                      {session.is_current && (
                        <span className="ml-2 text-label text-accent">this device</span>
                      )}
                    </span>
                    {session.ip && (
                      <span className="font-mono text-label text-faint">{session.ip}</span>
                    )}
                  </div>
                  {!session.is_current && (
                    <button
                      onClick={() => void revoke(session.family_id)}
                      className="flex-none text-caption text-muted transition-colors hover:text-warn"
                    >
                      Sign out
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        <button
          onClick={handleSignOut}
          className="h-13 rounded-card border border-line text-caption text-muted transition-colors hover:border-warn hover:text-warn"
        >
          Sign out
        </button>
      </main>
    </div>
  );
}
