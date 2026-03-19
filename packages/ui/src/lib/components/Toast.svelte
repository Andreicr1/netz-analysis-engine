<script lang="ts">
	import { cn } from "../utils/cn.js";
	import { onMount } from "svelte";

	type ToastType = "success" | "error" | "warning" | "info";

	interface Props {
		message: string;
		type?: ToastType;
		duration?: number;
		onDismiss?: () => void;
		class?: string;
	}

	let {
		message,
		type = "info",
		duration = 5000,
		onDismiss,
		class: className,
	}: Props = $props();

	let visible = $state(true);

	const styles: Record<ToastType, string> = {
		success:
			"border-[#10B981] bg-[#10B981]/10 text-[#10B981]",
		error:
			"border-(--netz-danger) bg-(--netz-danger)/10 text-(--netz-danger)",
		warning:
			"border-[#F59E0B] bg-[#F59E0B]/10 text-[#92400E]",
		info: "border-(--netz-info) bg-(--netz-info)/10 text-(--netz-info)",
	};

	const icons: Record<ToastType, string> = {
		success: "M20 6 9 17l-5-5",
		error: "M18 6 6 18M6 6l12 12",
		warning: "M12 9v4M12 17h.01",
		info: "M12 16v-4M12 8h.01",
	};

	function dismiss() {
		visible = false;
		onDismiss?.();
	}

	onMount(() => {
		if (duration > 0) {
			const timer = setTimeout(dismiss, duration);
			return () => clearTimeout(timer);
		}
	});
</script>

{#if visible}
	<div
		class={cn(
			"fixed bottom-4 right-4 z-[100] flex w-80 items-start gap-3 rounded-lg border p-4 shadow-lg netz-animate-scale-in",
			styles[type],
			className,
		)}
		role="alert"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="16"
			height="16"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			class="mt-0.5 shrink-0"
		>
			{#if type === "success"}
				<path d="M20 6 9 17l-5-5" />
			{:else if type === "error"}
				<path d="M18 6 6 18" /><path d="m6 6 12 12" />
			{:else if type === "warning"}
				<path d="M12 9v4" /><path d="M12 17h.01" />
			{:else}
				<path d="M12 16v-4" /><path d="M12 8h.01" />
			{/if}
		</svg>
		<p class="flex-1 text-sm font-medium">{message}</p>
		<button
			class="shrink-0 opacity-60 transition-opacity hover:opacity-100"
			onclick={dismiss}
			aria-label="Dismiss"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="14"
				height="14"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
			>
				<path d="M18 6 6 18" /><path d="m6 6 12 12" />
			</svg>
		</button>
	</div>
{/if}
