---
id: 176
status: pending
priority: p3
tags: [code-review, performance, admin]
created: 2026-03-17
---

# Branding Upload Blob URL Not Cleaned Up on Component Destroy

## Problem Statement

The branding page creates object URLs for image previews via `URL.createObjectURL()` but only revokes them on successful upload, not when the user navigates away from the page. This leaks browser memory.

## Findings

- **File:** `frontends/admin/src/routes/(admin)/tenants/[orgId]/branding/+page.svelte` line 57
- `URL.createObjectURL(file)` is called when the user selects a logo/image file for preview
- The blob URL is revoked only inside the successful upload handler
- If the user selects a file, previews it, then navigates away without uploading, the blob URL is never revoked
- Each leaked blob URL holds a reference to the entire file in memory until the page is fully unloaded
- Repeated file selections without upload compound the leak

## Proposed Solution

1. Track the current preview blob URL in a variable
2. Revoke the previous blob URL before creating a new one (handles repeated file selections)
3. Add an `onDestroy` lifecycle hook (or Svelte 5 `$effect` teardown) that revokes any outstanding blob URL on navigation

```
onDestroy(() => {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
});
```

## Acceptance Criteria

- [ ] Blob URLs are revoked when the component is destroyed (navigation away)
- [ ] Blob URLs are revoked when a new file is selected (replacing previous preview)
- [ ] Image preview still works correctly during the upload flow
