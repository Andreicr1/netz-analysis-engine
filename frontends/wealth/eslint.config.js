import tseslint from "typescript-eslint";
import { netzFormatterRules, netzTerminalRules } from "../eslint.config.js";

export default [tseslint.configs.base, ...netzFormatterRules, ...netzTerminalRules];
