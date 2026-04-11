<!--
  Screener — Terminal OS high-density asset screening surface.

  Owns the War Room modal state: clicking a fund row inside the
  TerminalDataGrid invokes FundWarRoomModal with the fund's
  external_id. ESC or backdrop click dismisses the modal and
  clears the active id, returning focus to the screener grid.
-->
<script lang="ts">
	import TerminalScreenerShell from "$lib/components/screener/terminal/TerminalScreenerShell.svelte";
	import FundWarRoomModal from "$lib/components/terminal/FundWarRoomModal.svelte";

	let activeFundId = $state<string | null>(null);

	function openWarRoom(fundId: string) {
		activeFundId = fundId;
	}

	function closeWarRoom() {
		activeFundId = null;
	}
</script>

<TerminalScreenerShell onOpenWarRoom={openWarRoom} />

{#if activeFundId}
	<FundWarRoomModal id={activeFundId} onClose={closeWarRoom} />
{/if}
