<!--
  StrategicApprovalBanner — CTA between STRATEGIC and PORTFOLIO tabs.

  Surfaces the approval state for the current profile's strategic
  allocation. When approved, shows a green "Approved" badge with
  a "Continue to Portfolio" action. When not approved, shows the
  required action (propose or approve).

  Emits ``onNavigate`` event — parent handles tab switching.
-->
<script lang="ts">
	import { formatDateTime } from "@investintell/ui";
	import { approval } from "../../state/workspace-approval.svelte";
	import type { ApprovalStatus } from "../../state/workspace-approval.svelte";

	interface Props {
		onNavigate?: (to: "portfolio") => void;
	}

	let { onNavigate }: Props = $props();

	const status = $derived<ApprovalStatus>(approval.state.status);
	const lastApprovedAt = $derived(approval.state.last_approved_at);
</script>

{#if status !== "loading"}
	<div
		class="sab-root"
		class:sab-root--approved={status === "approved"}
		class:sab-root--warn={status === "pending_approval" || status === "never_proposed"}
		class:sab-root--error={status === "error"}
	>
		<div class="sab-body">
			{#if status === "approved"}
				<span class="sab-badge sab-badge--success">APPROVED</span>
				<span class="sab-text">
					Strategic allocation approved
					{#if lastApprovedAt}
						on {formatDateTime(lastApprovedAt)}
					{/if}
				</span>
				{#if onNavigate}
					<button
						type="button"
						class="sab-action"
						onclick={() => onNavigate?.("portfolio")}
					>
						Continue to Portfolio ▸
					</button>
				{/if}
			{:else if status === "pending_approval"}
				<span class="sab-badge sab-badge--warn">PENDING</span>
				<span class="sab-text">
					Strategic allocation proposed but not yet approved.
					Approve before building a portfolio.
				</span>
			{:else if status === "never_proposed"}
				<span class="sab-badge sab-badge--warn">NOT PROPOSED</span>
				<span class="sab-text">
					Start by proposing a strategic allocation for this profile.
				</span>
			{:else if status === "error"}
				<span class="sab-badge sab-badge--error">ERROR</span>
				<span class="sab-text">
					Could not load approval status
					{#if approval.state.error}
						— {approval.state.error}
					{/if}
				</span>
			{/if}
		</div>
	</div>
{/if}

<style>
	.sab-root {
		display: flex;
		align-items: center;
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border: 1px solid var(--terminal-fg-muted);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-11);
	}

	.sab-root--approved {
		border-color: var(--terminal-status-success);
		background: color-mix(in srgb, var(--terminal-status-success) 8%, transparent);
	}

	.sab-root--warn {
		border-color: var(--terminal-accent-amber);
		background: color-mix(in srgb, var(--terminal-accent-amber) 8%, transparent);
	}

	.sab-root--error {
		border-color: var(--terminal-status-error);
		background: color-mix(in srgb, var(--terminal-status-error) 8%, transparent);
	}

	.sab-body {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		flex-wrap: wrap;
	}

	.sab-badge {
		display: inline-flex;
		align-items: center;
		height: 20px;
		padding: 0 var(--terminal-space-2);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		border: 1px solid;
	}

	.sab-badge--success {
		border-color: var(--terminal-status-success);
		color: var(--terminal-status-success);
	}

	.sab-badge--warn {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.sab-badge--error {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	.sab-text {
		color: var(--terminal-fg-secondary);
	}

	.sab-action {
		margin-left: auto;
		padding: var(--terminal-space-1) var(--terminal-space-3);
		background: transparent;
		border: 1px solid var(--terminal-status-success);
		color: var(--terminal-status-success);
		font-family: var(--terminal-font-mono);
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		cursor: pointer;
		transition: background var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}

	.sab-action:hover {
		background: color-mix(in srgb, var(--terminal-status-success) 12%, transparent);
	}

	.sab-action:focus-visible {
		outline: var(--terminal-border-focus);
		outline-offset: 2px;
	}
</style>
