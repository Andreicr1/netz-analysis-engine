<!--
  @component ICMemoViewer
  Shows IC memo chapters with SSE streaming for in-progress generation.
  Renders typed CommitteeVoteOut[] with colored vote badges.
  Memo content is gated behind quorum reached OR esignature_status === "complete".
  Memo generation uses LongRunningAction from @netz/ui.
  BL-08: Evidence Pack Inspector — per-chapter "View Sources" sheet.
  BL-10: AI Content Markers — provenance caption per chapter.
-->
<script lang="ts">
	import { Card, EmptyState, Skeleton, StatusBadge, LongRunningAction, Sheet } from "@netz/ui";
	import { createSSEStream } from "@netz/ui/utils";
	import type { SSEConnection } from "@netz/ui";
	import ICMemoStreamingChapter from "./ICMemoStreamingChapter.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import { formatDateTime, formatDate, formatPercent, formatNumber } from "@netz/ui";
	import { resolveCreditStatus } from "$lib/utils/status-maps";

	import type { ICMemo, VotingStatus, CommitteeVoteOut, EvidencePack, EvidenceCitation } from "$lib/types/api";

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

	// ── Evidence Pack state (BL-08) ──────────────────────────
	let evidencePack = $state<EvidencePack | null>(null);
	let evidenceLoading = $state(false);
	let evidenceError = $state<string | null>(null);
	let sheetOpen = $state(false);
	let activeChapterNumber = $state<number | null>(null);

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

	// ── Citations for the active chapter ────────────────────
	const citations = $derived<EvidenceCitation[]>(
		evidencePack?.evidenceJson?.citations ?? []
	);

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

	// ── Evidence Pack helpers (BL-08) ────────────────────────
	function extractFilename(blobName: string): string {
		return blobName.split("/").at(-1) ?? blobName;
	}

	function formatPageRange(start: number | null, end: number | null): string {
		if (start == null && end == null) return "—";
		if (start != null && end != null && start !== end) return `pp. ${start}–${end}`;
		return `p. ${start ?? end}`;
	}

	function formatScore(score: number | null): string {
		if (score == null) return "—";
		return formatPercent(score, 1);
	}

	async function openEvidenceSheet(chapterNumber: number) {
		activeChapterNumber = chapterNumber;
		sheetOpen = true;

		// Load on demand — only fetch if not already cached
		if (evidencePack !== null) return;

		evidenceLoading = true;
		evidenceError = null;

		try {
			const api = createClientApiClient(getToken);
			const data = await api.get<EvidencePack>(
				`/funds/${fundId}/ai/pipeline/deals/${dealId}/evidence-pack`
			);
			evidencePack = data;
		} catch (err) {
			evidenceError = err instanceof Error ? err.message : "Failed to load evidence pack.";
		} finally {
			evidenceLoading = false;
		}
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
			slaSeconds={180}
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
					<p class="text-sm font-semibold text-(--netz-text-primary)">IC Committee Voting</p>
					<StatusBadge status={String(votingStatus.status ?? "pending")} type="review" resolve={resolveCreditStatus} />
				</div>
				<p class="mb-4 text-xs text-(--netz-text-muted)">
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
							<div class="flex items-start justify-between rounded-md border border-(--netz-border) bg-(--netz-surface-alt) px-3 py-2">
								<div class="space-y-0.5">
									<p class="text-sm font-medium text-(--netz-text-primary)">{member.email}</p>
									{#if member.actor_capacity}
										<p class="text-xs text-(--netz-text-muted)">{member.actor_capacity}</p>
									{/if}
									{#if member.signed_at}
										<p class="text-xs text-(--netz-text-muted)">
											<time datetime={member.signed_at}>{formatDateTime(member.signed_at)}</time>
										</p>
									{/if}
									{#if member.signer_status}
										<p class="text-xs text-(--netz-text-muted)">Signer: {member.signer_status}</p>
									{/if}
									{#if member.rationale}
										<p class="mt-1 text-xs leading-relaxed text-(--netz-text-secondary)">
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
					<p class="text-xs text-(--netz-text-muted)">No votes recorded yet.</p>
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
					slaSeconds={180}
					stream={activeSse}
					onStart={startMemoGeneration}
					onRetry={startMemoGeneration}
					onCancel={handleCancelMemo}
				/>
			</Card>

			<!-- Chapter list -->
			{#each chapters as chapter (chapter.chapter_number)}
				<Card class="p-4">
					<div class="flex items-center justify-between">
						<button
							class="flex flex-1 items-center gap-3 text-left"
							onclick={() => {/* toggle expand */}}
						>
							<span class="flex h-7 w-7 items-center justify-center rounded-full bg-(--netz-brand-primary)/10 text-xs font-bold text-(--netz-brand-primary)">
								{chapter.chapter_number}
							</span>
							<span class="text-sm font-medium">{chapter.title}</span>
						</button>
						<div class="ml-3 flex items-center gap-2">
							<!-- BL-08: View Sources button -->
							<button
								class="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-(--netz-info) transition-colors hover:bg-(--netz-info)/8 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--netz-info)/40"
								onclick={() => openEvidenceSheet(chapter.chapter_number)}
								aria-label="View evidence sources for chapter {chapter.chapter_number}"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="12"
									height="12"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
									<path d="M14 2v4a2 2 0 0 0 2 2h4" />
									<path d="M10 9H8" />
									<path d="M16 13H8" />
									<path d="M16 17H8" />
								</svg>
								View Sources
							</button>
							<StatusBadge status={chapter.status} type="review" resolve={resolveCreditStatus} />
						</div>
					</div>

					<!-- BL-10: AI Content Marker — provenance caption -->
					{#if chapter.model_version || chapter.generated_at}
						<p
							class="mt-1 pl-10"
							style="font-size: var(--netz-text-caption); color: var(--netz-info); line-height: 1.4;"
						>
							Generated
							{#if chapter.model_version}by {chapter.model_version}{/if}
							{#if chapter.generated_at}
								{#if chapter.model_version} on {/if}
								{formatDate(chapter.generated_at)}
							{/if}
						</p>
					{/if}

					{#if chapter.content}
						<div class="mt-3 border-t border-(--netz-border) pt-3 text-sm leading-relaxed whitespace-pre-wrap text-(--netz-text-secondary)">
							{chapter.content}
						</div>
					{:else if streamingChapters[chapter.chapter_number]}
						<ICMemoStreamingChapter content={streamingChapters[chapter.chapter_number] ?? ""} />
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

<!-- BL-08: Evidence Pack Inspector Sheet -->
<Sheet bind:open={sheetOpen} side="right">
	<div class="space-y-5">
		<!-- Header -->
		<div>
			<h2 class="pr-10 text-base font-semibold text-(--netz-text-primary)">Evidence Sources</h2>
			{#if activeChapterNumber != null}
				<p class="mt-0.5 text-xs text-(--netz-text-muted)">
					Chapter {activeChapterNumber} · extracted citations
				</p>
			{/if}
		</div>

		<!-- Evidence Pack metadata -->
		{#if evidencePack && !evidenceLoading}
			<div class="rounded-md border border-(--netz-border) bg-(--netz-surface-alt) px-3 py-2 space-y-1">
				{#if evidencePack.versionTag}
					<p class="text-xs text-(--netz-text-muted)">Version: <span class="text-(--netz-text-secondary)">{evidencePack.versionTag}</span></p>
				{/if}
				{#if evidencePack.tokenCount != null}
					<p class="text-xs text-(--netz-text-muted)">Tokens: <span class="text-(--netz-text-secondary)">{formatNumber(evidencePack.tokenCount, 0)}</span></p>
				{/if}
				{#if evidencePack.generatedAt}
					<p class="text-xs text-(--netz-text-muted)">Generated: <span class="text-(--netz-text-secondary)">{formatDateTime(evidencePack.generatedAt)}</span></p>
				{/if}
			</div>
		{/if}

		<!-- Loading state -->
		{#if evidenceLoading}
			<div class="space-y-3">
				<Skeleton class="h-4 w-3/4" />
				<Skeleton class="h-16 w-full" />
				<Skeleton class="h-16 w-full" />
				<Skeleton class="h-16 w-full" />
			</div>

		<!-- Error state -->
		{:else if evidenceError}
			<div class="rounded-md border border-(--netz-danger)/20 bg-(--netz-danger)/6 px-3 py-3">
				<p class="text-sm text-(--netz-danger)">{evidenceError}</p>
			</div>

		<!-- No citations -->
		{:else if citations.length === 0}
			<div class="py-8 text-center">
				<p class="text-sm text-(--netz-text-muted)">No evidence sources recorded</p>
			</div>

		<!-- Citation list -->
		{:else}
			<div class="space-y-3">
				{#each citations as citation, idx (citation.chunk_id)}
					<div class="rounded-md border border-(--netz-border) bg-(--netz-surface) p-3 space-y-1.5">
						<!-- Source filename -->
						<p class="text-sm font-medium text-(--netz-text-primary) break-all leading-snug">
							{extractFilename(citation.blob_name)}
						</p>

						<!-- Doc type + page range row -->
						<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
							{#if citation.doc_type}
								<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide bg-(--netz-surface-alt) text-(--netz-text-muted) border border-(--netz-border)">
									{citation.doc_type}
								</span>
							{/if}
							<span class="text-xs text-(--netz-text-muted)">
								{formatPageRange(citation.page_start, citation.page_end)}
							</span>
						</div>

						<!-- Chunk ID + score row -->
						<div class="flex items-center justify-between pt-0.5">
							<p class="font-mono text-[10px] text-(--netz-text-muted) truncate max-w-[70%]" title={citation.chunk_id}>
								{citation.chunk_id}
							</p>
							{#if citation.score != null}
								<span
									class="text-xs font-semibold tabular-nums"
									style="color: var(--netz-info);"
									title="Extraction confidence"
								>
									{formatScore(citation.score)}
								</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</Sheet>
