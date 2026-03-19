<!--
  @component IngestionProgress
  SSE stream showing pipeline stages: OCR → classify → chunk → embed → index.
-->
<script lang="ts">
	import { Card, StatusBadge } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import { onMount, getContext } from "svelte";
	import { resolveCreditStatus } from "$lib/utils/status-maps";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { jobId }: { jobId: string } = $props();

	interface PipelineEvent {
		stage: string;
		status: string;
		message?: string;
		progress?: number;
	}

	let events = $state<PipelineEvent[]>([]);
	let status = $state<"connecting" | "connected" | "done" | "error">("connecting");

	const STAGES = ["ocr", "classify", "governance", "chunk", "extract", "embed", "index"];

	onMount(() => {
		const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
		const sse = createSSEStream<PipelineEvent>({
			url: `${API_BASE}/api/v1/jobs/${jobId}/stream`,
			getToken,
			onEvent: (event) => {
				events = [...events, event];
				if (event.status === "completed" || event.status === "failed") {
					status = event.status === "completed" ? "done" : "error";
					sse.disconnect();
				}
			},
			onError: () => { status = "error"; },
		});
		sse.connect();
		status = "connected";

		return () => sse.disconnect();
	});

	function stageStatus(stage: string): string {
		const event = events.findLast((e) => e.stage === stage);
		return event?.status ?? "pending";
	}
</script>

<Card class="p-6">
	<h3 class="mb-4 text-lg font-semibold text-(--netz-text-primary)">Ingestion Progress</h3>
	<div class="space-y-3">
		{#each STAGES as stage (stage)}
			<div class="flex items-center justify-between">
				<span class="text-sm capitalize text-(--netz-text-secondary)">{stage}</span>
				<StatusBadge status={stageStatus(stage)} type="review" resolve={resolveCreditStatus} />
			</div>
		{/each}
	</div>
	{#if status === "done"}
		<p class="mt-4 text-sm font-medium text-(--netz-success)">Document processed successfully.</p>
	{:else if status === "error"}
		<p class="mt-4 text-sm font-medium text-(--netz-danger)">Processing failed. Please retry.</p>
	{/if}
</Card>
