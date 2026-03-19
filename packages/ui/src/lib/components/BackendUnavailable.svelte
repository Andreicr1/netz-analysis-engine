<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		message?: string;
		class?: string;
	}

	let {
		message = "Service temporarily unavailable",
		class: className,
	}: Props = $props();
</script>

<div
	class={cn(
		"flex min-h-screen flex-col items-center justify-center bg-(--netz-brand-primary) p-8 text-center",
		className,
	)}
>
	<!-- Logo placeholder -->
	<div class="mb-8 flex items-center gap-3">
		<div
			class="flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 text-lg font-bold text-white"
		>
			N
		</div>
		<span class="text-2xl font-semibold text-white">Netz</span>
	</div>

	<div class="rounded-lg bg-white/10 p-8 backdrop-blur-sm">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="48"
			height="48"
			viewBox="0 0 24 24"
			fill="none"
			stroke="white"
			stroke-width="1.5"
			class="mx-auto mb-4 opacity-60"
		>
			<path d="M12 9v4" />
			<path d="M12 17h.01" />
			<path
				d="M3.586 16.726A2 2 0 0 0 5.035 20h13.93a2 2 0 0 0 1.449-3.274L13.449 4.449a2 2 0 0 0-2.898 0z"
			/>
		</svg>
		<h1 class="text-xl font-semibold text-white">{message}</h1>
		<p class="mt-2 text-sm text-white/60">
			We are working to restore the service. Please try again shortly.
		</p>
	</div>
</div>
