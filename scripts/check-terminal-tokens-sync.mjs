#!/usr/bin/env node
/*
 * scripts/check-terminal-tokens-sync.mjs
 * ========================================
 *
 * Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
 *   §1.2, §Appendix C — Design Token Inventory
 *
 * DRIFT SENTINEL between the two terminal token surfaces:
 *
 *   1. packages/investintell-ui/src/lib/tokens/terminal.css
 *      — the canonical CSS custom-property catalog. The ONLY file
 *        where hex literals are allowed.
 *
 *   2. packages/investintell-ui/src/lib/charts/terminal-options.ts
 *      — `DEFAULT_TOKENS`: the SSR-safe TypeScript mirror used by
 *        `createTerminalChartOptions()`, plus every `readVar(...)`
 *        call that pulls a custom property at runtime.
 *
 * The script enforces three invariants:
 *
 *   A. Every `--terminal-*` referenced via `readVar(style, "...",
 *      ...)` in terminal-options.ts MUST exist in terminal.css.
 *      Catches typos and renames that would leave charts on the
 *      hex fallback silently.
 *
 *   B. Every key declared in `DEFAULT_TOKENS` MUST resolve to a
 *      defined CSS variable (using the camelCase ↔ kebab-case
 *      naming convention, with explicit overrides for the
 *      `dataviz` 8-slot palette and `text*` numeric tokens).
 *      Catches drift where the TS dictionary outgrows the CSS
 *      catalog.
 *
 *   C. Every chart-relevant CSS token group (`bg`, `fg`, `accent`,
 *      `status`, `dataviz`, `font-mono`, `text-*`) declared in
 *      terminal.css MUST be mirrored by a key in `DEFAULT_TOKENS`.
 *      Catches drift in the opposite direction: someone adds a
 *      new accent color in CSS but forgets the SSR fallback.
 *
 * Failure exits with code 1 — wired into pnpm/turbo lint and
 * backend `make check` so PRs cannot land in a drifted state.
 *
 * Pure Node, no dependencies. Runs on the bare runtime.
 */

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..");

const CSS_PATH = resolve(
	REPO_ROOT,
	"packages/investintell-ui/src/lib/tokens/terminal.css",
);
const TS_PATH = resolve(
	REPO_ROOT,
	"packages/investintell-ui/src/lib/charts/terminal-options.ts",
);

// ── Parsing helpers ────────────────────────────────────────

function parseCssTokens(source) {
	// Match `--terminal-<name>: <value>;` declarations. We capture
	// the token name only — values are validated by stylelint, not
	// here. Tokens may be redeclared inside `@media` blocks (the
	// reduced-motion override does this) so we Set-dedupe.
	const tokens = new Set();
	const re = /(--terminal-[a-z0-9-]+)\s*:/g;
	let match;
	while ((match = re.exec(source)) !== null) {
		tokens.add(match[1]);
	}
	return tokens;
}

