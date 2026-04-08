/**
 * Analytics URL-hash codec — Phase 6 Block A.
 *
 * BottomTabDock state persistence per DL15 (no localStorage, no
 * sessionStorage). The active tab list and selected tab id are
 * serialized into the URL hash so deep links and browser back/forward
 * survive a page reload.
 *
 * Hash format: ``#tabs=<base64url(JSON.stringify(AnalyticsHashState))>``
 *
 * Empty / missing hashes return a clean ``{tabs: [], activeId: null}``
 * — never raises so a malformed hash from the wild cannot break the
 * route. The version field guards against future schema migrations.
 */

import type {
	AnalyticsHashState,
	AnalyticsTab,
} from "./analytics-types";

const HASH_KEY = "tabs";

/**
 * Encode AnalyticsHashState into a URL hash fragment. Returns the
 * fragment WITHOUT the leading ``#``. The caller is responsible for
 * concatenating it onto the URL.
 *
 * Empty tabs returns an empty string so the hash can be cleared.
 */
export function encodeAnalyticsHash(state: AnalyticsHashState): string {
	if (state.tabs.length === 0) return "";
	try {
		const json = JSON.stringify(state);
		// Browser-safe base64 (URL-safe characters + no padding).
		const b64 = base64UrlEncode(json);
		return `${HASH_KEY}=${b64}`;
	} catch {
		return "";
	}
}

/**
 * Decode an AnalyticsHashState from a URL hash fragment (with or
 * without the leading ``#``). Returns the canonical empty state on
 * any decode error or schema mismatch — never raises.
 */
export function decodeAnalyticsHash(hash: string | null | undefined): AnalyticsHashState {
	const empty: AnalyticsHashState = { v: 1, tabs: [], activeId: null };
	if (!hash) return empty;
	const stripped = hash.startsWith("#") ? hash.slice(1) : hash;
	if (stripped.length === 0) return empty;

	const params = new URLSearchParams(stripped);
	const raw = params.get(HASH_KEY);
	if (!raw) return empty;

	try {
		const json = base64UrlDecode(raw);
		const parsed = JSON.parse(json) as unknown;
		if (!isAnalyticsHashState(parsed)) return empty;
		return parsed;
	} catch {
		return empty;
	}
}

/**
 * Append, replace, or close a tab in an existing list with dedupe by
 * fingerprint (``${scope}:${subjectId}``). When ``op`` is ``"open"``
 * and the fingerprint already exists, the existing tab is updated
 * in place (group focus may have changed) and promoted to active —
 * never duplicated.
 */
export function applyTabOp(
	tabs: readonly AnalyticsTab[],
	op:
		| { kind: "open"; tab: AnalyticsTab }
		| { kind: "close"; id: string }
		| { kind: "select"; id: string },
): { tabs: AnalyticsTab[]; activeId: string | null } {
	const list = [...tabs];

	if (op.kind === "open") {
		const idx = list.findIndex((t) => t.id === op.tab.id);
		if (idx >= 0) {
			list[idx] = { ...list[idx], ...op.tab };
		} else {
			list.push(op.tab);
		}
		return { tabs: list, activeId: op.tab.id };
	}

	if (op.kind === "close") {
		const idx = list.findIndex((t) => t.id === op.id);
		if (idx < 0) return { tabs: list, activeId: list[0]?.id ?? null };
		list.splice(idx, 1);
		// Pick the neighbor on the right, then left, else null.
		const next = list[idx] ?? list[idx - 1] ?? null;
		return { tabs: list, activeId: next?.id ?? null };
	}

	if (op.kind === "select") {
		return { tabs: list, activeId: op.id };
	}

	return { tabs: list, activeId: null };
}

// ── Internals ──────────────────────────────────────────────────────

function isAnalyticsHashState(value: unknown): value is AnalyticsHashState {
	if (typeof value !== "object" || value === null) return false;
	const v = value as Record<string, unknown>;
	if (v.v !== 1) return false;
	if (!Array.isArray(v.tabs)) return false;
	if (v.activeId !== null && typeof v.activeId !== "string") return false;
	for (const t of v.tabs) {
		if (typeof t !== "object" || t === null) return false;
		const tab = t as Record<string, unknown>;
		if (typeof tab.id !== "string") return false;
		if (typeof tab.subjectId !== "string") return false;
		if (typeof tab.scope !== "string") return false;
		if (typeof tab.label !== "string") return false;
		if (typeof tab.groupFocus !== "string") return false;
	}
	return true;
}

function base64UrlEncode(input: string): string {
	const b64 = typeof btoa !== "undefined"
		? btoa(unescape(encodeURIComponent(input)))
		: Buffer.from(input, "utf-8").toString("base64");
	return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlDecode(input: string): string {
	const b64 = input.replace(/-/g, "+").replace(/_/g, "/");
	const padded = b64 + "===".slice((b64.length + 3) % 4);
	if (typeof atob !== "undefined") {
		return decodeURIComponent(escape(atob(padded)));
	}
	return Buffer.from(padded, "base64").toString("utf-8");
}
