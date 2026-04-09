<!--
  BuilderRightStack — Phase 4 Task 4.5 replacement host for the
  Builder's third column. Owns 4 tabs:

    - Calibration — the 63-input Phase 4 CalibrationPanel
    - Narrative   — the ConstructionNarrative fed by the last Phase 3
                    construct run
    - Stress      — the StressScenarioPanel (Matrix + Custom)
    - Chart       — the legacy MainPortfolioChart NAV synthesis,
                    preserved so the "View Chart" button still works

  The tab state is a local $state because Phase 5 will introduce a
  proper allowed-actions-driven tab host. Until then, the parent uses
  the imperative ``setActive`` prop to auto-switch on events — e.g.
  on ``runPhase === "done"`` the BuilderColumn flips the active tab
  to ``narrative`` (DL4 + plan §Phase 4 Step 3).

  Per CLAUDE.md Stability Guardrails charter §3 — <svelte:boundary>
  + PanelErrorState failed snippet.
-->
<script lang="ts" module>
	export type BuilderRightTab = "calibration" | "narrative" | "stress" | "chart";
</script>

<script lang="ts">
	import * as Tabs from "@investintell/ui/components/ui/tabs";
	import { EmptyState } from "@investintell/ui";
	import { PanelErrorState } from "@investintell/ui/runtime";
	import ConstructionNarrative from "./ConstructionNarrative.svelte";
	import StressScenarioPanel from "./StressScenarioPanel.svelte";
	import MainPortfolioChart from "./MainPortfolioChart.svelte";

	interface Props {
		/** Currently-visible tab. Controlled by the parent. */
		active: BuilderRightTab;
		onActiveChange: (tab: BuilderRightTab) => void;
	}

	let { active, onActiveChange }: Props = $props();
</script>

<svelte:boundary>
	<div class="brs-root">
		<Tabs.Root
			value={active}
			onValueChange={(v) => onActiveChange(v as BuilderRightTab)}
			class="brs-root-tabs"
		>
			<Tabs.List class="brs-tabs">
				<Tabs.Trigger value="calibration">Calibration</Tabs.Trigger>
				<Tabs.Trigger value="narrative">Narrative</Tabs.Trigger>
				<Tabs.Trigger value="stress">Stress</Tabs.Trigger>
				<Tabs.Trigger value="chart">Chart</Tabs.Trigger>
			</Tabs.List>

			<Tabs.Content value="calibration" class="brs-content">
				<div class="brs-placeholder">
					<EmptyState
						title="Calibration Results"
						message="Applied calibration summary and optimizer trace will appear here after a construction run. Edit calibration inputs in the Policy tab on the left sidebar."
					/>
				</div>
			</Tabs.Content>

			<Tabs.Content value="narrative" class="brs-content">
				<ConstructionNarrative />
			</Tabs.Content>

			<Tabs.Content value="stress" class="brs-content">
				<StressScenarioPanel />
			</Tabs.Content>

			<Tabs.Content value="chart" class="brs-content">
				<MainPortfolioChart />
			</Tabs.Content>
		</Tabs.Root>
	</div>

	{#snippet failed(err: unknown, reset: () => void)}
		<PanelErrorState
			title="Builder right stack failed"
			message={err instanceof Error ? err.message : "Unexpected error in the Builder right stack."}
			onRetry={reset}
		/>
	{/snippet}
</svelte:boundary>

<style>
	.brs-root {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 0;
		background: #141519;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	:global(.brs-root-tabs) {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-height: 0;
	}
	:global(.brs-tabs) {
		display: flex;
		gap: 6px;
		padding: 16px 16px 0;
		flex-shrink: 0;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
	}
	:global(.brs-content) {
		flex: 1;
		min-height: 0;
		overflow: hidden;
	}
	.brs-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 24px;
	}
</style>
