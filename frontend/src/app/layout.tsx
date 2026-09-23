import { PRODUCT_DESCRIPTION, PRODUCT_TITLE } from "@/lib/brand";
import type { Metadata } from "next";
import Script from "next/script";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { EntityProvider } from "@/context/EntityContext";
import { QueryProvider } from "@/providers/QueryProvider";
import { ThemeProvider } from "@/providers/ThemeProvider";
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
  title: PRODUCT_TITLE,
  description: PRODUCT_DESCRIPTION,
};

// The product is light-only: white surfaces, sky-blue accents, one set of
// colours to get right. This clears the `dark` class and any theme a browser
// still remembers from before, so a returning visitor is not left on a theme
// the product no longer maintains. The `dark:` variants in the markup stay
// harmlessly inert rather than being stripped from several hundred files.
const themeBootScript = `(function(){try{document.documentElement.classList.remove('dark');document.documentElement.style.colorScheme='light';localStorage.removeItem('payroll_saas_theme');}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable}`} suppressHydrationWarning>
      <head>
        <Script id="theme-boot" strategy="beforeInteractive">
          {themeBootScript}
        </Script>
      </head>
      <body className="font-sans">
        <ThemeProvider>
          <QueryProvider>
            <AuthProvider>
              <EntityProvider>{children}</EntityProvider>
            </AuthProvider>
            <Toaster />
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
