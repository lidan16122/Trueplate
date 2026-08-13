import { createBrowserRouter, Navigate } from "react-router";

import { ProtectedRoute, PublicOnlyRoute } from "@/components/ProtectedRoute";
import { Eyebrow } from "@/components/ui";
import { SignIn } from "@/pages/SignIn";

/**
 * Placeholder for a screen that lands in the next change.
 *
 * These exist so sign-in has somewhere to land. Without them the destinations
 * `SignIn` navigates to fall through to the catch-all, which sends the user to
 * `/signin`, where `PublicOnlyRoute` sees a signed-in user and bounces them
 * straight back — an infinite redirect on every successful sign-in.
 */
function ComingSoon({ name }: { name: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-page">
      <Eyebrow>{name}</Eyebrow>
      <p className="text-caption text-subtle">This screen lands in the next change.</p>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    element: <PublicOnlyRoute />,
    children: [{ path: "/signin", element: <SignIn /> }],
  },
  {
    element: <ProtectedRoute />,
    children: [
      { path: "/today", element: <ComingSoon name="Today" /> },
      { path: "/onboarding", element: <ComingSoon name="Onboarding" /> },
    ],
  },
  { path: "/", element: <Navigate to="/today" replace /> },
  { path: "*", element: <Navigate to="/today" replace /> },
]);
