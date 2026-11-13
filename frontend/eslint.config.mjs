// ESLint flat config. eslint-config-next 16 ships flat configs itself, and
// Next 16 has no `next lint`, so the project lints with the ESLint CLI.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  { ignores: [".next/**", "node_modules/**", "out/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  {
    rules: {
      // Pages here load their data in an effect (`void load()`), and the
      // loader sets state when the answer arrives. The rule reads that as a
      // synchronous setState. Moving 30-odd loaders to another pattern is its
      // own piece of work, not part of a framework upgrade.
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default config;
