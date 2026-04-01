<!--
  PdfPreview — Inline PDF viewer via browser-native <object> tag.
  Uses blob URL from api.getBlob(); no pdfjs dependency.
  Falls back to download link on unsupported browsers (Safari iOS).
-->
<script lang="ts">
	import { onDestroy } from "svelte";

	interface Props {
		blobUrl: string | null;
		filename?: string;
	}

	let { blobUrl, filename = "document.pdf" }: Props = $props();

	onDestroy(() => {
		if (blobUrl) URL.revokeObjectURL(blobUrl);
	});
</script>

{#if blobUrl}
	<div class="pdf-preview">
		<object data={blobUrl} type="application/pdf" title={filename}>
			<p class="pdf-fallback">
				PDF preview not available in this browser.
				<a href={blobUrl} download={filename}>Download PDF</a>
			</p>
		</object>
	</div>
{/if}

<style>
	.pdf-preview {
		width: 100%;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.pdf-preview object {
		width: 100%;
		height: 80vh;
		min-height: 600px;
	}

	.pdf-fallback {
		padding: var(--ii-space-stack-lg, 24px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.pdf-fallback a {
		color: var(--ii-brand-primary);
		text-decoration: underline;
	}
</style>
