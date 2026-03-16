"""AI Engine Governance — institutional controls for cost, quality, and safety.

Modules:
    policy_loader       — extracts concentration thresholds and governance rules
                           from Azure AI Search indices (fund constitution, risk policy)
    token_budget        — token-usage telemetry per deal for audit and cost visibility
    output_safety       — LLM output sanitization before database persistence
    prompt_safety       — input sanitization for user-supplied text before LLM calls
    artifact_cache      — prevents costly re-runs on existing versioned artifacts
    authority_resolver  — resolves governance authority from document classifications
    _constants          — shared injection markers for input/output safety modules
"""
