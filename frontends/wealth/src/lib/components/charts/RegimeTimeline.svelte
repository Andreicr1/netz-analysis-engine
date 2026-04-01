<!--
  Regime Timeline — pure CSS horizontal strip showing regime history.
  Each segment is proportional to its duration. Hover expands from 8px to 24px.
-->
<script lang="ts">
	import { regimeLabels, regimeColors } from "$lib/constants/regime";
	import { formatShortDate } from "@investintell/ui";

	interface Props {
		history: Array<{ snapshot_date?: string; date?: string; regime: string; profile?: string }>;
		profile?: string;
		height?: number;
	}

	let { history, profile, height = 8 }: Props = $props();

	// Filter by profile if provided + normalize date field
	let filtered = $derived.by(() => {
		let items = history;
		if (profile) {
			items = items.filter((h) => !h.profile || h.profile === profile);
		}
		return items
			.map((h) => ({ date: h.snapshot_date ?? h.date ?? "", regime: h.regime }))
			.sort((a, b) => a.date.localeCompare(b.date));
	});

	// Derive segments — consecutive points with same regime become one segment
	interface Segment {
		type: string;
		start: string;
		end: string;
		durationDays: number;
	}

	let segments = $derived.by((): Segment[] => {
		if (filtered.length === 0) return [];

		const result: Segment[] = [];
		let current = { type: filtered[0]!.regime, start: filtered[0]!.date, end: filtered[0]!.date };

		for (let i = 1; i < filtered.length; i++) {
			const pt = filtered[i]!;
			if (pt.regime === current.type) {
				current.end = pt.date;
			} else {
				result.push(finalize(current));
				current = { type: pt.regime, start: pt.date, end: pt.date };
			}
		}
		result.push(finalize(current));
		return result;
	});

	function finalize(seg: { type: string; start: string; end: string }): Segment {
		const ms = new Date(seg.end).getTime() - new Date(seg.start).getTime();
		const days = Math.max(Math.ceil(ms / 86_400_000), 1);
		return { type: seg.type, start: seg.start, end: seg.end, durationDays: days };
	}

	// Aria description
	let ariaDescription = $derived.by(() => {
		if (segments.length === 0) return "No regime history data available";
		return segments
			.map((s) => `${regimeLabels[s.type] ?? s.type}: ${formatShortDate(s.start)} to ${formatShortDate(s.end)}`)
			.join(", ");
	});
</script>

{#if segments.length > 0}
	<div
		class="regime-strip"
		style:height="{height}px"
		role="img"
		aria-label={ariaDescription}
	>
		{#each segments as seg (seg.start)}
			<div
				class="regime-segment"
				style:flex-grow={seg.durationDays}
				style:background-color={regimeColors[seg.type] ?? "var(--ii-border)"}
				title="{regimeLabels[seg.type] ?? seg.type}: {formatShortDate(seg.start)} – {formatShortDate(seg.end)} ({seg.durationDays}d)"
			></div>
		{/each}
	</div>
{/if}

<style>
	.regime-strip {
		display: flex;
		width: 100%;
		border-radius: 4px;
		overflow: hidden;
		transition: height 200ms ease;
		cursor: default;
	}

	.regime-strip:hover {
		height: 24px !important;
	}

	.regime-segment {
		min-width: 2px;
		transition: opacity 150ms ease;
	}

	.regime-segment:hover {
		opacity: 0.8;
	}
</style>
