import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";

import { AuthProvider } from "@/app/providers/AuthProvider";
import { router } from "@/app/router";
import { SkipToContent } from "@/components/SkipToContent";
import { AccessibilityMenu } from "@/features/accessibility";

import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SkipToContent />
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
    <AccessibilityMenu />
  </StrictMode>,
);
