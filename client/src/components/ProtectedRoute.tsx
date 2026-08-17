import { Suspense } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "@/auth/useAuth";
import { Eyebrow } from "@/components/ui";

/** Full-page hold while the initial session check settles. */
export function AuthLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-page">
      <Eyebrow>Trueplate</Eyebrow>
    </div>
  );
}

/**
 * Where a signed-in user belongs.
 *
 * Single source of truth for the post-auth destination. Both guards read it, so
 * they cannot disagree — which they previously did: SignIn navigated to the
 * wizard while PublicOnlyRoute sent every authenticated user to /today, and the
 * `await` between setting the user and navigating let /today win.
 */
function homeFor(needsOnboarding: boolean): string {
  return needsOnboarding ? "/onboarding" : "/today";
}

export function ProtectedRoute() {
  const { user, isLoading, needsOnboarding } = useAuth();
  const location = useLocation();

  // Rendering the redirect before the check finishes would bounce a
  // legitimately signed-in user to the sign-in screen on every hard refresh.
  if (isLoading) return <AuthLoading />;

  if (!user) {
    // `state.from` lets sign-in return the user where they were headed.
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }

  // The wizard is the whole app until it is done: a user with no profile has no
  // targets, so every other screen would render against zeroes. Enforced here
  // rather than at sign-in so it survives a reload and a half-finished wizard.
  // The wizard carries its own sign-out, because this redirect covers /profile
  // too — and a user on the wrong Google account must still be able to leave.
  if (needsOnboarding && !location.pathname.startsWith("/onboarding")) {
    return <Navigate to={homeFor(needsOnboarding)} replace />;
  }

  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { user, isLoading, needsOnboarding } = useAuth();

  if (isLoading) return <AuthLoading />;
  if (user) return <Navigate to={homeFor(needsOnboarding)} replace />;

  return <Outlet />;
}

/**
 * Suspense boundary for a route-level lazy import.
 *
 * Beside AuthLoading, which is its fallback, and out of the router so that file
 * exports only the router — a module mixing a component with a non-component
 * export defeats fast refresh for everything in it.
 */
export function Lazy({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<AuthLoading />}>{children}</Suspense>;
}
