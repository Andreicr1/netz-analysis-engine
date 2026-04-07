<!--
  ReportGeneratorCard — select a report type and trigger generation.
  Feeds into the PortfolioReportsStore for SSE-tracked background jobs.
-->
<script lang="ts">
	import { Button } from "@investintell/ui/components/ui/button";
	import type { ReportType, ReportGenerateRequest } from "$lib/types/model-portfolio";
	import { REPORT_TYPE_LABELS } from "$lib/types/model-portfolio";

	interface Props {
		canGenerate: boolean;
		generating: boolean;
		onGenerate: (req: ReportGenerateRequest) => void;
	}

	let { canGenerate, generating, onGenerate }: Props = $props();

	let reportType = $state<ReportType>("fact_sheet");
	let language = $state<"pt" | "en">("pt");
	let format = $state<"executive" | "institutional">("executive");

	function handleGenerate() {
		onGenerate({
			report_type: reportType,
			language,
			format,
		});
	}

	const REPORT_DESCRIPTIONS: Record<ReportType, string> = {
		fact_sheet: "Executive or institutional PDF summarizing portfolio composition, performance, and risk metrics.",
		monthly_report: "Monthly performance review with attribution analysis, risk metrics, and outlook.",
	};
</script>

<section class="mp-section mp-section--full">
	<h3 class="mp-section-title">Generate Report</h3>
	<div class="rg-content">
		<div class="rg-controls">
			<label class="rg-field">
				<span class="rg-label">Report Type</span>
				<select class="rg-select" bind:value={reportType}>
					{#each Object.entries(REPORT_TYPE_LABELS) as [value, label] (value)}
						<option {value}>{label}</option>
					{/each}
				</select>
			</label>

			<label class="rg-field">
				<span class="rg-label">Language</span>
				<select class="rg-select" bind:value={language}>
					<option value="pt">Portugues</option>
					<option value="en">English</option>
				</select>
			</label>

			{#if reportType === "fact_sheet"}
				<label class="rg-field">
					<span class="rg-label">Format</span>
					<select class="rg-select" bind:value={format}>
						<option value="executive">Executive</option>
						<option value="institutional">Institutional</option>
					</select>
				</label>
			{/if}

			<div class="rg-action">
				<Button
					size="sm"
					onclick={handleGenerate}
					disabled={!canGenerate || generating}
				>
					{generating ? "Generating…" : "Generate"}
				</Button>
			</div>
		</div>

		<p class="rg-description">{REPORT_DESCRIPTIONS[reportType]}</p>
	</div>
</section>

<style>
	.rg-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.rg-controls {
		display: flex;
		align-items: flex-end;
		gap: var(--ii-space-inline-md, 16px);
		flex-wrap: wrap;
	}

	.rg-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.rg-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.rg-select {
		font-size: var(--ii-text-small, 0.8125rem);
		padding: 6px 10px;
		border-radius: var(--ii-radius-sm, 6px);
		border: 1px solid var(--ii-border);
		background: var(--ii-surface);
		color: var(--ii-text-primary);
		min-width: 140px;
	}

	.rg-action {
		display: flex;
		align-items: flex-end;
	}

	.rg-description {
		margin-top: var(--ii-space-stack-sm, 12px);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		line-height: 1.5;
		max-width: 600px;
	}
</style>
