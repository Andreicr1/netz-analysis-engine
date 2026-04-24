<!--
  CascadeTimeline.svelte — ALLOCATION proposal wrapper.

  Thin wrapper around CascadeTimelineCore for the propose/review
  flow. Accepts allocation-page.ts types (CascadePhaseAttempt,
  CoverageSummary) and forwards them to the shared core renderer.
-->
<script lang="ts">
	import type {
		CascadePhaseAttempt,
		CoverageSummary,
	} from "../../types/allocation-page";
	import CascadeTimelineCore from "./CascadeTimelineCore.svelte";

	export type CascadeTimelineMode = "live" | "settled";

	interface Props {
		phases: CascadePhaseAttempt[];
		winnerSignal?: string | null;
		coverage?: CoverageSummary | null;
		mode?: CascadeTimelineMode;
		class?: string;
	}

	let {
		phases,
		winnerSignal = null,
		coverage = null,
		mode = "settled",
		class: className,
	}: Props = $props();
</script>

<CascadeTimelineCore
	{phases}
	{winnerSignal}
	{coverage}
	{mode}
	class={className}
/>
