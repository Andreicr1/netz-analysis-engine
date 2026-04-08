<!--
  BuilderActionBar — Phase 5 Task 5.2 of the portfolio-enterprise-workbench
  plan. Replaces the hardcoded 3-button row in BuilderColumn with a
  fully data-driven action bar that renders one button per entry in
  ``portfolio.allowed_actions`` (DL3).

  Per CLAUDE.md DL3 — zero ``if state === ...`` conditionals. The
  backend's ``compute_allowed_actions`` is the single source of truth
  for which actions are visible.

  Per Phase 5 Task 5.2 Step 4 — destructive / irreversible actions
  open a TransitionConfirmDialog that requires a reason for the audit
  trail. The PortfolioStateChip is always visible so the PM has
  immediate situational awareness regardless of which actions appear.

  Construction (``construct``) is a special case: it does not POST
  to the transition dispatcher. The action bar invokes the parent's
  ``onConstruct`` callback which fires ``workspace.runConstructJob()``
  via the existing Phase 4 SSE flow. Every other action goes through
  ``workspace.applyTransition`` (Phase 5 backend dispatcher).
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { Button } from "@investintell/ui";
	import {
		ACTION_MAP,
		sortActions,
		type ActionDescriptor,
	} from "$lib/portfolio/action-map";
	import type { PortfolioAction } from "$lib/types/model-portfolio";
	import PortfolioStateChip from "./PortfolioStateChip.svelte";
	import TransitionConfirmDialog from "./TransitionConfirmDialog.svelte";

	import Play from "lucide-svelte/icons/play";
	import ShieldCheck from "lucide-svelte/icons/shield-check";
	import CheckCircle from "lucide-svelte/icons/check-circle";
	import Rocket from "lucide-svelte/icons/rocket";
	import Pause from "lucide-svelte/icons/pause";
	import PlayCircle from "lucide-svelte/icons/play-circle";
	import Archive from "lucide-svelte/icons/archive";
	import XCircle from "lucide-svelte/icons/x-circle";
	import RotateCcw from "lucide-svelte/icons/rotate-ccw";
	import Loader2 from "lucide-svelte/icons/loader-2";

	interface Props {
		/**
		 * Construction handler — Phase 4 Task 4.5 already wires this to
		 * ``workspace.runConstructJob()``. The action bar fires it when
		 * the user presses the ``construct`` button instead of POSTing
		 * to the transition dispatcher (construct has its own
		 * Job-or-Stream route per DL18 P2).
		 */
		onConstruct: () => void;
	}

	let { onConstruct }: Props = $props();

	const portfolio = $derived(workspace.portfolio);
	const actions = $derived.by(() => {
		const list = portfolio?.allowed_actions ?? [];
		return sortActions(list);
	});

	let confirmOpen = $state(false);
	let pendingAction = $state<ActionDescriptor | null>(null);
	let inFlightAction = $state<PortfolioAction | null>(null);

	function handleClick(descriptor: ActionDescriptor) {
		if (!portfolio || inFlightAction !== null) return;

		// Construct is the only action that does NOT go through the
		// transition dispatcher — it has its own Job-or-Stream route.
		if (descriptor.action === "construct") {
			onConstruct();
			return;
		}

		if (descriptor.confirm) {
			pendingAction = descriptor;
			confirmOpen = true;
			return;
		}

		void dispatchTransition(descriptor.action, "");
	}

	async function dispatchTransition(action: PortfolioAction, reason: string) {
		inFlightAction = action;
		try {
			await workspace.applyTransition(action, { reason });
		} finally {
			inFlightAction = null;
		}
	}

	async function handleConfirmDispatch(reason: string) {
		if (!pendingAction) return;
		await dispatchTransition(pendingAction.action, reason);
	}

	function handleConfirmOpenChange(value: boolean) {
		confirmOpen = value;
		if (!value) pendingAction = null;
	}

	const ICONS = {
		play: Play,
		"shield-check": ShieldCheck,
		"check-circle": CheckCircle,
		rocket: Rocket,
		pause: Pause,
		"play-circle": PlayCircle,
		archive: Archive,
		"x-circle": XCircle,
		"rotate-ccw": RotateCcw,
	} as const;

	function buttonVariant(variant: ActionDescriptor["variant"]): "default" | "outline" | "destructive" | "ghost" {
		switch (variant) {
			case "primary":
			case "success":
				return "default";
			case "danger":
				return "destructive";
			case "warning":
			case "secondary":
			default:
				return "outline";
		}
	}

	const confirmDialogVariant = $derived<"default" | "destructive">(
		pendingAction?.variant === "danger" ? "destructive" : "default",
	);
</script>

<div class="bab-root">
	{#if portfolio}
		<PortfolioStateChip
			state={portfolio.state}
			stateMetadata={portfolio.state_metadata}
		/>
	{/if}

	<div class="bab-actions">
		{#each actions as action (action)}
			{@const descriptor = ACTION_MAP[action]}
			{@const Icon = ICONS[descriptor.icon]}
			{@const isInFlight = inFlightAction === action}
			<Button
				variant={buttonVariant(descriptor.variant)}
				size="sm"
				disabled={!portfolio || inFlightAction !== null}
				onclick={() => handleClick(descriptor)}
				title={descriptor.description}
			>
				{#if isInFlight}
					<Loader2 size={14} class="bab-spinner" />
				{:else}
					<Icon size={14} />
				{/if}
				<span>{descriptor.label}</span>
			</Button>
		{/each}
	</div>
</div>

{#if pendingAction}
	<TransitionConfirmDialog
		open={confirmOpen}
		onOpenChange={handleConfirmOpenChange}
		title={`${pendingAction.label}?`}
		message={pendingAction.description}
		confirmLabel={pendingAction.label}
		confirmVariant={confirmDialogVariant}
		reasonRequired={pendingAction.reasonRequired}
		onConfirm={handleConfirmDispatch}
	/>
{/if}

<style>
	.bab-root {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		font-family: "Urbanist", system-ui, sans-serif;
	}

	.bab-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	:global(.bab-spinner) {
		animation: bab-spin 1s linear infinite;
	}

	@keyframes bab-spin {
		to { transform: rotate(360deg); }
	}
</style>
