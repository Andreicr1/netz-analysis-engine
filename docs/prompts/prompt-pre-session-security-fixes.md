# Prompt de Execução — Pré-Sessão: Security Fixes HC-1 a HC-4

**Projeto:** netz-analysis-engine
**Branch:** main
**Executor:** Claude Opus (sessão fresca)
**Revisor:** Andrei
**Critério de saída:** `make check` verde (lint + typecheck + 1405 testes)

---

## Contexto

Este prompt é self-contained. Não é necessário ler documentação adicional — todos os
diffs estão especificados abaixo com o código exato lido do repositório.

Estas mudanças são pré-requisito de segurança para a cobertura do Wealth vertical.
HC-1 é crítico (cross-tenant data leak). HC-2 é defense-in-depth. HC-3 é error
handling. HC-4 é uma linha de linting.

**Regras invariantes do projeto:**
- `async def` + `AsyncSession` em routes. Sync Session apenas dentro de `asyncio.to_thread()`
- `expire_on_commit = False` sempre
- RLS via `SET LOCAL app.current_organization_id` (nunca `SET`)
- Never-raises pattern: vertical engines retornam defaults seguros, nunca propagam exceção
- Import-linter enforced: não importar entre verticais, não importar service em model

---

## Fix 1 — HC-1 (CRITICAL): SET LOCAL ausente no sync path do ManagerSpotlight

**Arquivo:** `backend/app/domains/wealth/routes/content.py`

**Problema:** A função `_sync_generate_content` abre `sync_session_factory()` sem
chamar `SET LOCAL`. O path `manager_spotlight` não tem tenant isolation — query em
`Fund` filtra apenas por `instrument_id`, podendo retornar dados de outro tenant.

O padrão correto já existe em `dd_reports.py` (linha 531):
```python
db.execute(text("SET LOCAL app.current_organization_id = :oid"), {"oid": org_id})
```

**Código atual** (a partir da linha 451):
```python
with sync_session_factory() as db:
    db.expire_on_commit = False

    if content_type == "investment_outlook":
```

**Código correto:**
```python
with sync_session_factory() as db:
    db.expire_on_commit = False
    from sqlalchemy import text
    db.execute(text("SET LOCAL app.current_organization_id = :oid"), {"oid": org_id})

    if content_type == "investment_outlook":
```

**Instrução:** Aplicar `str_replace` neste trecho exato. O import de `text` deve ir
dentro do `with` block (lazy import, consistente com os outros lazy imports da função).

---

## Fix 2 — HC-2 (MEDIUM): Defense-in-depth — organization_id explícito nas queries

Três arquivos com queries que filtram por `instrument_id`/`fund_id` sem `organization_id`
explícito. O RLS do caller protege em produção, mas defense-in-depth requer filtro
explícito para prevenir cross-tenant em callers futuros que passem sessão bare.

`FundRiskMetrics` herda `OrganizationScopedMixin` — tem `organization_id`. `Fund`
também tem `organization_id`.

### 2a — `backend/vertical_engines/wealth/dd_report/quant_injection.py`

**Mudança 1 — assinatura de `gather_quant_metrics` (linha 17):**

