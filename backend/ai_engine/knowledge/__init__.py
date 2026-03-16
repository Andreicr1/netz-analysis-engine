"""AI Engine Knowledge — knowledge graph construction and entity linking.

Modules:
    knowledge_builder         — builds ManagerProfile entities from document corpus
    knowledge_anchor_extractor — extracts knowledge anchors from classified documents
    linker                    — links knowledge entities across documents

Tech debt: All 3 modules use sqlalchemy.orm.Session (sync, legacy pattern).
Migrate to session injection in Sprint 3 alongside general ai_engine
async migration. See CLAUDE.md: "async migration safety net" section.
"""
