/**
 * @investintell/eslint-plugin-netz-runtime
 *
 * ESLint plugin enforcing the Netz Stability Guardrails runtime
 * primitives. See the package README and
 * `docs/reference/stability-guardrails.md` for the full charter.
 *
 * Exports the four rules listed in §5.2 of the design spec:
 *
 * - no-unsafe-derived            (P4, error)
 * - require-load-timeout         (P6, error)
 * - require-tick-buffer-dispose  (P4, error)
 * - require-svelte-boundary      (P3, warn in v1)
 */

import noUnsafeDerived from "./rules/no-unsafe-derived.js";
import requireLoadTimeout from "./rules/require-load-timeout.js";
import requireSvelteBoundary from "./rules/require-svelte-boundary.js";
import requireTickBufferDispose from "./rules/require-tick-buffer-dispose.js";

const plugin = {
	meta: {
		name: "@investintell/eslint-plugin-netz-runtime",
		version: "0.1.0",
	},
	rules: {
		"no-unsafe-derived": noUnsafeDerived,
		"require-load-timeout": requireLoadTimeout,
		"require-tick-buffer-dispose": requireTickBufferDispose,
		"require-svelte-boundary": requireSvelteBoundary,
	},
	configs: {
		recommended: {
			rules: {
				"@investintell/netz-runtime/no-unsafe-derived": "error",
				"@investintell/netz-runtime/require-load-timeout": "error",
				"@investintell/netz-runtime/require-tick-buffer-dispose": "error",
				"@investintell/netz-runtime/require-svelte-boundary": "warn",
			},
		},
	},
};

export default plugin;
export const rules = plugin.rules;
export const configs = plugin.configs;
