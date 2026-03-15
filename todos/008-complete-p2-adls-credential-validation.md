---
status: pending
priority: p2
issue_id: "008"
tags: [code-review, security]
dependencies: []
---

# validate_production_secrets() does not check ADLS credentials

## Problem Statement
When `feature_adls_enabled=true`, production validation doesn't verify that `adls_account_name` or credentials are set. A production deployment could start with ADLS enabled but missing credentials, causing runtime failures.

## Proposed Solutions
Extend `validate_production_secrets()`:
```python
if self.feature_adls_enabled:
    if not self.adls_account_name:
        raise RuntimeError("ADLS_ACCOUNT_NAME required when ADLS enabled")
    if not (self.adls_account_key or self.adls_connection_string):
        raise RuntimeError("ADLS credentials required when ADLS enabled")
```

## Acceptance Criteria
- [ ] Production startup fails fast if ADLS enabled without credentials
