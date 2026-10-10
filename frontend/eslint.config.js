import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

// MVP-8.3: минимальная конфигурация (рекомендованные наборы + правила хуков).
export default tseslint.config(
  { ignores: ["dist", "node_modules", "public"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    // Только классические правила хуков: набор recommended у react-hooks 7
    // включает правила React Compiler (set-state-in-effect и др.), которые
    // потребовали бы массовой переработки существующего кода — вне объёма MVP-8.3.
    rules: { "react-hooks/rules-of-hooks": "error", "react-hooks/exhaustive-deps": "warn" },
  },
  { files: ["scripts/**/*.mjs", "*.config.js"], languageOptions: { globals: { ...globals.node } }, extends: [js.configs.recommended] },
);
