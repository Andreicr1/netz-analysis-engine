import tseslint from "typescript-eslint";
import { netzFormatterRules } from "../eslint.config.js";

export default [tseslint.configs.base, ...netzFormatterRules];
