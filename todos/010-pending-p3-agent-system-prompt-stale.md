---
status: pending
priority: p3
issue_id: "010"
tags: [code-review, architecture, agent-native]
dependencies: []
---

# Global agent system prompt references removed modules and misses new capabilities

## Problem Statement
The global agent's `GLOBAL_SYSTEM_PROMPT` references "Counterparty Registry" and "Advisor Portal" which were removed per CLAUDE.md. It mentions nothing about Sprint 4 capabilities (upload-url, SSE, ProfileLoader, knowledge aggregation). The `build_agent_runtime_context()` function returns an empty dict.

## Findings
- **Agent-native reviewer:** CRITICAL — 0 of 10 new capabilities in system prompt, context function is a stub

## Proposed Solutions
1. Strip stale module references from prompt
2. Add Sprint 4 capability descriptions
3. Implement `build_agent_runtime_context()` to inject dynamic state

**Note:** This is important for agent-native parity but not a merge blocker — it's pre-existing tech debt amplified by new features.

## Acceptance Criteria
- [ ] No references to removed operational modules in system prompt
- [ ] New capabilities documented in agent prompt
- [ ] `build_agent_runtime_context()` returns meaningful data
