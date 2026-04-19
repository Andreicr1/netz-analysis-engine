<!--
  X3.1 — Profile strip.

  Three-button strip rendering Conservative / Moderate / Growth.
  Active button is highlighted via terminal amber accent; each button
  embeds the profile's CVaR limit inline ("MODERATE · CVaR 7.50%")
  when available so the operator can eyeball the active risk budget
  without switching tabs.

  Uses formatPercent from @investintell/ui for the CVaR suffix
  (Decimal input: 0.075 → 7.50%).
-->
<script lang="ts">
	import { formatPercent } from "@investintell/ui";
	import {
		ALLOCATION_PROFILES,
		PROFILE_LABELS,
		type AllocationProfile,
	} from "$wealth/types/allocation-page";

	interface Props {
		current: AllocationProfile;
		/** CVaR limits keyed by profile — optional; renders em dash when null. */
		cvarByProfile?: Partial<Record<AllocationProfile, number | null>>;
		onchange: (profile: AllocationProfile) => void;
	}

	let { current, cvarByProfile = {}, onchange }: Props = $props();

	function cvarLabel(p: AllocationProfile): string {
		const raw = cvarByProfile[p];
		if (raw === undefined || raw === null) return "CVaR —";
		return `CVaR ${formatPercent(raw)}`;
	}
</script>

<div class="profile-strip" role="tablist" aria-label="Allocation profile">
	{#each ALLOCATION_PROFILES as profile (profile)}
		{@const isActive = profile === current}
		<button
			type="button"
			role="tab"
			aria-selected={isActive}
			class="profile-strip__btn"
			class:profile-strip__btn--active={isActive}
			onclick={() => onchange(profile)}
		>
			<span class="profile-strip__label">{PROFILE_LABELS[profile]}</span>
			<span class="profile-strip__sep">·</span>
			<span class="profile-strip__cvar">{cvarLabel(profile)}</span>
		</button>
	{/each}
</div>

<style>
	.profile-strip {
		display: flex;
		align-items: stretch;
		gap: 0;
		border-bottom: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		flex-shrink: 0;
	}

	.profile-strip__btn {
		flex: 1;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		background: transparent;
		border: none;
		border-right: var(--terminal-border-hairline);
		border-bottom: 2px solid transparent;
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		transition:
			color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			border-color var(--terminal-motion-tick) var(--terminal-motion-easing-out),
			background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	.profile-strip__btn:last-child {
		border-right: none;
	}
	.profile-strip__btn:hover {
		color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-sunken);
	}
	.profile-strip__btn:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: -2px;
	}

	.profile-strip__btn--active {
		color: var(--terminal-accent-amber);
		border-bottom-color: var(--terminal-accent-amber);
		background: var(--terminal-bg-panel-sunken);
	}

	.profile-strip__label {
		color: inherit;
	}
	.profile-strip__sep {
		color: var(--terminal-fg-muted);
		font-weight: 400;
	}
	.profile-strip__cvar {
		color: var(--terminal-fg-secondary);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}
	.profile-strip__btn--active .profile-strip__cvar {
		color: var(--terminal-fg-primary);
	}
</style>
