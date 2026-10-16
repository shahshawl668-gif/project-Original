// ESLint 9 flat config. eslint-config-next 15 still ships the legacy format,
// so FlatCompat reads it; `next lint` is deprecated in Next 15.5 and the
// project lints with the ESLint CLI instead. ESLint 10 waits for Next 16:
// eslint-config-next 15 fails to load under it.
import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "out/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals"),
];

export default config;
