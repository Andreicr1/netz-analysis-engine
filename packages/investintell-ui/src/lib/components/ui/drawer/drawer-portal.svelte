<script lang="ts">
	import { Drawer as DrawerPrimitive } from "vaul-svelte";
	import type { Snippet } from "svelte";

	let { ...restProps }: { children?: Snippet } = $props();
</script>

<DrawerPrimitive.Portal {...restProps} />
