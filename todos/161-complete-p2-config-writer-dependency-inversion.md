---
status: pending
priority: p2
issue_id: "161"
tags: [code-review, architecture, admin]
---

# ConfigWriter dependency inversion — core imports from domain

## Problem Statement
`app.core.config.config_writer` imports from `app.domains.admin.models` (AdminAuditLog) and `app.domains.admin.validators`. Core modules should not depend on domain modules.

## Proposed Solution
Move ConfigWriter to `app/domains/admin/services/config_writer.py` since it is exclusively used by admin routes.
