<!--
  LibraryBundleWizard — modal dialog driving the Committee Pack
  bundle worker.

  Phase 6 of the Library frontend (spec §3.4 Fase 6 + §4.4). The
  wizard reads `bundle.state` from a `BundleBuilder` instance and
  surfaces three steps:

    1. Idle      — review the selected document count, confirm
    2. In flight — generating / uploading progress label
    3. Completed — Download ZIP button + missing-entries warning

  The dialog is dismissable while idle or after completion; once
  the worker is dispatched the user can still close the dialog —
  the SSE stream keeps running in the background until completion
  or error, since `bundle.dispose()` only fires on shell unmount.
-->
<script lang="ts">
	import Download from "lucide-svelte/icons/download";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import Package from "lucide-svelte/icons/package";
	import X from "lucide-svelte/icons/x";
	import { formatNumber } from "@investintell/ui";
	import {
		bundleDownloadUrl,
		type BundleBuilder,
	} from "../../state/library/bundle-builder.svelte";

	interface Props {
		bundle: BundleBuilder;
		open: boolean;
		onClose: () => void;
	}

	let { bundle, open, onClose }: Props = $props();

	const status = $derived(bundle.state.status);
	const inFlight = $derived(
		status === "dispatching" ||
			status === "generating" ||
			status === "uploading",
	);
	const downloadHref = $derived(
		bundle.state.bundleId ? bundleDownloadUrl(bundle.state.bundleId) : null,
	);

	function handleConfirm(): void {
		void bundle.createBundle();
	}

	function handleClose(): void {
		if (status === "completed" || status === "error") {
			bundle.reset();
			bundle.clearSelection();
		}
		onClose();
	}
</script>

{#if open}
	<div
		class="overlay"
		role="dialog"
		aria-modal="true"
		aria-label="Create Committee Pack"
	>
		<div class="dialog">
			<header class="dialog__header">
				<span class="dialog__icon">
					<Package size={16} />
				</span>
				<h2 class="dialog__title">Create Committee Pack</h2>
				<button
					type="button"
					class="dialog__close"
					onclick={handleClose}
					aria-label="Close wizard"
				>
					<X size={14} />
				</button>
			</header>

			<div class="dialog__body">
				{#if status === "idle"}
					<p class="dialog__sub">
						Bundle the selected documents into a ZIP archive that
						the worker uploads to storage. The pack includes a
						manifest describing every entry. The build runs in the
						background — you can keep working while it finishes.
					</p>
					<div class="dialog__stat">
						<span class="dialog__stat-num">
							{bundle.state.selected.size}
						</span>
						<span class="dialog__stat-label">documents selected</span>
					</div>
				{:else if inFlight}
					<div class="dialog__progress">
						<Loader2 size={18} class="spin" />
						<span>{bundle.state.progressLabel || "Preparing..."}</span>
					</div>
					{#if bundle.state.sizeBytes}
						<p class="dialog__sub">
							Bundle size:
							{formatNumber(bundle.state.sizeBytes / 1024 / 1024, 2)} MB
						</p>
					{/if}
				{:else if status === "completed"}
					<p class="dialog__sub">Your Committee Pack is ready.</p>
					{#if bundle.state.fetched != null}
						<p class="dialog__sub">
							{bundle.state.fetched} document{bundle.state.fetched === 1 ? "" : "s"} packed.
							{#if bundle.state.missing}
								{bundle.state.missing} missing.
							{/if}
						</p>
					{/if}
				{:else if status === "error"}
					<p class="dialog__error">{bundle.state.error}</p>
				{/if}
			</div>

			<footer class="dialog__footer">
				{#if status === "idle"}
					<button
						type="button"
						class="dialog__btn dialog__btn--secondary"
						onclick={handleClose}
					>
						Cancel
					</button>
					<button
						type="button"
						class="dialog__btn dialog__btn--primary"
						disabled={bundle.state.selected.size === 0}
						onclick={handleConfirm}
					>
						Build Pack
					</button>
				{:else if inFlight}
					<button
						type="button"
						class="dialog__btn dialog__btn--secondary"
						onclick={onClose}
					>
						Hide
					</button>
				{:else if status === "completed" && downloadHref}
					<button
						type="button"
						class="dialog__btn dialog__btn--secondary"
						onclick={handleClose}
					>
						Done
					</button>
					<a
						href={downloadHref}
						class="dialog__btn dialog__btn--primary"
						download
					>
						<Download size={14} />
						Download ZIP
					</a>
				{:else}
					<button
						type="button"
						class="dialog__btn dialog__btn--secondary"
						onclick={handleClose}
					>
						Close
					</button>
				{/if}
			</footer>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 9000;
		font-family: var(--ii-font-sans, "Urbanist", system-ui, sans-serif);
	}

	.dialog {
		width: min(480px, calc(100vw - 48px));
		background: #141519;
		border: 1px solid #404249;
		border-radius: 12px;
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
		color: #cbccd1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.dialog__header {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px;
		border-bottom: 1px solid #404249;
	}

	.dialog__icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		background: color-mix(in srgb, #0177fb 22%, #141519);
		border-radius: 8px;
		color: #ffffff;
	}

	.dialog__title {
		flex: 1;
		font-size: 15px;
		font-weight: 700;
		color: #ffffff;
		margin: 0;
	}

	.dialog__close {
		background: transparent;
		border: none;
		color: #85a0bd;
		cursor: pointer;
		padding: 4px;
		border-radius: 6px;
	}

	.dialog__close:hover { color: #ffffff; background: #1d1f25; }

	.dialog__body {
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.dialog__sub {
		font-size: 13px;
		color: #85a0bd;
		margin: 0;
		line-height: 1.5;
	}

	.dialog__stat {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 18px;
		background: #1d1f25;
		border: 1px solid #404249;
		border-radius: 10px;
	}

	.dialog__stat-num {
		font-size: 32px;
		font-weight: 800;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
	}

	.dialog__stat-label {
		font-size: 12px;
		color: #85a0bd;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.dialog__progress {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 13px;
		color: #ffffff;
	}

	:global(.spin) {
		animation: spin 1s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }

	.dialog__error {
		font-size: 13px;
		color: #ff6b6b;
		margin: 0;
	}

	.dialog__footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		padding: 14px 20px;
		border-top: 1px solid #404249;
	}

	.dialog__btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 14px;
		border: 1px solid #404249;
		background: #1d1f25;
		color: #cbccd1;
		font-family: inherit;
		font-size: 13px;
		font-weight: 600;
		border-radius: 8px;
		cursor: pointer;
		text-decoration: none;
	}

	.dialog__btn:hover {
		color: #ffffff;
		border-color: #85a0bd;
	}

	.dialog__btn--primary {
		background: #0177fb;
		border-color: #0177fb;
		color: #ffffff;
	}

	.dialog__btn--primary:hover {
		background: color-mix(in srgb, #0177fb 80%, #ffffff);
	}

	.dialog__btn--primary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
