<!--
  StressScenarioPanel — Phase 4 Task 4.4 replacement for the legacy
  StressTestPanel. Per OD-8 (locked), the panel ships with two tabs:

    - Matrix — reads the 4 canonical DL7 scenarios from the last
               persisted construction run. Drives the Builder's "how
               does this portfolio behave in each regime" question.
    - Custom — the existing ad-hoc shock form, now routed through the
               new workspace SSE-based runStressTest.

  Per CLAUDE.md Stability Guardrails charter §3 — the panel is wrapped
  in <svelte:boundary> with the PanelErrorState failed snippet.
-->
<script lang="ts">
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import StressScenarioMatrixTab from "./StressScenarioMatrixTab.svelte";
	import StressCustomShockTab from "./StressCustomShockTab.svelte";

	let activeTab = $state<"matrix" | "custom">("matrix");
</script>

<svelte:boundary>
	<div class="ssp-root">
		<header class="ssp-header">
			<span class="ssp-kicker">Stress</span>
			<span class="ssp-title">Scenario coverage</span>
		</header>

		<Tabs.Root value={activeTab} onValueChange={(v) => (activeTab = v as typeof activeTab)}>
			<Tabs.List class="ssp-tabs">
				<Tabs.Trigger value="matrix">Matrix</Tabs.Trigger>
				<Tabs.Trigger value="custom">Custom</Tabs.Trigger>
			</Tabs.List>

			<Tabs.Content value="matrix">
				<div class="ssp-section">
					<StressScenarioMatrixTab />
				</div>
			</Tabs.Content>

			<Tabs.Content value="custom">
				<div class="ssp-section">
					<StressCustomShockTab />
				</div>
			</Tabs.Content>
		</Tabs.Root>
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Stress panel failed to render"
			message={err instanceof Error ? err.message : "Unexpected error in the stress scenario panel."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.ssp-root {
		display: flex;
		flex-direction: column;
		gap: 12px;
		height: 100%;
		min-height: 0;
		padding: 16px;
		background: #141519;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	.ssp-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.ssp-kicker {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.ssp-title {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary, #ffffff);
	}
	:global(.ssp-tabs) {
		display: flex;
		gap: 6px;
		flex-shrink: 0;
	}
	.ssp-section {
		padding-top: 12px;
	}
</style>
