<!--
  @component ICMemoViewer
  Shows IC memo chapters with SSE streaming for in-progress generation.
  Renders typed CommitteeVoteOut[] with colored vote badges.
  Memo content is gated behind quorum reached OR esignature_status === "complete".
  Memo generation uses LongRunningAction from @netz/ui.
-->
<script lang="ts">
	import { Card, EmptyState, Skeleton, StatusBadge, LongRunningAction } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import type { SSEConnection } from "@netz/ui";
	import ICMemoStreamingChapter from "./ICMemoStreamingChapter.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import { formatDateTime } from "@netz/ui";

	import type { ICMemo, VotingStatus, CommitteeVoteOut } from "$lib/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

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

	// ── SSE stream for memo generation ──────────────────────
	type MemoStreamEvent = {
		state?: "idle" | "starting" | "in-flight" | "success" | "error" | "cancelled";
		progress?: number | null;
		stage?: string | null;
		chapter_number?: number | null;
		content?: string | null;
		error?: string | null;
		message?: string | null;
	};

	let streamingChapters = $state<Record<number, string>>({});
	let activeSse = $state<SSEConnection<MemoStreamEvent> | null>(null);

	// ── Quorum / visibility gate ─────────────────────────────
	const quorumReached = $derived.by(() => {
		if (!votingStatus) return false;
		return votingStatus.votes_cast >= votingStatus.quorum;
	});

	const esignComplete = $derived(icMemo?.esignature_status === "complete");

	const memoVisible = $derived(quorumReached || esignComplete);

	// ── Committee votes typed CommitteeVoteOut[] ─────────────
	const committeeVotes = $derived.by<CommitteeVoteOut[]>(() => {
		return (icMemo?.committee_votes ?? []) as CommitteeVoteOut[];
	});

	// ── Chapters ─────────────────────────────────────────────
	const chapters = $derived.by(() => {
		if (!icMemo?.chapters) return [];
		return icMemo.chapters;
	});

	// ── Vote badge helpers ───────────────────────────────────
	function voteColor(vote: string): string {
		const v = vote.toUpperCase();
		if (v === "APPROVED") return "var(--netz-success)";
		if (v === "REJECTED") return "var(--netz-danger)";
		return "var(--netz-text-secondary)"; // ABSTAINED / PENDING / unknown
	}

	function voteLabel(vote: string): string {
		const v = vote.toUpperCase();
		if (v === "APPROVED") return "Approved";
		if (v === "REJECTED") return "Rejected";
		if (v === "ABSTAINED") return "Abstained";
		return vote;
	}

	// ── Memo generation ──────────────────────────────────────
	async function startMemoGeneration() {
		// Disconnect previous stream if any
		activeSse?.disconnect();
		activeSse = null;
		streamingChapters = {};

		const api = createClientApiClient(getToken);
		const result = await api.post<{ job_id: string }>(`/funds/${fundId}/deals/${dealId}/ic-memo`);

		if (result.job_id) {
			const sse = createSSEStream<MemoStreamEvent>({
				url: `/api/v1/jobs/${result.job_id}/stream`,
				getToken,
				onEvent: (event) => {
					if (event.chapter_number != null && event.content != null) {
						streamingChapters = {
							...streamingChapters,
							[event.chapter_number]: event.content,
						};
					}
				},
			});
			activeSse = sse;
			sse.connect();
		}
	}

	function handleCancelMemo() {
		activeSse?.disconnect();
		activeSse = null;
	}

	// ── Clean up SSE on unmount ──────────────────────────────
	$effect(() => {
		return () => {
			activeSse?.disconnect();
		};
	});
</script>

