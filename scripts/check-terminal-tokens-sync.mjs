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
 *   D. No forbidden patterns inside the terminal route + component
 *      surfaces. Complements the ESLint formatter rules (which
 *      handle `.toFixed`, `Intl.*`) by catching patterns ESLint
 *      cannot cheaply express: raw hex color literals in `.svelte`
 *      files, client-side persistence (`localStorage` /
 *      `sessionStorage`), native `new EventSource` (auth-header
 *      unsafe — must use `fetch` + `ReadableStream`), and emoji
 *      glyphs (see `feedback_no_emojis.md`). Scoped to the 4
 *      terminal route dirs + shared component dir.
 *
 * Failure exits with code 1 — wired into pnpm/turbo lint and
 * backend `make check` so PRs cannot land in a drifted state.
 *
 * Pure Node, no dependencies. Runs on the bare runtime.
 */

import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, relative, join, extname } from "node:path";

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

	// ── Invariant D — no forbidden patterns in terminal surfaces ──
	const routeScanErrors = scanRouteSurfaces();
	errors.push(...routeScanErrors);

	// ── Invariant E — surface CSS isolation ─────────────────────
	const surfaceErrors = scanSurfaceCssFiles();
	errors.push(...surfaceErrors);

	if (errors.length > 0) {
		console.error("[token-sync] terminal drift detected:\n");
		for (const e of errors) console.error(`  - ${e}`);
		console.error(
			`\n[token-sync] FAIL — fix terminal.css, terminal-options.ts, surfaces/*.css, or the offending terminal route/component files.`,
		);
		process.exit(1);
	}

	console.log(
		`[token-sync] OK — ${cssTokens.size} CSS tokens, ${readVarRefs.size} readVar references, ${defaultKeys.size} DEFAULT_TOKENS keys are in sync; forbidden-pattern + surface-isolation scans passed.`,
	);
}

// ── Invariant E — surface CSS isolation ───────────────────
//
// Every rule declared in packages/investintell-ui/src/lib/styles/
// surfaces/*.css must either (a) override a base --ii-* token that
// exists in tokens.css, (b) define a new --ii-terminal-* namespaced
// token, or (c) live inside a [data-surface="..."] selector block.
//
// Operationalized as a leak check: bare `--netz-*`, `--term-*`,
// `--fg-*`, `--up`, `--down`, `--warn`, `--accent` (and their
// dim/-hot siblings) references or declarations FAIL the scanner.
// These are bundle-native names that belong in docs/ux/Netz Terminal/
// sources only — not in the exported surface CSS.

const SURFACE_CSS_DIR = resolve(
	REPO_ROOT,
	"packages/investintell-ui/src/lib/styles/surfaces",
);

/**
 * Regex for the bundle-native variable prefixes that must not leak
 * into the exported surface CSS. Matches both usage (`var(--X)`) and
 * declaration (`--X:`) positions.
 */
const LEAK_PATTERNS = [
	{ label: "netz-*", re: /--netz-[a-z0-9-]*/g },
	{ label: "term-*", re: /--term-[a-z0-9-]*/g },
	{ label: "fg-*", re: /--fg-[a-z0-9-]*/g },
	{ label: "sev-*", re: /--sev-[a-z0-9-]*/g },
	{ label: "up / up-dim", re: /--up(?:-dim)?\b/g },
	{ label: "down / down-dim", re: /--down(?:-dim)?\b/g },
	{ label: "warn (bare)", re: /--warn\b/g },
	{ label: "accent (bare)", re: /--accent(?:-dim)?\b/g },
	{ label: "info (bare)", re: /--info\b/g },
	{ label: "t-size/row/pad (bare)", re: /--t-(?:size-[a-z]+|row(?:-sm)?|pad)\b/g },
	{ label: "tr-caps (bare)", re: /--tr-caps\b/g },
	{ label: "ease (bare)", re: /--ease\b/g },
];

function scanSurfaceCssFiles() {
	const errors = [];
	if (!existsSync(SURFACE_CSS_DIR)) return errors;
	let entries;
	try {
		entries = readdirSync(SURFACE_CSS_DIR);
	} catch {
		return errors;
	}
	for (const name of entries) {
		if (!name.endsWith(".css")) continue;
		const abs = join(SURFACE_CSS_DIR, name);
		const rel = relative(REPO_ROOT, abs).replaceAll("\\", "/");
		let text;
		try {
			text = readFileSync(abs, "utf8");
		} catch {
			continue;
		}
		// Strip CSS block comments so comment prose mentioning legacy
		// names (--netz-orange, --fg-primary) does not trip the scan.
		const stripped = text.replace(/\/\*[\s\S]*?\*\//g, (block) =>
			block.replace(/[^\n]/g, " "),
		);
		for (const rule of LEAK_PATTERNS) {
			rule.re.lastIndex = 0;
			let m;
			while ((m = rule.re.exec(stripped)) !== null) {
				if (m[0] === "") {
					rule.re.lastIndex++;
					continue;
				}
				const line = offsetToLine(stripped, m.index);
				errors.push(
					`E. ${rel}:${line} bundle-native leak "${m[0]}" (${rule.label}) — rewrite as var(--ii-*) or --ii-terminal-*`,
				);
			}
		}
	}
	return errors;
}

// ── Invariant D — route-dir forbidden-pattern scan ─────────

