<!--
  JobProgressTracker — step-based progress UI for background report generation.
  Reacts to the SSE stream via ActiveJob state from the PortfolioReportsStore.
-->
<script lang="ts">
	import type { ActiveJob } from "$lib/stores/portfolio-reports.svelte";
	import type { ReportStage, ReportType } from "$lib/types/model-portfolio";
	import { REPORT_TYPE_LABELS, REPORT_STAGE_LABELS } from "$lib/types/model-portfolio";

	interface Props {
		jobs: ActiveJob[];
	}

	let { jobs }: Props = $props();

	/** Ordered pipeline stages for progress visualization */
	const PIPELINE_STAGES: ReportStage[] = [
		"QUEUED",
		"FETCHING_MARKET_DATA",
		"RUNNING_QUANT_ENGINE",
		"SYNTHESIZING_LLM",
		"GENERATING_PDF",
		"STORING_PDF",
		"COMPLETED",
	];

	function stageIndex(stage: ReportStage): number {
		const idx = PIPELINE_STAGES.indexOf(stage);
		return idx >= 0 ? idx : 0;
	}

	function stageStatus(
		currentStage: ReportStage,
		jobStatus: string,
		checkStage: ReportStage,
	): "completed" | "active" | "pending" | "failed" {
		if (jobStatus === "failed") return "failed";
		const current = stageIndex(currentStage);
		const check = stageIndex(checkStage);
		if (check < current) return "completed";
		if (check === current) return jobStatus === "completed" ? "completed" : "active";
		return "pending";
	}
</script>

{#if jobs.length > 0}
	<section class="mp-section mp-section--full">
		<h3 class="mp-section-title">
			Active Jobs
			<span class="mp-section-count">{jobs.filter((j) => j.status === "running").length} running</span>
		</h3>

		<div class="jpt-list">
			{#each jobs as job (job.jobId)}
				<div class="jpt-card" class:jpt-card--failed={job.status === "failed"} class:jpt-card--done={job.status === "completed"}>
					<div class="jpt-header">
						<span class="jpt-type">{REPORT_TYPE_LABELS[job.reportType]}</span>
						<span class="jpt-status" class:jpt-status--running={job.status === "running"} class:jpt-status--done={job.status === "completed"} class:jpt-status--failed={job.status === "failed"}>
							{job.status === "running" ? `${job.pct}%` : job.status}
						</span>
					</div>

					<!-- Progress bar -->
					<div class="jpt-bar-track">
						<div
							class="jpt-bar-fill"
							class:jpt-bar--failed={job.status === "failed"}
							class:jpt-bar--done={job.status === "completed"}
							style:width="{job.pct}%"
						></div>
					</div>

					<!-- Step indicators -->
					<div class="jpt-stages">
						{#each PIPELINE_STAGES as stage (stage)}
							{@const s = stageStatus(job.stage, job.status, stage)}
							<div class="jpt-stage" class:jpt-stage--completed={s === "completed"} class:jpt-stage--active={s === "active"} class:jpt-stage--failed={s === "failed"}>
								<div class="jpt-dot"></div>
								<span class="jpt-stage-label">{REPORT_STAGE_LABELS[stage]}</span>
							</div>
						{/each}
					</div>

					<!-- Current message -->
					<p class="jpt-message">{job.message}</p>

					{#if job.error}
						<p class="jpt-error">{job.error}</p>
					{/if}
				</div>
			{/each}
		</div>
	</section>
{/if}

<style>
	.jpt-list {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-sm, 12px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.jpt-card {
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-md, 8px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface);
	}

	.jpt-card--failed {
		border-color: color-mix(in srgb, var(--ii-danger) 40%, transparent);
	}

	.jpt-card--done {
		border-color: color-mix(in srgb, var(--ii-success) 40%, transparent);
	}

	.jpt-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--ii-space-stack-xs, 8px);
	}

	.jpt-type {
		font-weight: 600;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-primary);
	}

	.jpt-status {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.jpt-status--running { color: var(--ii-info); }
	.jpt-status--done { color: var(--ii-success); }
	.jpt-status--failed { color: var(--ii-danger); }

	/* Progress bar */
	.jpt-bar-track {
		height: 4px;
		background: color-mix(in srgb, var(--ii-border) 60%, transparent);
		border-radius: 2px;
		overflow: hidden;
		margin-bottom: var(--ii-space-stack-sm, 12px);
	}

	.jpt-bar-fill {
		height: 100%;
		background: var(--ii-info);
		border-radius: 2px;
		transition: width 300ms ease;
	}

	.jpt-bar--done { background: var(--ii-success); }
	.jpt-bar--failed { background: var(--ii-danger); }

	/* Stage pipeline */
	.jpt-stages {
		display: flex;
		gap: 2px;
		margin-bottom: var(--ii-space-stack-xs, 8px);
		overflow-x: auto;
	}

	.jpt-stage {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		flex: 1;
		min-width: 60px;
	}

	.jpt-dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: color-mix(in srgb, var(--ii-border) 80%, transparent);
		transition: background 200ms ease, box-shadow 200ms ease;
	}

	.jpt-stage--completed .jpt-dot {
		background: var(--ii-success);
	}

	.jpt-stage--active .jpt-dot {
		background: var(--ii-info);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--ii-info) 25%, transparent);
		animation: pulse 1.5s ease-in-out infinite;
	}

	.jpt-stage--failed .jpt-dot {
		background: var(--ii-danger);
	}

	@keyframes pulse {
		0%, 100% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--ii-info) 25%, transparent); }
		50% { box-shadow: 0 0 0 6px color-mix(in srgb, var(--ii-info) 10%, transparent); }
	}

	.jpt-stage-label {
		font-size: 0.625rem;
		color: var(--ii-text-muted);
		text-align: center;
		line-height: 1.2;
		white-space: nowrap;
	}

	.jpt-stage--completed .jpt-stage-label { color: var(--ii-success); }
	.jpt-stage--active .jpt-stage-label { color: var(--ii-info); font-weight: 600; }

	/* Message */
	.jpt-message {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
	}

	.jpt-error {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-danger);
		margin-top: var(--ii-space-stack-2xs, 6px);
	}
</style>
