"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "@/providers/ThemeProvider";

export function Toaster() {
  const { resolved } = useTheme();
  return (
    <SonnerToaster
      position="top-right"
      expand={false}
      richColors
      closeButton
      gap={12}
      theme={resolved}
      toastOptions={{
        classNames: {
          toast:
            "!rounded-2xl !border-ink-200/80 !bg-white !shadow-elevated !backdrop-blur-md text-sm font-sans dark:!border-white/10 dark:!bg-ink-900/95",
          title: "!font-display !font-semibold !text-ink-900 dark:!text-white",
          description: "!text-ink-500 dark:!text-ink-300",
          success:
            "!bg-gradient-to-br !from-success-50 !to-white dark:!from-success-500/15 dark:!to-ink-900/95",
          error:
            "!bg-gradient-to-br !from-danger-50 !to-white dark:!from-danger-500/15 dark:!to-ink-900/95",
          warning:
            "!bg-gradient-to-br !from-warning-50 !to-white dark:!from-warning-500/15 dark:!to-ink-900/95",
          info: "!bg-gradient-to-br !from-brand-50 !to-white dark:!from-brand-500/15 dark:!to-ink-900/95",
        },
      }}
    />
  );
}
