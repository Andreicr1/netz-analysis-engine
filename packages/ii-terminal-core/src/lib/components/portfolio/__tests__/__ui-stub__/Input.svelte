<!--
  Test-only Input stub. Native `<input>` with two-way bind:value.
-->
<script lang="ts">
	interface Props {
		value?: string;
		type?: string;
		placeholder?: string;
		maxlength?: number;
		disabled?: boolean;
		required?: boolean;
		[key: string]: unknown;
	}

	let {
		value = $bindable(""),
		type = "text",
		placeholder,
		maxlength,
		disabled,
		required,
		...rest
	}: Props = $props();
</script>

<input
	bind:value
	{type}
	{placeholder}
	{maxlength}
	{disabled}
	{required}
	{...rest}
/>
