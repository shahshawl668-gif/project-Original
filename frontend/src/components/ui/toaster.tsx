"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "@/providers/ThemeProvider";

/**
 * Bottom-right, where it covers nothing: at the top right it sat over the
 * company switcher and the profile menu — the controls someone reaches for
 * right after an action completes.
 */
export function Toaster() {
  const { resolved } = useTheme();
  return (
    <SonnerToaster
      position="bottom-right"
      expand={false}
      richColors
      closeButton
      gap={8}
      duration={5000}
      theme={resolved}
      toastOptions={{
        classNames: {
          toast: "!rounded-xl !border-ink-200 !bg-white !shadow-elevated text-sm font-sans",
          title: "!font-semibold !text-ink-900",
          description: "!text-ink-600",
          success: "!bg-success-50 !border-success-200",
          error: "!bg-danger-50 !border-danger-200",
          warning: "!bg-warning-50 !border-warning-200",
          info: "!bg-brand-50 !border-brand-200",
        },
      }}
    />
  );
}
