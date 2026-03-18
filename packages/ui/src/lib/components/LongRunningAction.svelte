<script lang="ts">
	import Button from "./Button.svelte";
	import ConfirmDialog from "./ConfirmDialog.svelte";
	import { cn } from "../utils/cn.js";
	import { formatNumber, formatRelativeDate } from "../utils/format.js";
	import type { SSEConnection } from "../utils/sse-client.svelte.js";

	type LongRunningActionState =
		| "idle"
		| "starting"
		| "in-flight"
		| "success"
		| "error"
		| "cancelled";

	type LongRunningActionEvent = {
		state?: LongRunningActionState;
		progress?: number | null;
		stage?: string | null;
		eta?: Date | number | string | null;
		eta_seconds?: number | null;
		detail?: string | null;
		error?: string | null;
		message?: string | null;
	};

	type LongRunningActionStream = Pick<SSEConnection<LongRunningActionEvent>, "events" | "status" | "error">;

	interface Props {
		title: string;
		description?: string;
		stream?: LongRunningActionStream | null;
		startLabel?: string;
		retryLabel?: string;
		cancelLabel?: string;
		idleMessage?: string;
		successMessage?: string;
		class?: string;
		disabled?: boolean;
		onStart?: () => void | Promise<void>;
		onRetry?: () => void | Promise<void>;
		onCancel?: () => void | Promise<void>;
	}

	let {
		title,
		description = "",
		stream = null,
		startLabel = "Start",
		retryLabel = "Retry",
		cancelLabel = "Cancel",
		idleMessage = "This action is ready to start.",
		successMessage = "Completed successfully.",
		class: className,
		disabled = false,
		onStart,
		onRetry,
		onCancel,
	}: Props = $props();

	let pendingState = $state<LongRunningActionState | null>(null);
	let confirmCancellation = $state(false);
	let localFailureDetail = $state<string | null>(null);

	const latestEvent = $derived(stream?.events.at(-1) ?? null);
	const progress = $derived.by(() => {
		const nextProgress = latestEvent?.progress;
		if (typeof nextProgress !== "number" || Number.isNaN(nextProgress)) {
			return 0;
		}

		return Math.max(0, Math.min(100, nextProgress));
	});
	const stageLabel = $derived(latestEvent?.stage?.trim() || null);
	const failureDetail = $derived(
		localFailureDetail || latestEvent?.error || latestEvent?.detail || stream?.error?.message || null,
	);
	const hasStreamActivity = $derived(
		latestEvent !== null ||
			(stream?.status === "connected" &&
				(pendingState === "starting" || pendingState === "in-flight")),
	);
	const etaLabel = $derived.by(() => {
		if (typeof latestEvent?.eta_seconds === "number" && Number.isFinite(latestEvent.eta_seconds)) {
			return formatRelativeDate(Date.now() + latestEvent.eta_seconds * 1000, "en-US");
		}

		if (latestEvent?.eta != null) {
			return formatRelativeDate(latestEvent.eta, "en-US");
		}

		return null;
	});
	const currentState = $derived.by<LongRunningActionState>(() => {
		const eventState = latestEvent?.state;
		if (eventState) {
			return eventState;
		}

		if (stream?.error || localFailureDetail) {
			return "error";
		}

		if (hasStreamActivity) {
			return "in-flight";
		}

		if (pendingState === "starting") {
			return "starting";
		}

		return pendingState ?? "idle";
	});
	const statusTone = $derived.by(() => {
		switch (currentState) {
			case "success":
				return "var(--netz-success)";
			case "error":
				return "var(--netz-danger)";
			case "cancelled":
				return "var(--netz-warning)";
			default:
				return "var(--netz-brand-secondary)";
		}
	});
	const statusMessage = $derived.by(() => {
		switch (currentState) {
			case "starting":
				return "Starting action…";
			case "in-flight":
				return stageLabel ?? "Action in progress";
			case "success":
				return latestEvent?.message || successMessage;
			case "error":
				return latestEvent?.message || "Action failed.";
			case "cancelled":
				return latestEvent?.message || "Action cancelled.";
			default:
				return idleMessage;
		}
	});
	const progressLabel = $derived(
		currentState === "in-flight" || currentState === "starting"
			? `${formatNumber(progress, 0, "en-US")}%`
			: null,
	);

	$effect(() => {
		if (
			currentState === "in-flight" ||
			currentState === "success" ||
			currentState === "error" ||
			currentState === "cancelled"
		) {
			pendingState = null;
		}

		if (currentState === "success" || currentState === "cancelled") {
			localFailureDetail = null;
		}
	});

	async function handleStart() {
		if (!onStart || disabled) return;
		localFailureDetail = null;
		pendingState = "starting";
		try {
			await onStart();
		} catch (error) {
			pendingState = "error";
			localFailureDetail = error instanceof Error ? error.message : "Unable to start action.";
		}
	}

	async function handleRetry() {
		if (!onRetry || disabled) return;
		localFailureDetail = null;
		pendingState = "starting";
		try {
			await onRetry();
		} catch (error) {
			pendingState = "error";
			localFailureDetail = error instanceof Error ? error.message : "Unable to retry action.";
		}
	}

	async function handleCancel() {
		if (!onCancel || disabled) return;
		localFailureDetail = null;
		try {
			await onCancel();
			confirmCancellation = false;
		} catch (error) {
			pendingState = "error";
			localFailureDetail = error instanceof Error ? error.message : "Unable to cancel action.";
		}
	}

	function requestCancellation() {
		if (progress > 50) {
			confirmCancellation = true;
			return;
		}

		void handleCancel();
	}
