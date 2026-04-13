<!--
	TerminalShell.svelte — outermost shell composition.
	====================================================

	Source of truth: docs/plans/2026-04-11-terminal-unification-master-plan.md
		§1.4 TerminalShell + layer taxonomy, Appendix B navigation flow,
		Appendix C tokens, Appendix G file structure.

	The persistent chrome of every terminal route. Composes:
		• TerminalTopNav   (row 1, 32px)
		• LayoutCage       (row 2, 1fr, wraps children snippet)
		• TerminalContextRail  (column 2, 280px conditional)
		• TerminalStatusBar (row 3, 28px)
		• CommandPalette   (overlay, z=70)

	Owns the global keyboard shortcuts:
		• Cmd/Ctrl + K      → toggle CommandPalette
		• `[` / `]`         → collapse / expand TerminalContextRail
		• `g` + s/l/r/m/a/p/n/d  → go-to navigation (active routes fire
		                       the matching command palette action;
		                       pending routes toggle the palette open
		                       so the user sees the pending badge)

	Input-field detection: the global handler short-circuits when the
	active element is an <input>, <textarea>, contenteditable, or
	role="textbox" so typing inside a search field never triggers a
	palette toggle or rail collapse.

	Resolves build metadata (VITE_BUILD_SHA, VITE_ENV), Clerk user/org
	placeholders (Phase 2+ will wire real Clerk context), and the
	URL-pinned entity via $derived reading $app/state `page`. The
	context rail only mounts when `?entity=<kind>:<id>` is in the URL
	with a valid entity kind. Rail collapse is ephemeral $state, not
	URL-persisted (feedback_echarts_no_localstorage.md: no browser
	storage inside the terminal namespace).
-->
<script lang="ts">
	import type { Snippet } from "svelte";
	import { getContext } from "svelte";
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { resolve } from "$app/paths";
	import { createClientApiClient } from "$lib/api/client";
	import TerminalTopNav from "./TerminalTopNav.svelte";
	import TerminalStatusBar from "./TerminalStatusBar.svelte";
	import TerminalContextRail, {
		type TerminalContextRailEntity,
		type TerminalContextRailEntityKind,
	} from "./TerminalContextRail.svelte";
	import CommandPalette from "./CommandPalette.svelte";
	import AlertTicker from "./AlertTicker.svelte";
	import LayoutCage from "./LayoutCage.svelte";

	interface TerminalShellProps {
		children: Snippet;
		/** Density for the LayoutCage: "standard" (24px) or "compact" (8px). */
		cageDensity?: "standard" | "compact";
	}

	let { children, cageDensity = "standard" }: TerminalShellProps = $props();

	// ─── Build metadata ─────────────────────────────────────────
	// Exposed via vite `define` in frontends/wealth/vite.config.ts
	// (commit 8). String literal fallbacks let the shell render
	// cleanly before the config edit lands.
	const buildShaRaw =
		(import.meta.env.VITE_BUILD_SHA as string | undefined) ?? "local";
	const buildSha = buildShaRaw.length > 7 ? buildShaRaw.slice(0, 7) : buildShaRaw;
	const environment = (((import.meta.env.VITE_ENV as string | undefined) ??
		"dev") as "dev" | "staging" | "prod");

	// ─── Clerk context placeholders ─────────────────────────────
	// Phase 2+ wires real Clerk user/org when the SvelteKit SDK
	// stabilizes. Ship with placeholders per escape hatch #7.
	const orgName = "NETZ";
	const userInitials = "AR";

	// ─── Connection status ──────────────────────────────────────
	// Part C hardcodes "connecting" since no streams are mounted.
	// Phase 5+ will aggregate real TerminalStream subscriptions.
	const connectionStatus = "connecting" as const;

	// ─── DD queue badge count ───────────────────────────────────
	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const ddApi = createClientApiClient(getToken);
	let ddQueueCount = $state(0);

	async function fetchDDQueueCount() {
		try {
			const res = await ddApi.get<{ counts: Record<string, number> }>("/dd-reports/queue");
			ddQueueCount = (res.counts.pending ?? 0) + (res.counts.in_progress ?? 0);
		} catch {
			// Silently ignore — badge stays at 0.
		}
	}

	$effect(() => {
		fetchDDQueueCount();
		const timer = setInterval(fetchDDQueueCount, 60_000);
		return () => clearInterval(timer);
	});

	// ─── URL-pinned entity ──────────────────────────────────────
	const KNOWN_KINDS: ReadonlyArray<TerminalContextRailEntityKind> = [
		"fund",
		"portfolio",
		"manager",
		"sector",
		"regime",
	];

	const entity = $derived.by<TerminalContextRailEntity | null>(() => {
		const raw = page.url.searchParams.get("entity");
		if (!raw) return null;
		const separator = raw.indexOf(":");
		if (separator <= 0 || separator >= raw.length - 1) return null;
		const kind = raw.slice(0, separator);
		const id = raw.slice(separator + 1);
		if (!KNOWN_KINDS.includes(kind as TerminalContextRailEntityKind)) return null;
		return { kind: kind as TerminalContextRailEntityKind, id };
	});

	// ─── Ephemeral shell state ──────────────────────────────────
	let railCollapsed = $state(false);
	let paletteOpen = $state(false);

	// Go-to navigation catalog (mirrors the CommandPalette action
	// dispatch surface). `active` entries invoke goto via resolve();
	// `pending` entries open the palette so the user sees the
	// pending badge for that route.
	async function navScreener() {
		const target = resolve("/terminal-screener");
		await goto(target);
	}

	async function navLive() {
		const target = resolve("/portfolio/live");
		await goto(target);
	}

	async function navResearch() {
		const target = resolve("/research");
		await goto(target);
	}

	async function navDD() {
		const target = resolve("/dd");
		await goto(target);
	}

	function openPalette() {
		paletteOpen = true;
	}

	type GoToHandler = () => void | Promise<void>;

	const GO_TO_SHORTCUTS: Readonly<Record<string, GoToHandler>> = {
		s: navScreener,
		l: navLive,
		r: navResearch,
		m: openPalette, // Macro — pending route
		a: openPalette, // Alloc — pending
		p: openPalette, // Portfolio Builder — pending
		n: openPalette, // Alerts (n for notifications) — pending
		d: navDD,       // DD — active
	};

	const GO_TO_WINDOW_MS = 800;

	// ─── Global keyboard handler ────────────────────────────────
	let goPrefixTimestamp: number | null = null;

	function isEditableTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName;
		if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
			return true;
		}
		if (target.isContentEditable) return true;
		const role = target.getAttribute("role");
		if (role === "textbox" || role === "searchbox" || role === "combobox") {
			return true;
		}
		return false;
	}

	$effect(() => {
		if (typeof window === "undefined") return;

		const handler = (event: KeyboardEvent) => {
			// Cmd+K / Ctrl+K always wins — it works inside inputs too,
			// because the palette is a global launcher and needs an
			// escape hatch from any focused surface.
			const isPaletteShortcut =
				(event.metaKey || event.ctrlKey) &&
				!event.shiftKey &&
				!event.altKey &&
				(event.key === "k" || event.key === "K");
			if (isPaletteShortcut) {
				event.preventDefault();
				paletteOpen = !paletteOpen;
				goPrefixTimestamp = null;
				return;
			}

			// All remaining shortcuts short-circuit inside editable fields.
			if (isEditableTarget(event.target)) {
				goPrefixTimestamp = null;
				return;
			}

			// Rail collapse — only plain brackets, no modifiers.
			if (
				(event.key === "[" || event.key === "]") &&
				!event.metaKey &&
				!event.ctrlKey &&
				!event.altKey
			) {
				if (entity !== null) {
					event.preventDefault();
					railCollapsed = event.key === "[";
				}
				goPrefixTimestamp = null;
				return;
			}

			// g-prefix go-to sequences.
			if (
				event.key === "g" &&
				!event.metaKey &&
				!event.ctrlKey &&
				!event.altKey
			) {
				goPrefixTimestamp = Date.now();
				return;
			}

			if (goPrefixTimestamp !== null) {
				const elapsed = Date.now() - goPrefixTimestamp;
				goPrefixTimestamp = null;
				if (elapsed > GO_TO_WINDOW_MS) return;
				const handlerFn = GO_TO_SHORTCUTS[event.key];
				if (handlerFn) {
					event.preventDefault();
					const result = handlerFn();
					if (
						result &&
						typeof (result as Promise<void>).then === "function"
					) {
						void (result as Promise<void>);
					}
				}
				return;
			}
		};

		window.addEventListener("keydown", handler);
		return () => {
			window.removeEventListener("keydown", handler);
		};
	});
