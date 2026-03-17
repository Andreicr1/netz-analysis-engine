<!--
  @component ICMemoViewer
  Shows IC memo chapters with SSE streaming for in-progress generation.
  Uses subscribe-then-snapshot pattern from @netz/ui.
-->
<script lang="ts">
	import { Card, Button, EmptyState, Skeleton, StatusBadge } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import ICMemoStreamingChapter from "./ICMemoStreamingChapter.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	import type { ICMemo, VotingStatus } from "$lib/types/api";

	let {
		icMemo,
		votingStatus,
		fundId,
		dealId,
	}: {
		icMemo: ICMemo | null;
		votingStatus: VotingStatus | null;
		fundId: string;
		dealId: string;
	} = $props();

	let memo = $derived(icMemo);
	let voting = $derived(votingStatus);
	let generating = $state(false);
	let streamingChapters = $state<Record<string, string>>({});
	let activeSse = $state<ReturnType<typeof createSSEStream> | null>(null);

	let chapters = $derived.by(() => {
		if (!memo?.chapters) return [];
		return memo.chapters as Array<{ chapter_number: number; title: string; content: string; status: string }>;
	});

	// Clean up SSE connection on component unmount (#087)
	$effect(() => {
		return () => {
			activeSse?.disconnect();
		};
	});

	async function generateMemo() {
		generating = true;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<{ job_id: string }>(`/funds/${fundId}/deals/${dealId}/ic-memo`);

			if (result.job_id) {
				// Disconnect previous SSE if any
				activeSse?.disconnect();

				const sse = createSSEStream<{ chapter_number: number; content: string; status: string }>({
					url: `/api/v1/jobs/${result.job_id}/stream`,
					getToken,
					onEvent: (event) => {
						if (event.chapter_number != null) {
							streamingChapters = {
								...streamingChapters,
								[event.chapter_number]: event.content ?? "",
							};
						}
					},
					onError: () => { generating = false; },
				});
				activeSse = sse;
				sse.connect();
			}
		} catch {
			generating = false;
		}
	}
</script>

{#if !memo}
	<Card class="p-6 text-center">
		<EmptyState
			title="No IC Memo"
			description="Generate an Investment Committee memorandum for this deal."
		/>
		<Button onclick={generateMemo} disabled={generating} class="mt-4">
			{generating ? "Generating..." : "Generate IC Memo"}
		</Button>
	</Card>
{:else}
	<div class="space-y-4">
		<!-- Voting status -->
		{#if voting}
			<Card class="flex items-center justify-between p-4">
				<div>
					<p class="text-sm font-medium text-[var(--netz-text-primary)]">IC Voting</p>
					<p class="text-xs text-[var(--netz-text-muted)]">
						{voting.votes_cast ?? 0} / {voting.quorum ?? 0} votes
					</p>
				</div>
				<StatusBadge status={String(voting.status ?? "pending")} type="review" />
			</Card>
		{/if}

		<!-- Chapter list -->
		{#each chapters as chapter (chapter.chapter_number)}
			<Card class="p-4">
				<button
					class="flex w-full items-center justify-between text-left"
					onclick={() => {/* toggle expand */}}
				>
					<div class="flex items-center gap-3">
						<span class="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--netz-primary)]/10 text-xs font-bold text-[var(--netz-primary)]">
							{chapter.chapter_number}
						</span>
						<span class="text-sm font-medium">{chapter.title}</span>
					</div>
					<StatusBadge status={chapter.status} type="review" />
				</button>
				{#if chapter.content}
					<div class="mt-3 border-t border-[var(--netz-border)] pt-3 text-sm leading-relaxed whitespace-pre-wrap text-[var(--netz-text-secondary)]">
						{chapter.content}
					</div>
				{:else if streamingChapters[chapter.chapter_number]}
					<ICMemoStreamingChapter content={streamingChapters[chapter.chapter_number]} />
				{/if}
			</Card>
		{/each}

		{#if generating}
			<Card class="p-4">
				<Skeleton class="mb-2 h-4 w-48" />
				<Skeleton class="h-20 w-full" />
			</Card>
		{/if}
	</div>
{/if}
