/**
 * Sign-in switched off, for a local build only.
 *
 * Set NEXT_PUBLIC_AUTH_DISABLED=1 at build time and the app opens straight on
 * the dashboard: no sign-in or sign-up pages, no sign-out. The browser sends
 * no token and the API answers as its built-in local user — which it does
 * only while ALLOW_ANONYMOUS_API is on, and never in production, where the
 * API refuses it whatever this build says. So this flag cannot open a
 * deployed site; it only stops a local one asking for a password.
 */
export const AUTH_DISABLED =
  process.env.NEXT_PUBLIC_AUTH_DISABLED === "1" || process.env.NEXT_PUBLIC_AUTH_DISABLED === "true";

/** Pages that exist only to sign someone in, sign them up or accept an invitation. */
const SIGN_IN_PAGES = [/^\/login\/?$/, /^\/signup\/?$/, /^\/invite\/?$/, /^\/platform\/(login|join)\/?$/, /^\/w\/[^/]+\/login\/?$/];

export function isSignInPage(pathname: string | null): boolean {
  return !!pathname && SIGN_IN_PAGES.some((re) => re.test(pathname));
}
