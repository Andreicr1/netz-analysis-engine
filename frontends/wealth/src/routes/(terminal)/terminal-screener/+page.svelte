<!--
  Screener — Terminal OS high-density asset screening surface.

  Row clicks dispatch a "focustrigger" CustomEvent (via the use:focusTrigger
  action on each <tr>). This page listens for the bubbled event and mounts
  FundFocusMode with the fund's identity. ESC or backdrop click dismisses
  FocusMode and clears the active entity.
-->
<script lang="ts">
	import TerminalScreenerShell from "$lib/components/screener/terminal/TerminalScreenerShell.svelte";
	import FundFocusMode from "$lib/components/terminal/focus-mode/fund/FundFocusMode.svelte";
	import type { FocusTriggerOptions } from "$lib/components/terminal/focus-mode/focus-trigger";

	let focusEntity = $state<FocusTriggerOptions | null>(null);
	let containerEl: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (!containerEl) return;
		const handler = (event: Event) => {
			const detail = (event as CustomEvent<FocusTriggerOptions>).detail;
			focusEntity = detail;
		};
		containerEl.addEventListener("focustrigger", handler);
		return () => containerEl?.removeEventListener("focustrigger", handler);
	});

	function closeFocusMode() {
		focusEntity = null;
	}
</script>

<div bind:this={containerEl}>
	<TerminalScreenerShell />
</div>

{#if focusEntity}
	<FundFocusMode
		fundId={focusEntity.entityId}
		fundLabel={focusEntity.entityLabel ?? ""}
		onClose={closeFocusMode}
	/>
{/if}
