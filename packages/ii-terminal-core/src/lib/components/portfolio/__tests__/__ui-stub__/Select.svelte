<!--
  Test-only Select stub. Native `<select>` with two-way bind:value
  so tests can assert against `select.options` and trigger native
  change events.
-->
<script lang="ts">
	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		value?: string;
		options: Option[];
		disabled?: boolean;
		[key: string]: unknown;
	}

	let {
		value = $bindable(""),
		options,
		disabled,
		...rest
	}: Props = $props();
</script>

<select bind:value {disabled} {...rest}>
	{#each options as opt (opt.value)}
		<option value={opt.value}>{opt.label}</option>
	{/each}
</select>
