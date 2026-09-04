import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    ".next-api/**",
    ".next-front/**",
    "__MACOSX/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "ui-prototype/**",
    "browser-extension/**",
    "deploy/**",
    "tmp/**",
    "output/**",
    "scratch/**",
  ]),
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "@next/next/no-img-element": "warn",
    },
  },
]);

export default eslintConfig;
