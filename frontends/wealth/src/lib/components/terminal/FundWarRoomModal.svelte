<!--
  FundWarRoomModal — full-screen War Room for a selected fund.

  Cinematic orchestration: staggered Svelte transitions choreograph the
  top bar (fade), the risk slab, the drawdown reactor, and the
  distribution histogram (fly + escalating delays). ECharts animations
  handle the in-chart "drawing in real time" effect.

  Aesthetic: HUD militar / techno-brutalist. Hard 1px borders, zero
  border-radius, monospace 11px, absolute black fill.
-->
<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { fade, fly } from "svelte/transition";
	import EntityAnalyticsVitrine from "$lib/components/analytics/entity/EntityAnalyticsVitrine.svelte";

	interface Props {
		id: string;
		onClose: () => void;
	}

	let { id, onClose }: Props = $props();

	// ── Lock body scroll while mounted ───────────────────
	let previousOverflow = "";
	onMount(() => {
		previousOverflow = document.body.style.overflow;
		document.body.style.overflow = "hidden";
		window.addEventListener("keydown", handleKey);
	});
	onDestroy(() => {
		document.body.style.overflow = previousOverflow;
		if (typeof window !== "undefined") {
			window.removeEventListener("keydown", handleKey);
		}
	});

	function handleKey(e: KeyboardEvent) {
		if (e.key === "Escape") onClose();
	}

	function handleBackdrop(e: MouseEvent) {
		if (e.target === e.currentTarget) onClose();
	}

	const timestamp = new Date().toISOString().replace("T", " ").slice(0, 19) + "Z";
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	class="wr-backdrop"
	onclick={handleBackdrop}
	transition:fade={{ duration: 150 }}
	role="dialog"
	aria-modal="true"
	aria-label="Fund War Room"
	tabindex="-1"
>
	<div class="wr-frame">
		<!-- ── TOP BAR — War Room chrome ───────────────────────── -->
		<header class="wr-topbar" in:fade={{ duration: 200 }}>
			<div class="wr-topbar-left">
				<span class="wr-brand">[ WAR ROOM ]</span>
				<span class="wr-sep">//</span>
				<span class="wr-fund-id">{id}</span>
				<span class="wr-sep">//</span>
				<span class="wr-status">
					<span class="wr-dot"></span>LIVE
				</span>
			</div>
			<div class="wr-topbar-right">
				<span class="wr-ts">{timestamp}</span>
				<button class="wr-close" onclick={onClose} aria-label="Close War Room">
					[ ESC · CLOSE ]
				</button>
			</div>
		</header>

		<!-- ── MAIN GRID ──────────────────────────────────────── -->
		<div class="wr-grid">
			<!-- Reactor: the Entity Analytics Vitrine, staggered via
			     :global CSS below so the risk slab, drawdown chart
			     and histogram cascade into view. -->
			<section class="wr-reactor" in:fly={{ y: 20, duration: 400, delay: 100 }}>
				<EntityAnalyticsVitrine {id} />
			</section>

			<!-- Context rail — fund metadata strip -->
			<aside class="wr-rail" in:fly={{ y: 20, duration: 400, delay: 300 }}>
				<div class="wr-rail-block">
					<span class="wr-rail-label">ENTITY</span>
					<span class="wr-rail-value">{id}</span>
				</div>
				<div class="wr-rail-block">
					<span class="wr-rail-label">MODE</span>
					<span class="wr-rail-value">TERMINAL // WAR ROOM</span>
				</div>
				<div class="wr-rail-block">
					<span class="wr-rail-label">SNAPSHOT</span>
					<span class="wr-rail-value">{timestamp}</span>
				</div>
				<div class="wr-rail-block wr-rail-hint">
					<span class="wr-rail-label">NAV</span>
					<span class="wr-rail-value">ESC · CLICK BACKDROP</span>
				</div>
			</aside>
		</div>
	</div>
</div>

