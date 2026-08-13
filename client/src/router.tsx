import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate } from "react-router";

import { AuthLoading, ProtectedRoute, PublicOnlyRoute } from "@/components/ProtectedRoute";
import { AddFood } from "@/pages/AddFood";
import { Confirm } from "@/pages/Confirm";
import { FoodLog } from "@/pages/FoodLog";
import { Onboarding } from "@/pages/Onboarding";
import { Profile } from "@/pages/Profile";
import { SignIn } from "@/pages/SignIn";
import { TargetReveal } from "@/pages/TargetReveal";
import { Today } from "@/pages/Today";

// Recharts is ~400 kB and used by exactly one screen — a placeholder at that.
// Loading it eagerly would make every cold start pay for a chart nobody has
// navigated to yet.
const Progress = lazy(() => import("@/pages/Progress").then((m) => ({ default: m.Progress })));

function Lazy({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<AuthLoading />}>{children}</Suspense>;
}

export const router = createBrowserRouter([
  {
    element: <PublicOnlyRoute />,
    children: [{ path: "/signin", element: <SignIn /> }],
  },
  {
    element: <ProtectedRoute />,
    children: [
      { path: "/onboarding", element: <Onboarding /> },
      { path: "/onboarding/done", element: <TargetReveal /> },
      { path: "/today", element: <Today /> },
      { path: "/add", element: <AddFood /> },
      { path: "/add/confirm", element: <Confirm /> },
      { path: "/profile", element: <Profile /> },
      // Not in the design yet — placeholders so the routes exist.
      { path: "/log", element: <FoodLog /> },
      {
        path: "/progress",
        element: (
          <Lazy>
            <Progress />
          </Lazy>
        ),
      },
    ],
  },
  { path: "/", element: <Navigate to="/today" replace /> },
  { path: "*", element: <Navigate to="/today" replace /> },
]);
