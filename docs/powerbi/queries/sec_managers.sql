-- SEC_Managers
-- Tabela: gestoras registradas no Form ADV (SEC FOIA)
-- Relaciona com: SEC_Holdings e SEC_Diffs via [cik]
-- Filtro: apenas managers com CIK resolvido e AUM > 0

SELECT
    crd_number,
    cik,
    firm_name,
    registration_status,
    aum_total,
    aum_discretionary,
    aum_non_discretionary,
    total_accounts,
    state,
    country,
    website,
    compliance_disclosures,
    last_adv_filed_at,
    data_fetched_at
FROM public.sec_managers
WHERE cik IS NOT NULL
  AND registration_status = 'ACTIVE'
ORDER BY aum_total DESC NULLS LAST
