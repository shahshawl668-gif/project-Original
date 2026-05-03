import type { Metadata } from "next";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { QueryProvider } from "@/providers/QueryProvider";
import { Toaster } from "@/components/ui/toaster";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const display = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "PayrollCheck — India statutory payroll validation",
  description:
    "Modern PF, ESIC, PT, LWF and tax validation for Indian payroll teams. Audit-grade accuracy, built for HR & finance.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable}`}>
      <body className="font-sans">
        <QueryProvider>
          <AuthProvider>{children}</AuthProvider>
          <Toaster />
        </QueryProvider>
      </body>
    </html>
  );
}