/**
 * Directories covered by the terminal forbidden-pattern sweep.
 * Paths relative to REPO_ROOT. Must stay in sync with the route
 * surface declared in each terminal parity plan (currently
 * docs/plans/2026-04-19-netz-terminal-parity-builder-macro-screener.md §D.9).
 *
 * PR-4b note: ``(terminal)/portfolio/builder`` is deliberately NOT
 * scanned — that legacy surface is outside the parity target and may
 * be retired in a follow-up. ``(terminal)/allocation`` +
 * ``components/allocation`` are the canonical propose→approve surface.
 */
const ROUTE_SCAN_DIRS = [
	"frontends/wealth/src/routes/(terminal)/portfolio/live",
	"frontends/wealth/src/routes/(terminal)/terminal-screener",
	"frontends/wealth/src/routes/(terminal)/macro",
	"frontends/wealth/src/routes/(terminal)/allocation",
	"frontends/wealth/src/lib/components/terminal",
	"frontends/wealth/src/lib/components/allocation",
];

const SCAN_EXTENSIONS = new Set([".svelte", ".ts"]);
const SKIP_DIR_NAMES = new Set([
	"node_modules",
	".svelte-kit",
	"build",
	"dist",
	".turbo",
]);

/**
 * Each rule returns an array of `{ line, match }` hits against the
 * file's text. `.svelte`-only rules are gated by `svelteOnly: true`.
 * Patterns already enforced by ESLint (`.toFixed`, `.toLocaleString`,
 * `new Intl.*`) are deliberately NOT duplicated here.
 */
const FORBIDDEN_PATTERNS = [
	{
		label: "hex color literal",
		svelteOnly: true,
		re: /#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b/g,
		note: "use --terminal-* CSS custom property",
	},
	{
		label: "localStorage",
		// Match real access only (`.foo`, `[...]`, or `()`) to avoid
		// flagging the word inside "Zero localStorage" comments.
		re: /\blocalStorage\s*(?:\.|\[|\()/g,
		note: "terminal surfaces are in-memory only (see feedback_echarts_no_localstorage.md)",
	},
	{
		label: "sessionStorage",
		re: /\bsessionStorage\s*(?:\.|\[|\()/g,
		note: "terminal surfaces are in-memory only",
	},
	{
		label: "new EventSource",
		re: /new\s+EventSource\s*\(/g,
		note: "use fetch() + ReadableStream (auth headers required)",
	},
	{
		label: "emoji glyph",
		// Actual pictograph planes only — Misc Symbols & Pictographs
		// + Supplemental + Dingbats. Deliberately excludes Misc
		// Technical (U+2300-23FF, e.g. ⌘ ⏎ ⌥) and Arrows, which are
		// legitimate keyboard glyphs in Kbd components.
		re: /[\u{1F300}-\u{1F6FF}\u{1F900}-\u{1FAFF}\u{2700}-\u{27BF}]/gu,
		note: "terminal is text-only (see feedback_no_emojis.md)",
	},
];

function scanRouteSurfaces() {
	const errors = [];
	for (const relDir of ROUTE_SCAN_DIRS) {
		const absDir = resolve(REPO_ROOT, relDir);
		if (!existsSync(absDir)) continue; // dir may not exist yet — routes land per-PR
		for (const absFile of walkFiles(absDir)) {
			const ext = extname(absFile);
			if (!SCAN_EXTENSIONS.has(ext)) continue;
			const rel = relative(REPO_ROOT, absFile).replaceAll("\\", "/");
			const text = readFileSync(absFile, "utf8");
			for (const rule of FORBIDDEN_PATTERNS) {
				if (rule.svelteOnly && ext !== ".svelte") continue;
				const hits = findHits(text, rule.re, ext);
				for (const hit of hits) {
					errors.push(
						`D. ${rel}:${hit.line} forbidden ${rule.label} "${hit.match}" — ${rule.note}`,
					);
				}
			}
		}
	}
	return errors;
}

function walkFiles(absDir) {
	const out = [];
	const stack = [absDir];
	while (stack.length) {
		const current = stack.pop();
		let entries;
		try {
			entries = readdirSync(current);
		} catch {
			continue;
		}
		for (const name of entries) {
			if (SKIP_DIR_NAMES.has(name)) continue;
			const abs = join(current, name);
			let st;
			try {
				st = statSync(abs);
			} catch {
				continue;
			}
			if (st.isDirectory()) stack.push(abs);
			else if (st.isFile()) out.push(abs);
		}
	}
	return out;
}

function findHits(text, re, ext) {
	const hits = [];
	// For .svelte files we must skip the <style> block: hex literals
	// are legitimate inside scoped component styles since Svelte's
	// scoped CSS output is not the token catalog. We only enforce the
	// no-hex rule in script + template regions.
	const scanText = ext === ".svelte" ? stripStyleBlocks(text) : text;
	re.lastIndex = 0;
	let m;
	while ((m = re.exec(scanText)) !== null) {
		if (m[0] === "") {
			re.lastIndex++;
			continue;
		}
		hits.push({
			line: offsetToLine(scanText, m.index),
			match: m[0],
		});
	}
	return hits;
}

function stripStyleBlocks(text) {
	// Replace <style ...>...</style> with equivalent-length blanks so
	// line numbers stay accurate for reports.
	return text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, (block) =>
		block.replace(/[^\n]/g, " "),
	);
}

function offsetToLine(text, offset) {
	let line = 1;
	for (let i = 0; i < offset && i < text.length; i++) {
		if (text[i] === "\n") line++;
	}
	return line;
}

main();
