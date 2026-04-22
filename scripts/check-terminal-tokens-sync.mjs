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
 *   H. The standalone terminal frontend and ii-terminal-core package
 *      MUST NOT reach back into the wealth frontend. Terminal-owned
 *      code consumes shared components, stores, state, types, utils,
 *      api, and constants via `@investintell/ii-terminal-core` and
 *      `@investintell/ui`. Imports through local app aliases or path
 *      references to the wealth frontend FAIL this invariant.
 *
 *   G. User-visible strings in terminal chrome (top nav brand,
 *      status bar brand, aria-labels, alt, placeholder, title
 *      attributes, and visible text nodes) MUST NOT contain the
 *      hardcoded tenant name "Netz" / "NETZ". Product chrome
 *      defaults to "II" (InvestIntell); tenant branding comes in
 *      at runtime via the orgName prop from the Clerk actor.
 *      Comments, context keys ("netz:getToken"), and path
 *      references to docs/ux/Netz Terminal/ are explicitly
 *      whitelisted — they are not user-visible strings.
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

	// ── Invariant F — terminal routes must not use shadcn classes ─
	const terminalShadcnErrors = scanTerminalRoutesForShadcn();
	errors.push(...terminalShadcnErrors);

	// ── Invariant H — terminal/core must not depend on wealth ───
	const wealthIsolationErrors = scanTerminalForWealthCoupling();
	errors.push(...wealthIsolationErrors);

	// ── Invariant G — no hardcoded Netz in user-visible chrome ──
	const brandErrors = scanChromeBrandLeaks();
	errors.push(...brandErrors);

	if (errors.length > 0) {
		console.error("[token-sync] terminal drift detected:\n");
		for (const e of errors) console.error(`  - ${e}`);
		console.error(
			`\n[token-sync] FAIL — fix terminal.css, terminal-options.ts, surfaces/*.css, frontends/terminal/src/, or the offending terminal route/component files.`,
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

// ── Invariant F — shadcn semantic classes in terminal routes ──
//
// The terminal app at frontends/terminal/ is a pure terminal-native
// surface: IBM Plex Mono, navy/orange bundle palette, zero shadcn
// dependency. Shadcn semantic Tailwind classes (bg-card, text-
// foreground, border-border, text-primary, hover:bg-accent/30 etc.)
// render transparent-on-transparent there because the shadcn CSS
// layer is not loaded — the X3 visual migration ports the palette
// via surfaces/*.css, not via shadcn's own stylesheet.
//
// Any `.svelte` file under frontends/terminal/src/routes/** that
// uses a shadcn class FAILS this invariant. The fix is a terminal-
// native component (see frontends/terminal/src/lib/components/**)
// or the bundle's .bd-* / .mc-* / .ts-* surface classes.

const TERMINAL_ROUTES_DIR = resolve(
	REPO_ROOT,
	"frontends/terminal/src/routes",
);

/**
 * Shadcn semantic class patterns. We match them as whole-word CSS
 * class tokens so we don't trip on user-authored class names that
 * happen to contain these substrings ("my-custom-foreground" etc.).
 * The `\b` word-boundary on each side + the HTML-attribute context
 * (either class="..." or class:foo={...}) is enforced by only scanning
 * matches inside class attribute strings (see scanClassAttributes).
 */
const SHADCN_CLASS_PATTERNS = [
	// Backgrounds
	"bg-card",
	"bg-card-foreground",
	"bg-popover",
	"bg-popover-foreground",
	"bg-primary",
	"bg-primary-foreground",
	"bg-secondary",
	"bg-secondary-foreground",
	"bg-muted",
	"bg-muted-foreground",
	"bg-accent",
	"bg-accent-foreground",
	"bg-destructive",
	"bg-destructive-foreground",
	"bg-success",
	"bg-success-foreground",
	"bg-warning",
	// Text
	"text-foreground",
	"text-muted-foreground",
	"text-card-foreground",
	"text-popover-foreground",
	"text-primary",
	"text-primary-foreground",
	"text-secondary",
	"text-secondary-foreground",
	"text-accent",
	"text-accent-foreground",
	"text-destructive",
	"text-destructive-foreground",
	"text-success",
	"text-warning",
	// Borders
	"border-border",
	"border-input",
	"border-primary",
	"border-destructive",
	"ring-ring",
	"ring-offset-background",
];

function scanTerminalRoutesForShadcn() {
	const errors = [];
	if (!existsSync(TERMINAL_ROUTES_DIR)) return errors;

	for (const absFile of walkFiles(TERMINAL_ROUTES_DIR)) {
		if (extname(absFile) !== ".svelte") continue;
		const rel = relative(REPO_ROOT, absFile).replaceAll("\\", "/");
		let text;
		try {
			text = readFileSync(absFile, "utf8");
		} catch {
			continue;
		}
		// Strip <style> blocks: scoped component CSS uses its own
		// class names and is not subject to this rule.
		const scanText = stripStyleBlocks(text);

		for (const cls of SHADCN_CLASS_PATTERNS) {
			// Match the class token inside a class="..." attribute or a
			// bare string — require a non-alphanumeric boundary on each
			// side (permitting slashes for Tailwind opacity modifiers,
			// e.g. "bg-accent/30", and colons for hover/focus etc.).
			const escaped = cls.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&");
			const re = new RegExp(
				`(?<![A-Za-z0-9_-])${escaped}(?:\\/[0-9]{1,3})?(?![A-Za-z0-9_-])`,
				"g",
			);
			let m;
			while ((m = re.exec(scanText)) !== null) {
				const line = offsetToLine(scanText, m.index);
				errors.push(
					`F. ${rel}:${line} forbidden shadcn class "${m[0]}" — use terminal-native CSS via surfaces/*.css or var(--terminal-*)`,
				);
			}
		}
	}
	return errors;
}

// ── Invariant G — chrome brand-leak scan ──────────────────
//
// The terminal app + shared terminal component surface must not carry
// hardcoded "Netz" / "NETZ" in any user-visible string. "Netz" is a
// tenant (injected at runtime via the orgName prop from the Clerk
// actor), not the product brand. Product chrome defaults to "II".
//
// Scan targets:
//   1. frontends/terminal/src/**/*.{svelte,ts,html}
//   2. frontends/wealth/src/lib/components/terminal/**/*.{svelte,ts}
//        — these components are shared via $wealth/* into the II
//          terminal app, so any hardcoded Netz bleeds into the
//          product chrome.
//   3. A small allowlist of additional wealth components that render
//      Score/brand labels into the terminal surface.
//
// For each file we strip comments (//, /* */, <!-- -->) and <style>
// blocks, then match:
//   - `>…Netz…<` visible text nodes
//   - `aria-label="…Netz…"`, `alt="…Netz…"`, `placeholder="…Netz…"`,
//     `title="…Netz…"`
//   - bare "Netz" / "NETZ" string literals in scripts (single or
//     double-quoted; backtick templates included)
// A narrow whitelist lets through `netz:getToken` (context key —
// internal app IP, not user-visible) and literal path references to
// `docs/ux/Netz Terminal/`.

const CHROME_SCAN_ROOTS = [
	"frontends/terminal/src",
	"frontends/wealth/src/lib/components/terminal",
	"frontends/wealth/src/lib/components/research/terminal",
];

const CHROME_SCAN_FILES = [
	"frontends/wealth/src/lib/components/portfolio/FundDetailsDrawer.svelte",
	"frontends/wealth/src/lib/components/screener/FundFactSheetContent.svelte",
];

const CHROME_SCAN_EXTENSIONS = new Set([".svelte", ".ts", ".html"]);

/** Strip // line, /* block, and <!-- HTML --> comments so comment
 *  prose that mentions "Netz" never trips Invariant G. Keeps line
 *  counts stable by replacing non-newline chars inside matches with
 *  spaces. */
function stripCommentary(text, ext) {
	let out = text;
	// Block CSS/JS comments
	out = out.replace(/\/\*[\s\S]*?\*\//g, (block) =>
		block.replace(/[^\n]/g, " "),
	);
	// HTML comments (only meaningful inside .svelte/.html)
	if (ext === ".svelte" || ext === ".html") {
		out = out.replace(/<!--[\s\S]*?-->/g, (block) =>
			block.replace(/[^\n]/g, " "),
		);
	}
	// Line comments (JS/TS only — inside .svelte these only appear in
	// <script> regions but the regex is safe: it won't match inside a
	// CSS block comment because those were already blanked above).
	out = out.replace(/(^|[^:])\/\/[^\n]*/g, (match, pfx) =>
		pfx + " ".repeat(match.length - pfx.length),
	);
	return out;
}

const CHROME_WHITELIST_PATTERNS = [
	/netz:getToken/,               // context key — internal app IP
	/docs\/ux\/Netz Terminal/,     // reference path to the bundle source
	/netz-analysis-engine/,        // repo name
];

function isChromeWhitelisted(lineText) {
	return CHROME_WHITELIST_PATTERNS.some((re) => re.test(lineText));
}

const CHROME_BRAND_RULES = [
	{
		label: "aria-label",
		re: /aria-label\s*=\s*(["'`])[^"'`]*\b[Nn][Ee][Tt][Zz]\b[^"'`]*\1/g,
	},
	{
		label: "alt attribute",
		re: /\balt\s*=\s*(["'`])[^"'`]*\b[Nn][Ee][Tt][Zz]\b[^"'`]*\1/g,
	},
	{
		label: "placeholder attribute",
		re: /\bplaceholder\s*=\s*(["'`])[^"'`]*\b[Nn][Ee][Tt][Zz]\b[^"'`]*\1/g,
	},
	{
		label: "title attribute",
		re: /\btitle\s*=\s*(["'`])[^"'`]*\b[Nn][Ee][Tt][Zz]\b[^"'`]*\1/g,
	},
	{
		label: "visible text node",
		// Matches a character between `>` and `<` that contains a
		// word "Netz" / "NETZ". Skips tag-internal content.
		re: />[^<]*\b(?:Netz|NETZ)\b[^<]*</g,
	},
	{
		label: "string literal brand",
		// "Netz" / "NETZ" / 'Netz' / 'NETZ' / `Netz` / `NETZ` as a
		// whole-word token inside a quoted literal.
		re: /(["'`])\b(?:Netz|NETZ)\b\1/g,
	},
];

function scanChromeBrandLeaks() {
	const errors = [];

	const targets = [];
	for (const rel of CHROME_SCAN_ROOTS) {
		const abs = resolve(REPO_ROOT, rel);
		if (!existsSync(abs)) continue;
		for (const file of walkFiles(abs)) {
			if (CHROME_SCAN_EXTENSIONS.has(extname(file))) targets.push(file);
		}
	}
	for (const rel of CHROME_SCAN_FILES) {
		const abs = resolve(REPO_ROOT, rel);
		if (existsSync(abs)) targets.push(abs);
	}

	for (const absFile of targets) {
		const ext = extname(absFile);
		const rel = relative(REPO_ROOT, absFile).replaceAll("\\", "/");
		let text;
		try {
			text = readFileSync(absFile, "utf8");
		} catch {
			continue;
		}
		// Strip comments + <style> blocks before scanning so prose and
		// scoped CSS (which may legitimately reference legacy class
		// names) never trip the brand check.
		const decommented = stripCommentary(text, ext);
		const scanText =
			ext === ".svelte" ? stripStyleBlocks(decommented) : decommented;

		for (const rule of CHROME_BRAND_RULES) {
			rule.re.lastIndex = 0;
			let m;
			while ((m = rule.re.exec(scanText)) !== null) {
				if (m[0] === "") {
					rule.re.lastIndex++;
					continue;
				}
				if (isChromeWhitelisted(m[0])) continue;
				const line = offsetToLine(scanText, m.index);
				errors.push(
					`G. ${rel}:${line} hardcoded Netz brand in ${rule.label}: "${m[0].trim()}" — product chrome defaults to "II"; tenant name injected via orgName prop`,
				);
			}
		}
	}
	return errors;
}

// ── Invariant H — terminal/core must not depend on wealth ──
//
// frontends/terminal/ is the standalone II Terminal app. Shared
// implementation belongs in packages/ii-terminal-core or
// packages/investintell-ui. This invariant prevents regressions:
// app code and terminal-core code must not reach back into the
// wealth frontend by path, by transitional alias, or by local app
// alias imports.
//
// Comments that mention historical aliases in prose are allowed for
// import checks. Concrete path/config strings are still rejected.

const TERMINAL_ISOLATION_DIRS = [
	resolve(REPO_ROOT, "frontends/terminal"),
	resolve(REPO_ROOT, "packages/ii-terminal-core/src/lib"),
];

const WEALTH_IMPORT_PATTERNS = [
	{ label: "from '$wealth/...'", re: /\bfrom\s+(["'`])\$wealth\/[^"'`]*\1/g },
	{ label: "import('$wealth/...')", re: /\bimport\s*\(\s*(["'`])\$wealth\/[^"'`]*\1\s*\)/g },
	{ label: "from '$lib/...'", re: /\bfrom\s+(["'`])\$lib\/[^"'`]*\1/g },
	{ label: "import('$lib/...')", re: /\bimport\s*\(\s*(["'`])\$lib\/[^"'`]*\1\s*\)/g },
];

const WEALTH_PATH_PATTERNS = [
	{ label: "wealth frontend path", re: /frontends\/wealth/g },
	{ label: "relative wealth path", re: /\.\.\/wealth/g },
	{ label: "wealth source path", re: /wealth\/src\/lib/g },
	{ label: "terminal local alias", re: /\$lib:\s*["'`][^"'`]*wealth/g },
	{ label: "terminal local alias", re: /find:\s*\/\^\\\$lib/g },
];

function scanTerminalForWealthCoupling() {
	const errors = [];

	for (const root of TERMINAL_ISOLATION_DIRS) {
		if (!existsSync(root)) continue;
		for (const absFile of walkFiles(root)) {
		const ext = extname(absFile);
		if (!SCAN_EXTENSIONS.has(ext) && ext !== ".js" && ext !== ".cjs" && ext !== ".mjs") continue;
		const rel = relative(REPO_ROOT, absFile).replaceAll("\\", "/");
		let text;
		try {
			text = readFileSync(absFile, "utf8");
		} catch {
			continue;
		}
		// Strip comments + <style> blocks: legacy prose that mentions
		// historical aliases is allowed, only live import statements fail.
		const decommented = stripCommentary(text, ext);
		const scanText =
			ext === ".svelte" ? stripStyleBlocks(decommented) : decommented;

		for (const rule of WEALTH_IMPORT_PATTERNS) {
			rule.re.lastIndex = 0;
			let m;
			while ((m = rule.re.exec(scanText)) !== null) {
				if (m[0] === "") {
					rule.re.lastIndex++;
					continue;
				}
				const line = offsetToLine(scanText, m.index);
				errors.push(
					`H. ${rel}:${line} forbidden ${rule.label}: ${m[0].trim()} — import from @investintell/ii-terminal-core/* or @investintell/ui instead`,
				);
			}
		}

		for (const rule of WEALTH_PATH_PATTERNS) {
			rule.re.lastIndex = 0;
			let m;
			while ((m = rule.re.exec(text)) !== null) {
				if (m[0] === "") {
					rule.re.lastIndex++;
					continue;
				}
				const line = offsetToLine(text, m.index);
				errors.push(
					`H. ${rel}:${line} forbidden ${rule.label}: ${m[0].trim()} — terminal must not configure or reference wealth frontend paths`,
				);
			}
		}
		}
	}
	return errors;
}

main();
