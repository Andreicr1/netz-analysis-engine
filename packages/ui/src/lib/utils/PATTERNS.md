# Frontend Mutation Playbook

Standard patterns for all endpoint implementations across Netz frontends.

## Mutation Patterns

| Pattern | Default | When to use |
|---|---|---|
| **Pessimistic save** | YES | All mutations — wait for server response before UI update |
| **Optimistic update** | NO | Only checklist toggles — must handle rollback |
| **422 error mapping** | YES | Map Pydantic `detail[].loc[-1]` to field names for inline errors |
| **Form reset** | After success | Call `resetForm()` for edit-in-place; `goto()` for create |
| **Touched tracking** | YES | Show validation errors only after field blur, not on mount |
| **`$derived` aggregate** | YES | `canSubmit = $derived(allFilled && !hasErrors && !saving)` |
| **Blob download** | `getBlob()` + createObjectURL | All PDF downloads — revoke URL after click |
| **File upload** | `upload()` + FormData | All file inputs — validate magic bytes client-side |
| **Polling** | `createPoller` | Only when SSE not available — max 5 min duration |
| **SSE** | `createSSEStream` | Preferred for all real-time status — use registry |

## Standard Save Pattern (Svelte 5)

```typescript
const api = createClientApiClient(getToken);
let saving = $state(false);
let error = $state<string | null>(null);

async function save() {
  saving = true;
  error = null;
  try {
    await api.put("/endpoint", formData, { "If-Match": String(version) });
    // Reload or navigate on success
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed";
  } finally {
    saving = false;
  }
}
```

## 422 Error Mapping

```typescript
import { ValidationError } from "@netz/ui";

function mapValidationErrors(e: unknown): Record<string, string> {
  if (e instanceof ValidationError && Array.isArray(e.details)) {
    const errors: Record<string, string> = {};
    for (const d of e.details as { loc: string[]; msg: string }[]) {
      const field = d.loc[d.loc.length - 1];
      errors[field] = d.msg;
    }
    return errors;
  }
  return {};
}
```

## Blob Download

```typescript
async function downloadPdf(path: string, filename: string) {
  const blob = await api.getBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

## File Upload with Magic Byte Validation

```typescript
const MAGIC_BYTES: Record<string, number[]> = {
  "image/png": [0x89, 0x50, 0x4e, 0x47],
  "image/jpeg": [0xff, 0xd8, 0xff],
  "image/x-icon": [0x00, 0x00, 0x01, 0x00],
  "application/pdf": [0x25, 0x50, 0x44, 0x46],
};

async function validateMagicBytes(file: File, allowedTypes: string[]): Promise<boolean> {
  const buf = await file.slice(0, 4).arrayBuffer();
  const bytes = new Uint8Array(buf);
  return allowedTypes.some((type) => {
    const magic = MAGIC_BYTES[type];
    return magic?.every((b, i) => bytes[i] === b) ?? false;
  });
}
```

## Touched Field Tracking

```typescript
let touched = $state<Record<string, boolean>>({});
let errors = $derived(validate(form));
let visibleErrors = $derived(
  Object.fromEntries(
    Object.entries(errors).filter(([k]) => touched[k])
  )
);

function onBlur(field: string) {
  touched[field] = true;
}
```
