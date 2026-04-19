<script lang="ts">
    import { formatNumber } from "@investintell/ui";

    const COMPONENT_LABELS: Record<string, string> = {
        return_consistency: "Return Consistency",
        risk_adjusted_return: "Risk-Adjusted Return",
        drawdown_control: "Drawdown Control",
        information_ratio: "Information Ratio",
        flows_momentum: "Flows Momentum",
        fee_efficiency: "Fee Efficiency",
    };

    function humanLabel(key: string): string {
        return COMPONENT_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }

    interface Props {
        scoreComponents: Record<string, number> | null;
        managerScore: number | null;
    }

    let { scoreComponents, managerScore }: Props = $props();

    const entries = $derived(
        scoreComponents
            ? Object.entries(scoreComponents).map(([key, value]) => ({
                label: humanLabel(key),
                value,
            }))
            : []
    );
</script>

<div class="popover-root">
    <div class="popover-header">QUANTITATIVE ENGINE</div>

    {#if entries.length > 0}
        <table class="popover-table">
            <thead>
                <tr>
                    <th class="text-left">COMPONENT</th>
                    <th class="text-right">SCORE</th>
                </tr>
            </thead>
            <tbody>
                {#each entries as comp}
                    <tr>
                        <td class="text-left comp-name">{comp.label}</td>
                        <td class="text-right comp-score">{formatNumber(comp.value, 1)}</td>
                    </tr>
                {/each}
            </tbody>
        </table>

        {#if managerScore != null}
            <div class="popover-footer">
                COMPOSITE: {formatNumber(managerScore, 0)}/100
            </div>
        {/if}
    {:else}
        <div class="popover-empty">No score components available</div>
    {/if}
</div>

<style>
    .popover-root {
        background: var(--terminal-bg-panel-raised);
        border: var(--terminal-border-hairline);
        width: 280px;
        display: flex;
        flex-direction: column;
        font-family: var(--terminal-font-mono);
    }

    .popover-header {
        font-size: var(--terminal-text-10);
        font-weight: 700;
        letter-spacing: 0.05em;
        color: var(--terminal-fg-secondary);
        padding: 8px 12px;
        border-bottom: var(--terminal-border-hairline);
        background: var(--terminal-bg-panel);
    }

    .popover-table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--terminal-text-11);
    }

    .popover-table th {
        font-size: 9px;
        color: var(--terminal-fg-tertiary);
        font-weight: 600;
        padding: 6px 12px;
        border-bottom: var(--terminal-border-hairline);
        background: var(--terminal-bg-panel);
    }

    .popover-table td {
        padding: 6px 12px;
        border-bottom: 1px solid var(--terminal-fg-disabled);
    }

    .text-left { text-align: left; }
    .text-right { text-align: right; }

    .comp-name {
        color: var(--terminal-fg-secondary);
    }

    .comp-score {
        color: var(--terminal-fg-primary);
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }

    .popover-footer {
        padding: 10px 12px;
        font-size: var(--terminal-text-10);
        font-weight: 700;
        color: var(--terminal-accent-cyan);
        border-top: var(--terminal-border-hairline);
    }

    .popover-empty {
        padding: 16px 12px;
        font-size: var(--terminal-text-11);
        color: var(--terminal-fg-muted);
        text-align: center;
    }
</style>
