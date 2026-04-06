<script lang="ts">
	import { cn } from "$lib/utils.js";
	import { Loader2 as Loader2Icon } from 'lucide-svelte';
	import type { SVGAttributes } from "svelte/elements";

	let {
		class: className,
		role = "status",
		// we add color and stroke for compatibility with different icon libraries props
		color,
		stroke,
		"aria-label": ariaLabel = "Loading",
		...restProps
	}: SVGAttributes<SVGSVGElement> = $props();
</script>

<Loader2Icon {role} color={color === null ? undefined : (color as any)} stroke={stroke === null ? undefined : (stroke as any)} aria-label={ariaLabel} class={cn("size-4 animate-spin", className)} {...(restProps as any)} />
