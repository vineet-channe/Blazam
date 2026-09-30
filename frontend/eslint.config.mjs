import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // react-three-fiber mutates three.js objects (uniforms, transforms) inside useFrame, outside
    // React's render; that is the library's intended per-frame model, not React state mutation.
    files: ["src/scene/**/*.{ts,tsx}"],
    rules: { "react-hooks/immutability": "off" },
  },
  { ignores: ["e2e/.audio/**", ".scratch/**", "playwright-report/**", "test-results/**"] },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
