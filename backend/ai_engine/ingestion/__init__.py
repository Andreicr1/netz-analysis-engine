"""AI Engine Ingestion — batch orchestration and document discovery.

Modules:
    pipeline_ingest_runner — canonical batch orchestrator
        5-stage lifecycle: scan → discover deals → entity bootstrap
        → bridge registry → deep review. Creates PipelineIngestJob audit trail.
    document_scanner       — blob inventory → DocumentRegistry rows
    registry_bridge        — DocumentRegistry → DealDocument mapping (idempotent)
    monitoring             — daily cycle: classification + obligation extraction + alerts
"""