<style>
	/* ── Backdrop — isolates the screen ───────────────── */
	.wr-backdrop {
		position: fixed;
		inset: 0;
		z-index: 9999;
		background: rgba(0, 0, 0, 0.8);
		backdrop-filter: blur(4px);
		-webkit-backdrop-filter: blur(4px);
		display: grid;
		place-items: center;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
			"Liberation Mono", "Courier New", monospace;
		color: #e5e7eb;
		font-size: 11px;
	}

	/* ── Frame — laser-cut HUD shell ──────────────────── */
	.wr-frame {
		width: 95vw;
		height: 95vh;
		background: #000;
		border: 1px solid #333;
		display: grid;
		grid-template-rows: 36px 1fr;
		overflow: hidden;
	}

	/* ── Top Bar ──────────────────────────────────────── */
	.wr-topbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 14px;
		border-bottom: 1px solid #333;
		background: #050505;
		font-size: 11px;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.wr-topbar-left,
	.wr-topbar-right {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.wr-brand {
		color: #f3f4f6;
		font-weight: 700;
		letter-spacing: 0.12em;
	}

	.wr-sep {
		color: #333;
	}

	.wr-fund-id {
		color: #9ca3af;
		font-weight: 500;
	}

	.wr-status {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: #22c55e;
	}

	.wr-dot {
		width: 6px;
		height: 6px;
		background: #22c55e;
		display: inline-block;
		box-shadow: 0 0 8px #22c55e;
		animation: wr-pulse 1.8s ease-in-out infinite;
	}

	@keyframes wr-pulse {
		0%, 100% { opacity: 0.45; }
		50% { opacity: 1; }
	}

	.wr-ts {
		color: #4b5563;
		font-variant-numeric: tabular-nums;
	}

	.wr-close {
		background: transparent;
		border: 1px solid #333;
		color: #e5e7eb;
		font-family: inherit;
		font-size: 11px;
		letter-spacing: 0.06em;
		padding: 4px 10px;
		cursor: pointer;
		text-transform: uppercase;
		transition: border-color 80ms ease, color 80ms ease, background 80ms ease;
	}

	.wr-close:hover {
		border-color: #ef4444;
		color: #ef4444;
		background: rgba(239, 68, 68, 0.06);
	}

	/* ── Main Grid — rigorous CSS grid, reactor + rail ── */
	.wr-grid {
		display: grid;
		grid-template-columns: 1fr 220px;
		grid-template-rows: 1fr;
		min-height: 0;
		overflow: hidden;
	}

	.wr-reactor {
		min-width: 0;
		min-height: 0;
		overflow: auto;
		border-right: 1px solid #1a1a1a;
	}

	.wr-rail {
		display: grid;
		grid-auto-rows: min-content;
		gap: 1px;
		background: #1a1a1a;
		overflow: auto;
	}

	.wr-rail-block {
		background: #000;
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.wr-rail-label {
		font-size: 9px;
		color: #4b5563;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.wr-rail-value {
		font-size: 11px;
		color: #e5e7eb;
		word-break: break-all;
	}

	.wr-rail-hint .wr-rail-value {
		color: #6b7280;
	}

	/* ── Cascade for the internal Vitrine modules ─────
	   Uses :global because the modules live inside a
	   child component (Vitrine). Each .module fades/flies
	   in with escalating delay so the drawdown chart,
	   capture scatter and return distribution cascade
	   after the risk slab, matching the cinematic brief. */
	.wr-reactor :global(.tail-strip) {
		opacity: 0;
		animation: wr-in 400ms ease-out 80ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(1)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 140ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(2)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 220ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(3)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 300ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(4)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 380ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(5)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 460ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(6)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 540ms forwards;
	}
	.wr-reactor :global(.module:nth-of-type(7)) {
		opacity: 0;
		transform: translateY(20px);
		animation: wr-fly 450ms ease-out 620ms forwards;
	}

	@keyframes wr-in {
		to { opacity: 1; }
	}

	@keyframes wr-fly {
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* Responsive — collapse the context rail on narrow screens */
	@media (max-width: 1100px) {
		.wr-grid {
			grid-template-columns: 1fr;
			grid-template-rows: 1fr auto;
		}
		.wr-reactor {
			border-right: none;
			border-bottom: 1px solid #1a1a1a;
		}
		.wr-rail {
			grid-auto-flow: column;
			grid-auto-columns: minmax(160px, 1fr);
			max-height: 120px;
		}
	}
</style>