</script>

<div
	class={cn(
		"rounded-xl border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4 shadow-sm",
		className,
	)}
>
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div class="space-y-1">
			<p class="text-sm font-semibold text-[var(--netz-text-primary)]">{title}</p>
			{#if description}
				<p class="text-sm text-[var(--netz-text-secondary)]">{description}</p>
			{/if}
		</div>

		<div
			class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
			style={`background-color: color-mix(in srgb, ${statusTone} 14%, var(--netz-surface)); color: ${statusTone};`}
		>
			<span class="h-2 w-2 rounded-full" style={`background-color: ${statusTone};`}></span>
			<span>{currentState}</span>
		</div>
	</div>

	<div class="mt-4 space-y-3">
		<div class="space-y-1">
			<p class="text-sm text-[var(--netz-text-primary)]">{statusMessage}</p>
			<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--netz-text-muted)]">
				{#if progressLabel}
					<span>Progress: {progressLabel}</span>
				{/if}
				{#if stageLabel && currentState === "in-flight"}
					<span>Stage: {stageLabel}</span>
				{/if}
				{#if etaLabel && currentState === "in-flight"}
					<span>ETA: {etaLabel}</span>
				{/if}
			</div>
		</div>

		<div class="h-2 overflow-hidden rounded-full bg-[var(--netz-surface-inset)]">
			<div
				class="h-full rounded-full transition-[width] duration-300"
				style={`width: ${currentState === "starting" ? "12%" : `${progress}%`}; background-color: ${statusTone};`}
			></div>
		</div>

		{#if currentState === "error" && failureDetail}
			<div
				class="rounded-lg border px-3 py-2 text-sm"
				style="border-color: var(--netz-danger); background-color: color-mix(in srgb, var(--netz-danger) 10%, var(--netz-surface)); color: var(--netz-text-primary);"
			>
				<p class="font-medium text-[var(--netz-danger)]">Failure detail</p>
				<p class="mt-1 text-[var(--netz-text-secondary)]">{failureDetail}</p>
			</div>
		{/if}
	</div>

	<div class="mt-4 flex flex-wrap gap-2">
		{#if currentState === "idle"}
			<Button onclick={handleStart} disabled={disabled || !onStart}>{startLabel}</Button>
		{:else if currentState === "starting"}
			<Button disabled>Starting…</Button>
		{:else if currentState === "in-flight"}
			<Button variant="outline" onclick={requestCancellation} disabled={disabled || !onCancel}>
				{cancelLabel}
			</Button>
		{:else if currentState === "error"}
			<Button onclick={handleRetry} disabled={disabled || !onRetry}>{retryLabel}</Button>
		{:else if currentState === "cancelled"}
			<Button onclick={handleRetry} disabled={disabled || !onRetry}>{retryLabel}</Button>
		{/if}
	</div>
</div>

<ConfirmDialog
	bind:open={confirmCancellation}
	title="Cancel running action?"
	message="This job is already more than halfway complete. Confirm cancellation to stop it."
	confirmLabel={cancelLabel}
	confirmVariant="destructive"
	onConfirm={handleCancel}
/>
