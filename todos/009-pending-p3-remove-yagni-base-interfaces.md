---
status: pending
priority: p3
issue_id: "009"
tags: [code-review, quality, simplicity]
dependencies: []
---

# BaseCritic and BaseExtractor have zero implementations (YAGNI)

## Problem Statement
`base_critic.py` and `base_extractor.py` are abstract interfaces with no implementations anywhere. Neither credit nor wealth implements them. They can be added when actually needed.

Also: `QuantAnalyzer.analyze_fund_manager()` is uncalled speculative code.

## Proposed Solutions
Remove `base_critic.py`, `base_extractor.py`, and `analyze_fund_manager()`. Update `__init__.py` exports and tests. ~160 lines saved.

Consider also making `run_pipeline_analysis` non-abstract with a default "not_applicable" return so wealth doesn't need a stub.

## Acceptance Criteria
- [ ] Removed files have no remaining imports
- [ ] Tests updated
