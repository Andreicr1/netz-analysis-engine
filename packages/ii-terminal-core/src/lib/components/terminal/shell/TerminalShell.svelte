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
	import { base } from "$app/paths";
	import { createClientApiClient } from "../../../api/client";
	import TerminalTopNav from "./TerminalTopNav.svelte";
	import TerminalBreadcrumb from "./TerminalBreadcrumb.svelte";
	import TerminalTweaksPanel from "./TerminalTweaksPanel.svelte";
	import TerminalStatusBar from "./TerminalStatusBar.svelte";
	import {
		TERMINAL_TWEAKS_KEY,
		type TerminalTweaks,
	} from "../../../stores/terminal-tweaks.svelte";
	import { TERMINAL_MARKET_DATA_KEY } from "../../../components/portfolio/live/workbench-state";
	import type { MarketDataStore, WsStatus } from "../../../stores/market-data.svelte";
	import type { TerminalStatusBarConnectionStatus } from "./TerminalStatusBar.svelte";
	import TerminalContextRail, {
		type TerminalContextRailEntity,
		type TerminalContextRailEntityKind,
	} from "./TerminalContextRail.svelte";
	import CommandPalette from "./CommandPalette.svelte";
	import AlertTicker from "./AlertTicker.svelte";
	import LayoutCage from "./LayoutCage.svelte";
	import {
		openPalette as openPaletteStore,
		togglePalette,
	} from "../../../stores/palette.svelte";

	interface TerminalShellProps {
		children: Snippet;
		/** Density for the LayoutCage: "standard" (24px) or "compact" (8px). */
		cageDensity?: "standard" | "compact";
		/**
		 * Hide the TerminalBreadcrumb workflow stepper row. The II Terminal
		 * app (frontends/terminal/) sets this to `true` because its TopNav
		 * already carries the workflow tabs (F1..F6) — rendering the
		 * breadcrumb too produces a double-nav stack. Wealth's (terminal)/
		 * routes keep the legacy default (false) while the shell lives in
		 * both apps; X7 retires the wealth copy entirely.
		 */
		hideWorkflowStepper?: boolean;
	}

	let {
		children,
		cageDensity = "standard",
		hideWorkflowStepper = false,
	}: TerminalShellProps = $props();

	// ─── Build metadata ─────────────────────────────────────────
	// Exposed via vite `define`. String literal fallbacks let the shell render
	// cleanly when build metadata is absent.
	const buildShaRaw =
		(import.meta.env.VITE_BUILD_SHA as string | undefined) ?? "local";
	const buildSha = buildShaRaw.length > 7 ? buildShaRaw.slice(0, 7) : buildShaRaw;
	const environment = (((import.meta.env.VITE_ENV as string | undefined) ??
		"dev") as "dev" | "staging" | "prod");

	// ─── Clerk context placeholders ─────────────────────────────
	// Phase 2+ wires real Clerk user/org when the SvelteKit SDK
	// stabilizes. Ship with placeholders per escape hatch #7.
	const orgName = "II";
	const userInitials = "AR";

	// ─── Connection status ──────────────────────────────────────
	// Aggregated from the terminal-scoped MarketDataStore WS state
	// (context set by (terminal)/+layout.svelte). Routes without a
	// market stream still see "connecting" as the bootstrap default.
	const marketStore = getContext<MarketDataStore | undefined>(
		TERMINAL_MARKET_DATA_KEY,
	);

	const WS_STATUS_MAP: Record<WsStatus, TerminalStatusBarConnectionStatus> = {
		connecting: "connecting",
		connected: "open",
		reconnecting: "degraded",
		disconnected: "closed",
		error: "error",
	};

	const connectionStatus = $derived<TerminalStatusBarConnectionStatus>(
		marketStore ? WS_STATUS_MAP[marketStore.status] : "connecting",
	);

	// ─── Tweaks (density / accent / theme) ─────────────────────
	// Bound as data-attributes on the shell root so tokens shipped
	// in @investintell/ui/tokens/terminal.css activate via attribute
	// selectors. Store is populated by (terminal)/+layout.svelte.
	const tweaks = getContext<TerminalTweaks>(TERMINAL_TWEAKS_KEY);

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
	// Go-to navigation catalog (mirrors the CommandPalette action
	// dispatch surface). `active` entries invoke goto via resolve();
	// `pending` entries open the palette so the user sees the
	// pending badge for that route.
	async function navMacro() {
		await goto(`${base}/macro`);
	}

	async function navAlloc() {
		await goto(`${base}/allocation`);
	}

	async function navScreener() {
		await goto(`${base}/screener`);
	}

	async function navDD() {
		await goto(`${base}/dd`);
	}

	async function navBuilder() {
		await goto(`${base}/portfolio/builder`);
	}

	async function navLive() {
		await goto(`${base}/live`);
	}

	async function navResearch() {
		await goto(`${base}/screener/research`);
	}

	async function navAlerts() {
		await goto(`${base}/alerts`);
	}

	function openPalette() {
		openPaletteStore();
	}

	type GoToHandler = () => void | Promise<void>;

	const GO_TO_SHORTCUTS: Readonly<Record<string, GoToHandler>> = {
		m: navMacro,
		a: navAlloc,
		s: navScreener,
		d: navDD,
		p: navBuilder,
		l: navLive,
		r: navResearch,
		n: navAlerts,
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
				togglePalette();
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

<div
	class="ts-shell"
	class:ts-shell--has-rail={entity !== null}
	class:ts-shell--no-crumb={hideWorkflowStepper}
	data-surface="terminal"
	data-density={tweaks?.density ?? "standard"}
	data-accent={tweaks?.accent ?? "amber"}
	data-theme={tweaks?.theme ?? "dark"}
>
	<div class="ts-nav-row">
		<TerminalTopNav
			activePath={page.url.pathname}
			onOpenPalette={openPalette}
			{ddQueueCount}
			{userInitials}
			{orgName}
		/>
	</div>

	{#if !hideWorkflowStepper}
		<div class="ts-crumb-row">
			<TerminalBreadcrumb />
		</div>
	{/if}

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

<CommandPalette />
<TerminalTweaksPanel />

<style>
	.ts-shell {
		position: fixed;
		inset: 0;
		display: grid;
		grid-template-rows: 32px var(--terminal-shell-breadcrumb-height, 28px) 1fr 28px;
		grid-template-columns: 1fr;
		grid-template-areas:
			"nav"
			"crumb"
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

	/* II Terminal path — stepper hidden. Collapse the breadcrumb row
	 * entirely so the content gets the full height back, including
	 * the 28px previously reserved by --terminal-shell-breadcrumb. */
	.ts-shell--no-crumb {
		grid-template-rows: 32px 1fr 28px;
		grid-template-areas:
			"nav"
			"content"
			"status";
	}

	.ts-shell--has-rail {
		grid-template-columns: 1fr 280px;
		grid-template-areas:
			"nav nav"
			"crumb crumb"
			"content rail"
			"status status";
	}

	.ts-shell--has-rail.ts-shell--no-crumb {
		grid-template-rows: 32px 1fr 28px;
		grid-template-areas:
			"nav nav"
			"content rail"
			"status status";
	}

	.ts-nav-row {
		grid-area: nav;
		min-width: 0;
	}

	.ts-crumb-row {
		grid-area: crumb;
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
