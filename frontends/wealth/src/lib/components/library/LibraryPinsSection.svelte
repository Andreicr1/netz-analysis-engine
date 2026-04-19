<!--
  LibraryPinsSection — landing-page carousels for pinned, starred,
  and recently-viewed Library entries.

  Phase 6 of the Library frontend (spec §3.4 Fase 6). Renders only
  on the Library root (no folder or file selected) and gives the
  PM a one-click jump back into the documents they actually use.

  Each card writes through the URL adapter so the click round-trips
  through the same single-flight preview loader as a tree click.
-->
<script lang="ts">
	import Pin from "lucide-svelte/icons/pin";
	import Clock from "lucide-svelte/icons/clock";
	import Star from "lucide-svelte/icons/star";
	import { formatDateTime } from "@investintell/ui";
	import type { PinsClient } from "$wealth/state/library/pins-client.svelte";
	import type { UrlAdapter } from "$wealth/state/library/url-adapter.svelte";
	import type { LibraryPin } from "$wealth/types/library";

	interface Props {
		pins: PinsClient;
		adapter: UrlAdapter;
	}

	let { pins, adapter }: Props = $props();

	function openPin(pin: LibraryPin): void {
		adapter.setSelectedId(pin.library_index_id);
	}

	const sections = $derived([
		{
			id: "pinned",
			title: "Pinned",
			Icon: Pin,
			items: pins.state.pinned,
		},
		{
			id: "starred",
			title: "Starred",
			Icon: Star,
			items: pins.state.starred,
		},
		{
			id: "recent",
			title: "Recently Viewed",
			Icon: Clock,
			items: pins.state.recent,
		},
	]);
</script>

<div class="pins">
	{#if pins.state.loading && pins.state.pinned.length === 0 && pins.state.starred.length === 0 && pins.state.recent.length === 0}
		<p class="pins__loading">Loading your shortcuts…</p>
	{/if}

	{#each sections as section (section.id)}
		{@const Icon = section.Icon}
		<section class="pins__section" aria-label={section.title}>
			<header class="pins__header">
				<span class="pins__icon">
					<Icon size={14} />
				</span>
				<h3 class="pins__title">{section.title}</h3>
				<span class="pins__count">{section.items.length}</span>
			</header>

			{#if section.items.length === 0}
				<p class="pins__empty">
					{#if section.id === "pinned"}
						No pinned documents yet.
					{:else if section.id === "starred"}
						Star a document to keep it within reach.
					{:else}
						Documents you open will appear here.
					{/if}
				</p>
			{:else}
				<div class="pins__row">
					{#each section.items as pin (pin.id)}
						<button
							type="button"
							class="pins__card"
							onclick={() => openPin(pin)}
						>
							<span class="pins__card-kind">{pin.kind ?? "document"}</span>
							<span class="pins__card-label">{pin.label}</span>
							<span class="pins__card-meta">
								{formatDateTime(pin.last_accessed_at)}
							</span>
						</button>
					{/each}
				</div>
			{/if}
		</section>
	{/each}
</div>

<style>
	.pins {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding: 24px;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
		color: #cbccd1;
	}

	.pins__loading {
		font-size: 13px;
		color: #85a0bd;
		margin: 0;
	}

	.pins__section {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.pins__header {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.pins__icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		background: #1d1f25;
		border: 1px solid #404249;
		border-radius: 6px;
		color: #85a0bd;
	}

	.pins__title {
		font-size: 13px;
		font-weight: 700;
		color: #ffffff;
		margin: 0;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.pins__count {
		font-size: 11px;
		font-weight: 600;
		color: #85a0bd;
		padding: 1px 8px;
		border-radius: 999px;
		background: #1d1f25;
	}

	.pins__empty {
		font-size: 12px;
		color: #85a0bd;
		margin: 0;
	}

	.pins__row {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: 10px;
	}

	.pins__card {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 12px 14px;
		border: 1px solid #404249;
		background: #1d1f25;
		color: #cbccd1;
		border-radius: 10px;
		font-family: inherit;
		text-align: left;
		cursor: pointer;
		transition: border-color 120ms ease, transform 120ms ease;
	}

	.pins__card:hover {
		border-color: #0177fb;
		transform: translateY(-1px);
	}

	.pins__card-kind {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #85a0bd;
	}

	.pins__card-label {
		font-size: 13px;
		font-weight: 600;
		color: #ffffff;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.pins__card-meta {
		font-size: 11px;
		color: #85a0bd;
		font-variant-numeric: tabular-nums;
	}
</style>
