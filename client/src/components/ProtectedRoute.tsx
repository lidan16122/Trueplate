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

export function ProtectedRoute() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  // Rendering the redirect before the check finishes would bounce a
  // legitimately signed-in user to the sign-in screen on every hard refresh.
  if (isLoading) return <AuthLoading />;

  if (!user) {
    // `state.from` lets sign-in return the user where they were headed.
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

export function PublicOnlyRoute() {
  const { user, isLoading } = useAuth();

  if (isLoading) return <AuthLoading />;
  if (user) return <Navigate to="/today" replace />;

  return <Outlet />;
}