function parseReadVarReferences(source) {
	// Match `readVar(style, "--terminal-...", fallback)` calls.
	// Both single and double-quoted variants are accepted.
	const refs = new Set();
	const re = /readVar\s*\(\s*[a-zA-Z_$][\w$]*\s*,\s*["'](--terminal-[a-z0-9-]+)["']/g;
	let match;
	while ((match = re.exec(source)) !== null) {
		refs.add(match[1]);
	}
	return refs;
}

function parseDefaultTokensKeys(source) {
	// Slice the literal between `const DEFAULT_TOKENS:` and the
	// closing `};`. We deliberately do not eval — a regex over the
	// declared key names is sufficient and never executes user
	// code. Skips nested arrays (the `dataviz` palette).
	const start = source.indexOf("const DEFAULT_TOKENS");
	if (start === -1) {
		throw new Error("DEFAULT_TOKENS declaration not found in terminal-options.ts");
	}
	const blockStart = source.indexOf("{", start);
	if (blockStart === -1) {
		throw new Error("DEFAULT_TOKENS body { not found");
	}
	let depth = 0;
	let end = blockStart;
	for (let i = blockStart; i < source.length; i++) {
		const ch = source[i];
		if (ch === "{") depth++;
		else if (ch === "}") {
			depth--;
			if (depth === 0) {
				end = i;
				break;
			}
		}
	}
	const body = source.slice(blockStart + 1, end);
	const keys = new Set();
	// Top-level keys only — naive but adequate, since DEFAULT_TOKENS
	// is a flat object plus one inline array (`dataviz: [...]`).
	const re = /(?:^|\n)\s*([a-zA-Z][a-zA-Z0-9]*)\s*:/g;
	let match;
	while ((match = re.exec(body)) !== null) {
		keys.add(match[1]);
	}
	return keys;
}

// ── Naming convention ─────────────────────────────────────

/**
 * Convert a camelCase key from `DEFAULT_TOKENS` into the CSS
 * custom-property name(s) it should resolve to. Returns an array
 * because `dataviz` expands to eight slots.
 */
function keyToCssVars(key) {
	if (key === "dataviz") {
		return [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `--terminal-dataviz-${n}`);
	}
	// Generic: insert "-" between [a-z]→[A-Z] and between
	// [a-zA-Z]→[0-9]. Then lowercase.
	const kebab = key
		.replace(/([a-z])([A-Z])/g, "$1-$2")
		.replace(/([a-zA-Z])(\d)/g, "$1-$2")
		.toLowerCase();
	return [`--terminal-${kebab}`];
}

/**
 * Inverse: given a CSS variable, return the camelCase key the
 * factory would expose, or `null` if the variable is outside the
 * chart-relevant surface (spacing, radii, z-index, motion are
 * all consumed via CSS variables only and have no SSR mirror).
 */
function cssVarToKey(name) {
	const stripped = name.replace(/^--terminal-/, "");
	// Chart-relevant prefixes only. Spacing, radii, motion, z,
	// border, leading, tracking, shell-* are consumed directly
	// from CSS by Svelte components, not from the TS factory.
	const CHART_PREFIXES = ["bg-", "fg-", "accent-", "status-", "dataviz-", "font-mono", "text-"];
	const match = CHART_PREFIXES.some((p) => stripped === p.replace(/-$/, "") || stripped.startsWith(p));
	if (!match) return null;
	// Skip dim variants — `accent-amber-dim` is consumed only by
	// CSS classes, never by ECharts options.
	if (stripped.endsWith("-dim")) return null;
	// Skip the `disabled` and `inverted` foreground tiers and the
	// `neutral` status — never read by the chart factory.
	if (stripped === "fg-disabled" || stripped === "fg-inverted") return null;
	if (stripped === "status-neutral") return null;
	if (stripped === "bg-panel-sunken" || stripped === "bg-overlay" || stripped === "bg-scrim") return null;
	if (stripped === "text-16" || stripped === "text-20" || stripped === "text-24") return null;
	// dataviz palette is collapsed under the array `dataviz` key.
	if (/^dataviz-[1-8]$/.test(stripped)) return "dataviz";
	// Standard kebab → camelCase.
	return stripped.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
}

// ── Main ───────────────────────────────────────────────────

function main() {
	if (!existsSync(CSS_PATH)) {
		console.error(`[token-sync] FATAL: terminal.css not found at ${CSS_PATH}`);
		process.exit(2);
	}
	if (!existsSync(TS_PATH)) {
		console.error(`[token-sync] FATAL: terminal-options.ts not found at ${TS_PATH}`);
		process.exit(2);
	}

	const cssSource = readFileSync(CSS_PATH, "utf8");
	const tsSource = readFileSync(TS_PATH, "utf8");

	const cssTokens = parseCssTokens(cssSource);
	const readVarRefs = parseReadVarReferences(tsSource);
	const defaultKeys = parseDefaultTokensKeys(tsSource);

	const errors = [];

	// ── Invariant A — every readVar reference exists in CSS ──
	for (const ref of readVarRefs) {
		if (!cssTokens.has(ref)) {
			errors.push(`A. readVar references unknown CSS token: ${ref}`);
		}
	}

	// ── Invariant B — every DEFAULT_TOKENS key resolves ──────
	for (const key of defaultKeys) {
		const expected = keyToCssVars(key);
		for (const cssVar of expected) {
			if (!cssTokens.has(cssVar)) {
				errors.push(
					`B. DEFAULT_TOKENS key "${key}" expects CSS token ${cssVar} but it is missing from terminal.css`,
				);
			}
		}
	}

	// ── Invariant C — every chart-relevant CSS token mirrored ─
	const expectedKeys = new Set();
	for (const cssVar of cssTokens) {
		const key = cssVarToKey(cssVar);
		if (key !== null) expectedKeys.add(key);
	}
	for (const expected of expectedKeys) {
		if (!defaultKeys.has(expected)) {
			errors.push(
				`C. CSS catalog exposes a chart-relevant token mapped to DEFAULT_TOKENS key "${expected}" but it is missing from the TypeScript dictionary`,
			);
		}
	}

	if (errors.length > 0) {
		console.error("[token-sync] terminal token drift detected:\n");
		for (const e of errors) console.error(`  - ${e}`);
		console.error(
			`\n[token-sync] FAIL — fix terminal.css or terminal-options.ts so the two surfaces match.`,
		);
		process.exit(1);
	}

	console.log(
		`[token-sync] OK — ${cssTokens.size} CSS tokens, ${readVarRefs.size} readVar references, ${defaultKeys.size} DEFAULT_TOKENS keys are in sync.`,
	);
}

main();
