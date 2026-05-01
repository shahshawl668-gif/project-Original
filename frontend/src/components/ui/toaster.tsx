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
            "rounded-xl border border-slate-200/80 bg-white/95 shadow-card backdrop-blur-sm text-sm",
          title: "font-semibold text-slate-900",
          description: "text-slate-600",
        },
      }}
    />
  );
}