</script>

{#snippet tickerSnippet()}
	<AlertTicker />
{/snippet}

<div class="ts-shell" class:ts-shell--has-rail={entity !== null}>
	<div class="ts-nav-row">
		<TerminalTopNav
			activePath={page.url.pathname}
			onOpenPalette={openPalette}
			{ddQueueCount}
			{userInitials}
			{orgName}
		/>
	</div>

	<main class="ts-content">
		<LayoutCage density={cageDensity}>
			{@render children()}
		</LayoutCage>
	</main>

	{#if entity !== null}
		<div class="ts-rail-col">
			<TerminalContextRail {entity} collapsed={railCollapsed} />
		</div>
	{/if}

	<div class="ts-status-row">
		<TerminalStatusBar
			{buildSha}
			{environment}
			{orgName}
			{userInitials}
			{connectionStatus}
			ticker={tickerSnippet}
		/>
	</div>
</div>

<CommandPalette bind:open={paletteOpen} />

<style>
	.ts-shell {
		position: fixed;
		inset: 0;
		display: grid;
		grid-template-rows: 32px 1fr 28px;
		grid-template-columns: 1fr;
		grid-template-areas:
			"nav"
			"content"
			"status";
		height: 100dvh;
		width: 100vw;
		overflow: hidden;
		background: var(--terminal-bg-void);
		color: var(--terminal-fg-primary);
		font-family: var(--terminal-font-mono);
		isolation: isolate;
	}

	.ts-shell--has-rail {
		grid-template-columns: 1fr 280px;
		grid-template-areas:
			"nav nav"
			"content rail"
			"status status";
	}

	.ts-nav-row {
		grid-area: nav;
		min-width: 0;
	}

	.ts-content {
		grid-area: content;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		display: flex;
	}

	.ts-rail-col {
		grid-area: rail;
		min-width: 0;
		min-height: 0;
	}

	.ts-status-row {
		grid-area: status;
		min-width: 0;
	}

	:global(body:has(.ts-shell)) {
		overflow: hidden;
	}
</style>
