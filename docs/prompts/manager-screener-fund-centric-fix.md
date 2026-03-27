# Manager Screener — Fund-Centric Add-to-Universe Fix

## Problema

`POST /manager-screener/managers/{crd}/add-to-universe` adiciona a **firma RIA**
como instrumento, com o CIK da firma em `attributes["sec_cik"]`. Isso é firm-centric:
o CIK da firma aponta para 13F (holdings agregadas), não para N-PORT (fundo específico).

Quando este instrumento entra no DD Report, `sec_injection.py` usa o CIK errado.

## Solução

1. **Novo endpoint:** `GET /manager-screener/managers/{crd}/registered-funds`
   Lista os fundos registrados da firma via `sec_registered_funds` para o usuário escolher.

2. **Endpoint modificado:** `POST /manager-screener/managers/{crd}/add-to-universe`
   Passa a exigir `fund_cik` no body. Adiciona o **fundo específico** com o CIK correto.

---

## Leitura obrigatória antes de qualquer edição

```
backend/app/shared/models.py              (SecRegisteredFund — campos e FK)
backend/app/domains/wealth/routes/manager_screener.py   (endpoint atual completo)
backend/app/domains/wealth/schemas/manager_screener.py  (schemas existentes)
backend/app/domains/wealth/models/instrument.py         (campos e attributes JSONB)
backend/app/domains/wealth/routes/screener.py           (import_sec_security — padrão de attributes)
```

Verificar em `screener.py` o endpoint `POST /screener/import-sec/{ticker}`:
ele já faz a resolução correta CIK + `sec_universe="registered_us"` — usar como referência
de como popular `attributes` do instrumento.

---

## Etapa 1 — Novo schema `ManagerRegisteredFundItem`

Em `backend/app/domains/wealth/schemas/manager_screener.py`, adicionar:

```python
class ManagerRegisteredFundItem(BaseModel):
    """Um fundo registrado (N-PORT) da firma gestora."""
    cik: str
    fund_name: str
    fund_type: str
    ticker: str | None = None
    isin: str | None = None
    total_assets: int | None = None          # AUM em USD
    inception_date: date | None = None
    last_nport_date: date | None = None
    aum_below_threshold: bool = False
    already_in_universe: bool = False        # True se já importado pelo tenant
    universe_instrument_id: str | None = None  # UUID se já importado

class ManagerRegisteredFundsResponse(BaseModel):
    crd_number: str
    firm_name: str
    funds: list[ManagerRegisteredFundItem]
    total_funds: int
```

Também modificar `ManagerToUniverseRequest` para exigir `fund_cik`:

```python
class ManagerToUniverseRequest(BaseModel):
    fund_cik: str                  # OBRIGATÓRIO — CIK do fundo específico
    block_id: str | None = None
    asset_class: str = "alternatives"
    geography: str = "north_america"
    currency: str = "USD"
```

---

## Etapa 2 — Novo endpoint `GET /managers/{crd}/registered-funds`

Adicionar em `manager_screener.py`, antes do endpoint `add-to-universe`:

```python
@router.get(
    "/managers/{crd}/registered-funds",
    response_model=ManagerRegisteredFundsResponse,
    summary="List registered funds (N-PORT filers) for a manager",
)
@route_cache(ttl=3600, global_key=True, key_prefix="mgr:reg_funds")
async def get_registered_funds(
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ManagerRegisteredFundsResponse:
    """Lista fundos registrados (sec_registered_funds) vinculados à firma.

    Retorna apenas fundos com N-PORT disponível (last_nport_date IS NOT NULL).
    Para cada fundo, verifica se já foi importado no universo do tenant.
    Ordena por total_assets DESC (maiores primeiro).
    """
    _require_investment_role(actor)
    crd = _validate_crd(crd)
    manager = await _get_manager(db, crd)

    # Buscar fundos registrados da firma (global, sem RLS)
    funds_result = await db.execute(
        select(SecRegisteredFund)
        .where(SecRegisteredFund.crd_number == crd)
        .where(SecRegisteredFund.last_nport_date.isnot(None))  # só com N-PORT
        .order_by(SecRegisteredFund.total_assets.desc().nulls_last())
    )
    funds = funds_result.scalars().all()

    # Verificar quais já estão no universo do tenant (org-scoped)
    fund_ciks = [f.cik for f in funds]
    universe_map: dict[str, str] = {}  # cik → instrument_id
    if fund_ciks:
        existing_result = await db.execute(
            select(
                Instrument.attributes["sec_cik"].astext.label("sec_cik"),
                Instrument.instrument_id.cast(String).label("instrument_id"),
            )
            .where(Instrument.attributes["sec_cik"].astext.in_(fund_ciks))
        )
        for row in existing_result.mappings().all():
            universe_map[row["sec_cik"]] = row["instrument_id"]

    return ManagerRegisteredFundsResponse(
        crd_number=crd,
        firm_name=manager.firm_name,
        funds=[
            ManagerRegisteredFundItem(
                cik=f.cik,
                fund_name=f.fund_name,
                fund_type=f.fund_type,
                ticker=f.ticker,
                isin=f.isin,
                total_assets=f.total_assets,
                inception_date=f.inception_date,
                last_nport_date=f.last_nport_date,
                aum_below_threshold=f.aum_below_threshold,
                already_in_universe=f.cik in universe_map,
                universe_instrument_id=universe_map.get(f.cik),
            )
            for f in funds
        ],
        total_funds=len(funds),
    )
```