{#if !icMemo}
	<!-- No memo yet — show LongRunningAction to generate -->
	<Card class="p-6">
		<LongRunningAction
			title="Generate IC Memo"
			description="Generate an Investment Committee memorandum for this deal using the AI engine."
			startLabel="Generate IC Memo"
			retryLabel="Retry Generation"
			cancelLabel="Cancel"
			idleMessage="Ready to generate the IC memorandum."
			successMessage="IC memo generated successfully."
			stream={activeSse}
			onStart={startMemoGeneration}
			onRetry={startMemoGeneration}
			onCancel={handleCancelMemo}
		/>
	</Card>
{:else}
	<div class="space-y-4">
		<!-- Voting status summary + committee votes -->
		{#if votingStatus}
			<Card class="p-4">
				<div class="mb-3 flex items-center justify-between">
					<p class="text-sm font-semibold text-[var(--netz-text-primary)]">IC Committee Voting</p>
					<StatusBadge status={String(votingStatus.status ?? "pending")} type="review" />
				</div>
				<p class="mb-4 text-xs text-[var(--netz-text-muted)]">
					{votingStatus.votes_cast ?? 0} / {votingStatus.quorum ?? 0} votes cast
					{#if quorumReached}
						— quorum reached
					{:else}
						— quorum not yet reached
					{/if}
				</p>

				<!-- Committee votes — typed CommitteeVoteOut[] -->
				{#if committeeVotes.length > 0}
					<div class="space-y-2">
						{#each committeeVotes as member (member.email)}
							<div class="flex items-start justify-between rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-alt)] px-3 py-2">
								<div class="space-y-0.5">
									<p class="text-sm font-medium text-[var(--netz-text-primary)]">{member.email}</p>
									{#if member.actor_capacity}
										<p class="text-xs text-[var(--netz-text-muted)]">{member.actor_capacity}</p>
									{/if}
									{#if member.signed_at}
										<p class="text-xs text-[var(--netz-text-muted)]">
											<time datetime={member.signed_at}>{formatDateTime(member.signed_at)}</time>
										</p>
									{/if}
									{#if member.signer_status}
										<p class="text-xs text-[var(--netz-text-muted)]">Signer: {member.signer_status}</p>
									{/if}
									{#if member.rationale}
										<p class="mt-1 text-xs leading-relaxed text-[var(--netz-text-secondary)]">
											"{member.rationale}"
										</p>
									{/if}
								</div>
								<span
									class="ml-3 inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold"
									style="background-color: color-mix(in srgb, {voteColor(member.vote)} 14%, var(--netz-surface)); color: {voteColor(member.vote)};"
								>
									{voteLabel(member.vote)}
								</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-xs text-[var(--netz-text-muted)]">No votes recorded yet.</p>
				{/if}
			</Card>
		{/if}

		<!-- Quorum gate: memo chapters only visible when quorum reached or e-sign complete -->
		{#if !memoVisible}
			<Card class="p-6 text-center">
				<EmptyState
					title="Memo Awaiting Quorum"
					description="The IC memo will be visible once the committee reaches quorum or the e-signature process is complete."
				/>
			</Card>
		{:else}
			<!-- Regeneration control via LongRunningAction -->
			<Card class="p-4">
				<LongRunningAction
					title="Regenerate IC Memo"
					description="Re-run the AI engine to update the memorandum with the latest evidence."
					startLabel="Regenerate"
					retryLabel="Retry"
					cancelLabel="Cancel"
					idleMessage="Memo is current. Click regenerate to refresh with latest evidence."
					successMessage="IC memo regenerated successfully."
					stream={activeSse}
					onStart={startMemoGeneration}
					onRetry={startMemoGeneration}
					onCancel={handleCancelMemo}
				/>
			</Card>

			<!-- Chapter list -->
			{#each chapters as chapter (chapter.chapter_number)}
				<Card class="p-4">
					<button
						class="flex w-full items-center justify-between text-left"
						onclick={() => {/* toggle expand */}}
					>
						<div class="flex items-center gap-3">
							<span class="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--netz-brand-primary)]/10 text-xs font-bold text-[var(--netz-brand-primary)]">
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

			{#if activeSse?.status === "connected" || activeSse?.status === "connecting"}
				<Card class="p-4">
					<Skeleton class="mb-2 h-4 w-48" />
					<Skeleton class="h-20 w-full" />
				</Card>
			{/if}
		{/if}
	</div>
{/if}
