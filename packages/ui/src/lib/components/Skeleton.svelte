<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		class?: string;
		width?: string;
		height?: string;
	}

	let { class: className, width, height }: Props = $props();
</script>

<div
	class={cn("animate-pulse rounded-md bg-[var(--netz-border)]", className)}
	style:width={width}
	style:height={height}
></div>
