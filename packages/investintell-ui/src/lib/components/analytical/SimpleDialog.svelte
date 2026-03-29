<!--
  SimpleDialog — thin wrapper around shadcn Dialog providing the legacy simple API:
  <SimpleDialog bind:open>content</SimpleDialog>
  Used by ConfirmDialog. For new code, prefer the shadcn Dialog compound components directly.
-->
<script lang="ts">
	import * as Dialog from "$lib/components/ui/dialog";
	import type { Snippet } from "svelte";

	let {
		open = $bindable(false),
		children,
	}: {
		open?: boolean;
		children?: Snippet;
	} = $props();
</script>

<Dialog.Root bind:open>
	<Dialog.Content showCloseButton={false} class="max-w-lg sm:max-w-lg">
		{@render children?.()}
	</Dialog.Content>
</Dialog.Root>
