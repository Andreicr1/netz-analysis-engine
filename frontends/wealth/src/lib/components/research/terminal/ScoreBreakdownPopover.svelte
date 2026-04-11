<script lang="ts">
    import { formatNumber } from "@investintell/ui";
    interface ScoreComponent {
        name: string;
        weight: number;
        score: number;
    }

    interface ScoreData {
        totalScore: number;
        penaltyApplied: boolean;
        missingData: string[];
        components: ScoreComponent[];
    }

    interface Props {
        scoreData: ScoreData;
    }

    let { scoreData }: Props = $props();
</script>

<div class="popover-root">
    <div class="popover-header">QUANTITATIVE ENGINE</div>
    
    <table class="popover-table">
        <thead>
            <tr>
                <th class="text-left">COMPONENT</th>
                <th class="text-right">WEIGHT</th>
                <th class="text-right">SCORE</th>
            </tr>
        </thead>
        <tbody>
            {#each scoreData.components as comp}
                <tr>
                    <td class="text-left comp-name">{comp.name}</td>
                    <td class="text-right comp-weight">{formatNumber(comp.weight * 100, 0)}%</td>
                    <td class="text-right comp-score">{formatNumber(comp.score, 1)}</td>
                </tr>
            {/each}
        </tbody>
    </table>

    {#if scoreData.penaltyApplied && scoreData.missingData.length > 0}
        <div class="popover-footer penalty">
            * PENALTY APPLIED: MISSING {scoreData.missingData.join(', ').toUpperCase()} (PEER MEDIAN - 5PTS).
        </div>
    {/if}
</div>

<style>
    .popover-root {
        background: #0e1320;
        border: 1px solid #1e293b;
        width: 280px;
        display: flex;
        flex-direction: column;
        font-family: "Urbanist", system-ui, sans-serif;
    }

    .popover-header {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.05em;
        color: #94a3b8;
        padding: 8px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        background: #0b0f1a;
    }

    .popover-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 11px;
    }

    .popover-table th {
        font-size: 9px;
        color: #64748b;
        font-weight: 600;
        padding: 6px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        background: rgba(255, 255, 255, 0.01);
    }

    .popover-table td {
        padding: 6px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.02);
    }

    .text-left { text-align: left; }
    .text-right { text-align: right; }

    .comp-name {
        color: #cbd5e1;
    }

    .comp-weight {
        color: #64748b;
        font-variant-numeric: tabular-nums;
        font-family: monospace;
    }

    .comp-score {
        color: #ffffff;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        font-family: monospace;
    }

    .popover-footer {
        padding: 10px 12px;
        font-size: 10px;
        font-weight: 700;
        font-family: monospace;
    }

    .penalty {
        color: #ef4444;
        background: rgba(239, 68, 68, 0.05);
        border-top: 1px solid rgba(239, 68, 68, 0.1);
        animation: subtlePulse 2s infinite alternate;
    }

    @keyframes subtlePulse {
        0% { opacity: 0.8; }
        100% { opacity: 1; }
    }
</style>
