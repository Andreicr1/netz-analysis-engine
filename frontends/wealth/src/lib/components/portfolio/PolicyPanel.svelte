<!--
  PolicyPanel — Adjusts the quantitative constraints for the Clarabel optimizer.
  Features modern, interactive sliders for intuitive calibration.
-->
<script lang="ts">
    import { workspace } from "$lib/state/portfolio-workspace.svelte";
    import { EmptyState, formatPercent } from "@investintell/ui";

    // Policy constraints are local UI state — backend reads from StrategicAllocation table.
    // These defaults match the moderate profile; real values load when policy API is wired.
    let cvarLimit = $state(-0.08);
    let maxConcentration = $state(0.15);

    function handleCvarChange(e: Event) {
        const val = parseFloat((e.target as HTMLInputElement).value);
        workspace.updatePolicy("cvar_limit", val);
    }

    function handleConcentrationChange(e: Event) {
        const val = parseFloat((e.target as HTMLInputElement).value);
        workspace.updatePolicy("max_single_fund_weight", val);
    }
</script>

{#if !workspace.portfolio}
    <div class="p-6">
        <EmptyState
            title="No portfolio selected"
            message="Select a model portfolio to adjust its investment policies."
        />
    </div>
{:else}
    <div class="flex flex-col gap-8 p-5">
        <div class="space-y-6">
            <h3
                class="text-xs font-bold text-muted-foreground uppercase tracking-widest border-b border-border pb-2"
            >
                Risk Constraints
            </h3>

            <!-- CVaR Limit Slider -->
            <div class="flex flex-col gap-3">
                <div class="flex justify-between items-center">
                    <label
                        for="cvar-slider"
                        class="text-sm font-semibold text-foreground"
                        >Max CVaR Limit (95%)</label
                    >
                    <span
                        class="text-sm font-bold"
                        style="color: var(--netz-danger)"
                        >{formatPercent(cvarLimit)}</span
                    >
                </div>
                <input
                    id="cvar-slider"
                    type="range"
                    min="-0.25"
                    max="-0.02"
                    step="0.01"
                    value={cvarLimit}
                    oninput={handleCvarChange}
                />
                <div
                    class="flex justify-between text-xs font-medium text-muted-foreground"
                >
                    <span>-25% (Looser)</span>
                    <span>-2% (Tighter)</span>
                </div>
            </div>

            <!-- Max Concentration Slider -->
            <div class="flex flex-col gap-3 pt-2">
                <div class="flex justify-between items-center">
                    <label
                        for="conc-slider"
                        class="text-sm font-semibold text-foreground"
                        >Max Single Fund Weight</label
                    >
                    <span class="text-sm font-bold text-primary"
                        >{formatPercent(maxConcentration)}</span
                    >
                </div>
                <input
                    id="conc-slider"
                    type="range"
                    min="0.05"
                    max="0.40"
                    step="0.01"
                    value={maxConcentration}
                    oninput={handleConcentrationChange}
                />
                <div
                    class="flex justify-between text-xs font-medium text-muted-foreground"
                >
                    <span>5%</span>
                    <span>40%</span>
                </div>
            </div>
        </div>

        <div
            class="bg-surface-alt p-4 rounded-lg border border-border-subtle shadow-sm"
        >
            <p class="text-xs text-muted-foreground leading-relaxed">
                <strong>Note:</strong> These constraints govern the
                <span
                    class="font-mono text-[10px] bg-background px-1 rounded border border-border"
                    >CLARABEL</span
                > optimizer. Tighter CVaR limits may activate the Phase 2 variance-ceiling
                fallback to preserve numerical admissibility.
            </p>
        </div>
    </div>
{/if}

<style>
    /* Modern cross-browser Slider Styling mapping to Netz Design Tokens */
    input[type="range"] {
        -webkit-appearance: none;
        appearance: none;
        width: 100%;
        background: transparent;
    }

    input[type="range"]::-webkit-slider-runnable-track {
        width: 100%;
        height: 6px;
        cursor: pointer;
        background: var(--netz-border-strong);
        border-radius: var(--netz-radius-pill);
    }

    input[type="range"]::-webkit-slider-thumb {
        height: 20px;
        width: 20px;
        border-radius: 50%;
        background: var(--netz-surface);
        border: 3px solid var(--netz-brand-primary);
        cursor: pointer;
        -webkit-appearance: none;
        margin-top: -7px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
        transition:
            transform 100ms var(--netz-ease-out),
            box-shadow 100ms var(--netz-ease-out);
    }

    input[type="range"]::-webkit-slider-thumb:hover {
        transform: scale(1.15);
    }

    input[type="range"]:focus {
        outline: none;
    }

    input[type="range"]:focus::-webkit-slider-thumb {
        box-shadow: 0 0 0 4px var(--netz-focus-ring);
    }

    /* Firefox support */
    input[type="range"]::-moz-range-track {
        width: 100%;
        height: 6px;
        cursor: pointer;
        background: var(--netz-border-strong);
        border-radius: var(--netz-radius-pill);
    }

    input[type="range"]::-moz-range-thumb {
        height: 20px;
        width: 20px;
        border-radius: 50%;
        background: var(--netz-surface);
        border: 3px solid var(--netz-brand-primary);
        cursor: pointer;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
        transition: transform 100ms var(--netz-ease-out);
    }
</style>
