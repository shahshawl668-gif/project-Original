"use client";

import { Toaster as SonnerToaster } from "sonner";

export function Toaster() {
  return (
    <SonnerToaster
      position="top-right"
      expand={false}
      richColors
      closeButton
      gap={12}
      toastOptions={{
        classNames: {
          toast:
            "!rounded-2xl !border-ink-200/80 !bg-white !shadow-elevated !backdrop-blur-md text-sm font-sans",
          title: "!font-display !font-semibold !text-ink-900",
          description: "!text-ink-500",
          success: "!bg-gradient-to-br !from-success-50 !to-white",
          error: "!bg-gradient-to-br !from-danger-50 !to-white",
          warning: "!bg-gradient-to-br !from-warning-50 !to-white",
          info: "!bg-gradient-to-br !from-brand-50 !to-white",
        },
      }}
    />
  );
}
