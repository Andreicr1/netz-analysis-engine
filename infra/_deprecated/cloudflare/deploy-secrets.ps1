$ErrorActionPreference = "Stop"
$rootDir = "d:\Projetos\netz-analysis-engine"
Set-Location $rootDir

Write-Host "[1/3] EXTRAINDO CHAVES DO .ENV.PRODUCTION" -ForegroundColor Cyan
$envPath = "$rootDir\.env.production"
if (-not (Test-Path $envPath)) {
    Write-Host "Erro: Arquivo .env.production não encontrado em $envPath" -ForegroundColor Red
    exit 1
}

$envVars = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match "^\s*([^=]+?)\s*=\s*(.*)$" -and -not $_.StartsWith("#")) {
        $key = $Matches[1].Trim()
        $val = $Matches[2].Trim()
        if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
            $val = $val.Substring(1, $val.Length - 2)
        }
        $envVars[$key] = $val
    }
}
Write-Host "=> Extraídas $($envVars.Count) variáveis do cofre." -ForegroundColor Green

$workerSecret = "Gwq3H8bEhDqOCVIks8Xd4dJZugKTrl_KlfX54jYyi7c"

Write-Host "`n[2/3] INJETANDO SECRETS NO CLOUDFLARE (WRANGLER API)" -ForegroundColor Cyan
Write-Host "=> Autenticando Gateway Worker"
Set-Location "$rootDir\infra\cloudflare\gateway"
$workerSecret | npx wrangler secret put WORKER_SECRET

Write-Host "=> Autenticando Cron Worker"
Set-Location "$rootDir\infra\cloudflare\cron"
$workerSecret | npx wrangler secret put WORKER_SECRET

Write-Host "=> Injetando cofre master do Backend e Containers"
Set-Location "$rootDir\infra\cloudflare"
$requiredKeys = @(
    "DATABASE_URL", "REDIS_URL", "OPENAI_API_KEY", "MISTRAL_API_KEY", 
    "CLERK_SECRET_KEY", "CLERK_JWKS_URL", "R2_ACCESS_KEY_ID", 
    "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME", "WORKER_DISPATCH_SECRET", 
    "FRED_API_KEY", "EDGAR_IDENTITY"
)

foreach ($k in $requiredKeys) {
    if ($envVars.ContainsKey($k)) {
        Write-Host " + Empurrando: $k" -ForegroundColor DarkGray
        $envVars[$k] | npx wrangler secret put $k --config wrangler.backend.jsonc
        $envVars[$k] | npx wrangler secret put $k --config wrangler.workers.jsonc
    } else {
        Write-Host " ! [AVISO] Chave $k não encontrada no .env.production, pulando..." -ForegroundColor Yellow
    }
}

Write-Host "`n[3/3] REGISTRANDO CHAVES NO GITHUB ACTIONS" -ForegroundColor Cyan
Set-Location $rootDir
$cfAccount = "a44ddf3ff0612bc0f62d1ee86f465ac9"
gh secret set CF_ACCOUNT_ID --body $cfAccount
Write-Host " + Embutido CF_ACCOUNT_ID" -ForegroundColor DarkGray

if ($envVars.ContainsKey("CF_API_TOKEN")) {
    gh secret set CF_API_TOKEN --body $envVars["CF_API_TOKEN"]
    Write-Host " + Embutido CF_API_TOKEN nativo" -ForegroundColor DarkGray
} else {
    Write-Host " ! [AVISO] CF_API_TOKEN não encontrado no .env. Instale manualmente no painel depois." -ForegroundColor Yellow
}

Write-Host "`n============= OPERAÇÃO TRANSACIONAL COMPLETA ==============" -ForegroundColor Green
