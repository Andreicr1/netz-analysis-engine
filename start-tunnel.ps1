# Netz Backend — Cloudflare Tunnel
# Roda o tunnel nomeado que expoe o backend em:
# https://dbf04994-bc16-47c8-a38d-20f72d1510ab.cfargotunnel.com
#
# Para iniciar automaticamente com o Windows:
#   1. Win+R → shell:startup
#   2. Criar atalho para este arquivo nessa pasta
#
# Ou instalar como servico do Windows (recomendado):
#   D:\Projetos\netz-analysis-engine\cloudflared.exe service install
#   sc start cloudflared

Write-Host "Iniciando Cloudflare Tunnel (netz-backend)..." -ForegroundColor Cyan
Write-Host "URL permanente: https://dbf04994-bc16-47c8-a38d-20f72d1510ab.cfargotunnel.com" -ForegroundColor Green

& "D:\Projetos\netz-analysis-engine\cloudflared.exe" tunnel --config "C:\Users\Andrei\.cloudflared\config.yml" run
