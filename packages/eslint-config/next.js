import { globalIgnores } from "eslint/config"
import pluginNext from "@next/eslint-plugin-next"
import pluginReactHooks from "eslint-plugin-react-hooks"
import globals from "globals"

import { config as baseConfig } from "./base.js"

/**
 * A custom ESLint configuration for libraries that use Next.js.
 *
 * @type {import("eslint").Linter.Config[]}
 */
export const nextJsConfig = [
  ...baseConfig,
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.serviceworker,
      },
    },
  },
  {
    plugins: {
      "@next/next": pluginNext,
    },
    rules: {
      ...pluginNext.configs.recommended.rules,
      ...pluginNext.configs["core-web-vitals"].rules,
    },
  },
  pluginReactHooks.configs.flat.recommended,
  {
    rules: {
      // Pages load their data in the browser (static export, no server
      // components), so "set state from an effect after fetching" is the
      // app's standard pattern (hooks/use-api.ts and every view). This rule
      // flags every such load plus the "reset form when the dialog opens"
      // effects, and the alternatives need a data library the app doesn't use.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]