Código atual:
```python
def gather_quant_metrics(
    db: Session,
    *,
    instrument_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Código correto:
```python
def gather_quant_metrics(
    db: Session,
    *,
    instrument_id: str,
    organization_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

**Mudança 2 — query dentro de `gather_quant_metrics` (linha ~47):**

Código atual:
```python
        row = (
            db.query(FundRiskMetrics)
            .filter(FundRiskMetrics.instrument_id == instrument_id)
            .order_by(FundRiskMetrics.calc_date.desc())
            .first()
        )
```

Código correto:
```python
        row = (
            db.query(FundRiskMetrics)
            .filter(
                FundRiskMetrics.instrument_id == instrument_id,
                FundRiskMetrics.organization_id == organization_id,
            )
            .order_by(FundRiskMetrics.calc_date.desc())
            .first()
        )
```

**Mudança 3 — assinatura de `gather_risk_metrics` (linha ~88):**

Código atual:
```python
def gather_risk_metrics(
    db: Session,
    *,
    instrument_id: str,
) -> dict[str, Any]:
    profile = gather_quant_metrics(db, instrument_id=instrument_id)
```

Código correto:
```python
def gather_risk_metrics(
    db: Session,
    *,
    instrument_id: str,
    organization_id: str,
) -> dict[str, Any]:
    profile = gather_quant_metrics(db, instrument_id=instrument_id, organization_id=organization_id)
```

### 2b — `backend/vertical_engines/wealth/dd_report/dd_report_engine.py`

**Mudança 1 — assinatura de `_build_evidence` (linha ~278):**

Código atual:
```python
    def _build_evidence(
        self,
        db: Session,
        *,
        fund_id: str,
    ) -> EvidencePack:
        """Gather all evidence for the fund."""
        from app.domains.wealth.models.fund import Fund

        fund = db.query(Fund).filter(Fund.fund_id == fund_id).first()
```

Código correto:
```python
    def _build_evidence(
        self,
        db: Session,
        *,
        fund_id: str,
        organization_id: str,
    ) -> EvidencePack:
        """Gather all evidence for the fund."""
        from app.domains.wealth.models.fund import Fund

        fund = (
            db.query(Fund)
            .filter(Fund.fund_id == fund_id, Fund.organization_id == organization_id)
            .first()
        )
```

**Mudança 2 — calls a `gather_quant_metrics` e `gather_risk_metrics` dentro de
`_build_evidence` (linha ~305):**

Código atual:
```python
        quant_profile = gather_quant_metrics(db, instrument_id=fund_id)
        risk_metrics = gather_risk_metrics(db, instrument_id=fund_id)
```

Código correto:
```python
        quant_profile = gather_quant_metrics(db, instrument_id=fund_id, organization_id=organization_id)
        risk_metrics = gather_risk_metrics(db, instrument_id=fund_id, organization_id=organization_id)
```

**Mudança 3 — call a `_build_evidence` dentro de `generate()` (linha ~137):**

Código atual:
```python
            # 2. Gather evidence
            evidence = self._build_evidence(db, fund_id=instrument_id)
```

Código correto:
```python
            # 2. Gather evidence
            evidence = self._build_evidence(db, fund_id=instrument_id, organization_id=organization_id)
```

### 2c — `backend/vertical_engines/wealth/manager_spotlight.py`

**Mudança 1 — assinatura de `_gather_fund_data` (linha ~125):**

Código atual:
```python
    def _gather_fund_data(self, db: Session, instrument_id: str) -> dict[str, Any]:
        """Gather fund identity and DD report data."""
        from app.domains.wealth.models.fund import Fund

        fund = db.query(Fund).filter(Fund.fund_id == instrument_id).first()
```

Código correto:
```python
    def _gather_fund_data(self, db: Session, instrument_id: str, organization_id: str) -> dict[str, Any]:
        """Gather fund identity and DD report data."""
        from app.domains.wealth.models.fund import Fund

        fund = (
            db.query(Fund)
            .filter(Fund.fund_id == instrument_id, Fund.organization_id == organization_id)
            .first()
        )
```

**Mudança 2 — calls dentro de `generate()` (linha ~83):**

Código atual:
```python
            fund_data = self._gather_fund_data(db, instrument_id)
            quant_profile = gather_quant_metrics(db, instrument_id=instrument_id)
            risk_metrics = gather_risk_metrics(db, instrument_id=instrument_id)
```

Código correto:
```python
            fund_data = self._gather_fund_data(db, instrument_id, organization_id)
            quant_profile = gather_quant_metrics(db, instrument_id=instrument_id, organization_id=organization_id)
            risk_metrics = gather_risk_metrics(db, instrument_id=instrument_id, organization_id=organization_id)
```

---

## Fix 3 — HC-3 (MEDIUM): Silent exception swallowing em R2StorageClient

**Arquivo:** `backend/app/services/storage_client.py`

**Problema:** `exists()` retorna `False` para qualquer exceção — auth failures e
erros de rede são silenciados como se o arquivo não existisse. `delete()` faz noop
em qualquer exceção. Ambos usam `# noqa: BLE001` para suprimir o linter.

**Código atual** (linha ~240):
```python
    async def exists(self, path: str) -> bool:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.head_object, Bucket=self._bucket_name, Key=path,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    async def delete(self, path: str) -> None:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.delete_object, Bucket=self._bucket_name, Key=path,
            )
        except Exception:  # noqa: BLE001
            pass
```

**Código correto:**
```python
    async def exists(self, path: str) -> bool:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.head_object, Bucket=self._bucket_name, Key=path,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError) and exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            logger.warning("storage_exists_error", path=path, error=str(exc))
            return False

    async def delete(self, path: str) -> None:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.delete_object, Bucket=self._bucket_name, Key=path,
            )
        except Exception as exc:  # noqa: BLE001
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError) and exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return
            logger.warning("storage_delete_error", path=path, error=str(exc))
```

**Nota:** O `logger` já está disponível no escopo de `R2StorageClient` — verificar
se é `structlog.get_logger()` ou `logging.getLogger()` antes de aplicar (usar o
mesmo padrão do restante do arquivo).

---

## Fix 4 — HC-4 (LOW): f-string em adv_service.py

**Arquivo:** `backend/data_providers/sec/adv_service.py`

**Problema:** Linha ~772 usa f-string para montar path de storage em vez de
`global_reference_path()`.

**Código atual:**
```python
# procurar por: gold/_global/sec_brochures/
# o trecho exato será algo como:
path = f"gold/_global/sec_brochures/{crd_number}.pdf"
```

**Código correto:**
```python
from ai_engine.pipeline.storage_routing import global_reference_path
path = global_reference_path("sec_brochures", f"{crd_number}.pdf")
```

**Instrução:** Ler o arquivo inteiro para localizar o trecho exato antes de aplicar
o str_replace, pois a linha exata pode diferir do estimado.

---

## Ordem de execução

1. Fix 1 (HC-1) — arquivo único, mudança cirúrgica
2. Fix 2a (HC-2 quant_injection) — 3 mudanças no mesmo arquivo
3. Fix 2b (HC-2 dd_report_engine) — 3 mudanças no mesmo arquivo
4. Fix 2c (HC-2 manager_spotlight) — 2 mudanças no mesmo arquivo
5. Fix 3 (HC-3 storage_client) — 2 métodos no mesmo arquivo
6. Fix 4 (HC-4 adv_service) — 1 linha
7. Rodar `make check` — deve passar com 1405 testes

## Critério de saída

- `make check` verde
- Nenhum teste novo necessário (os fixes são defense-in-depth em código sync já coberto
  por `tests/test_dd_report_engine.py`, `tests/test_storage_client.py`,
  `tests/test_phase5_content.py`)
- Se algum teste quebrar por mudança de assinatura, o teste deve ser atualizado para
  passar `organization_id` onde necessário