**Import necessário:** `SecRegisteredFund` já deve estar disponível via `app.shared.models`.
Verificar se já está importado no topo do arquivo — adicionar se não estiver.

---

## Etapa 3 — Modificar `POST /managers/{crd}/add-to-universe`

Substituir a implementação atual por:

```python
@router.post(
    "/managers/{crd}/add-to-universe",
    response_model=ManagerUniverseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a specific registered fund to instrument universe",
)
async def add_to_universe(
    body: ManagerToUniverseRequest,
    crd: str = Path(...),
    db: AsyncSession = Depends(get_db_with_rls),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ManagerUniverseRead:
    """Adiciona um fundo específico (por fund_cik) ao universo do tenant.

    Fund-centric: requer fund_cik do fundo N-PORT, nunca usa CIK da firma.
    O fund_cik vem de GET /managers/{crd}/registered-funds.

    attributes["sec_cik"] = fund CIK (fundo, não firma) → habilita N-PORT no DD Report.
    attributes["sec_universe"] = "registered_us"
    """
    _require_investment_role(actor)
    crd = _validate_crd(crd)

    # Validar que a firma existe
    manager = await _get_manager(db, crd)

    # Validar que o fundo existe e pertence a esta firma
    fund_result = await db.execute(
        select(SecRegisteredFund)
        .where(SecRegisteredFund.cik == body.fund_cik)
        .where(SecRegisteredFund.crd_number == crd)  # fundo deve ser desta firma
    )
    fund = fund_result.scalar_one_or_none()
    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fund with CIK {body.fund_cik} not found for manager {crd}",
        )

    # Verificar se já foi importado (idempotência)
    existing_result = await db.execute(
        select(Instrument)
        .where(Instrument.attributes["sec_cik"].astext == body.fund_cik)
        .where(Instrument.organization_id == org_id)
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Fund {fund.fund_name} (CIK {body.fund_cik}) already in universe",
        )

    instrument = Instrument(
        organization_id=org_id,
        instrument_type="fund",
        name=fund.fund_name,
        ticker=fund.ticker,
        isin=fund.isin,
        asset_class=body.asset_class,
        geography=body.geography,
        currency=fund.currency or body.currency,
        block_id=body.block_id,
        approval_status="pending",
        attributes={
            "sec_cik": body.fund_cik,          # CIK do FUNDO (N-PORT) — não da firma
            "sec_crd": crd,                    # CRD da firma gestora (contexto)
            "sec_universe": "registered_us",
            "manager_name": manager.firm_name,
            "fund_type": fund.fund_type,
            "source": "manager_screener",
            "aum_usd": fund.total_assets,
            "inception_date": fund.inception_date.isoformat() if fund.inception_date else None,
        },
    )
    db.add(instrument)
    await db.commit()
    await db.refresh(instrument)

    return ManagerUniverseRead(
        instrument_id=instrument.instrument_id,
        approval_status=instrument.approval_status,
        asset_class=instrument.asset_class,
        geography=instrument.geography,
        currency=instrument.currency,
        block_id=instrument.block_id,
        added_at=instrument.created_at,
    )
```

---

## Etapa 4 — Importar `SecRegisteredFund` no manager_screener.py

No topo do arquivo, onde estão os imports de `app.shared.models`, adicionar
`SecRegisteredFund` se não estiver presente:

```python
from app.shared.models import (
    Sec13fDiff,
    Sec13fHolding,
    SecInstitutionalAllocation,
    SecManager,
    SecNportHolding,
    SecRegisteredFund,   # ← adicionar
)
```

Também adicionar `String` aos imports de `sqlalchemy` se não estiver presente
(usado no `.cast(String)` da query `universe_map`).

---

## Definition of Done

- [ ] `ManagerRegisteredFundItem` e `ManagerRegisteredFundsResponse` em schemas
- [ ] `ManagerToUniverseRequest` atualizado com `fund_cik: str` obrigatório
- [ ] `GET /managers/{crd}/registered-funds` implementado — retorna fundos com N-PORT
- [ ] `already_in_universe` e `universe_instrument_id` preenchidos corretamente
- [ ] `POST /managers/{crd}/add-to-universe` usa `fund_cik`, valida que fundo pertence à firma
- [ ] `attributes["sec_cik"]` = CIK do fundo (não da firma)
- [ ] `attributes["sec_crd"]` = CRD da firma (contexto)
- [ ] 409 se fundo já importado, 404 se fundo não pertence à firma
- [ ] `make check` passa

## O que NÃO fazer

- Não adicionar `organization_id` na query de `sec_registered_funds` — tabela global sem RLS
- Não usar `manager.cik` como `sec_cik` do instrumento — CIK da firma leva ao 13F
- Não remover o endpoint atual de brochure/holdings/drift — apenas o add-to-universe muda
- Não quebrar `ManagerUniverseRead` — response mantém o mesmo schema

## Failure modes esperados

- `SecRegisteredFund.crd_number` NULL para fundos sem ADV linkage confirmado:
  a query `WHERE crd_number = crd` retorna vazio — retornar lista vazia com
  mensagem de log `mgr.no_registered_funds` em vez de erro 500
- Instrumento com `attributes["sec_cik"]` já preenchido de outra forma (import
  via `import-sec`): o check de idempotência cobre este caso via `sec_cik`
- `fund.currency` NULL: fallback para `body.currency` (default "USD")
