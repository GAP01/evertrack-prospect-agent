# Installation de cloudflared.exe sur Windows.
# A executer depuis PowerShell (droits utilisateur suffisent, pas besoin d'admin).
#
# Usage :
#   powershell -ExecutionPolicy Bypass -File .\install_cloudflared.ps1

$ErrorActionPreference = "Stop"

$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$toolsDir = Join-Path $env:USERPROFILE "bin"
$target = Join-Path $toolsDir "cloudflared.exe"

Write-Host "==> Installation de cloudflared" -ForegroundColor Cyan
Write-Host "    Dossier cible : $toolsDir"

# 1. Creer le dossier des outils personnels si absent.
if (-not (Test-Path $toolsDir)) {
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    Write-Host "    Dossier cree."
} else {
    Write-Host "    Dossier deja present."
}

# 2. Telecharger le binaire.
Write-Host "==> Telechargement depuis $url"
try {
    # TLS 1.2 force pour eviter les soucis sur anciens Windows.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $target -UseBasicParsing
} catch {
    Write-Host "[ERREUR] Telechargement echoue : $_" -ForegroundColor Red
    exit 1
}
Write-Host "    Binaire telecharge : $target"

# 3. Ajouter le dossier au PATH utilisateur si absent.
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($null -eq $userPath) { $userPath = "" }
if ($userPath -split ";" -notcontains $toolsDir) {
    $newPath = if ($userPath) { "$userPath;$toolsDir" } else { $toolsDir }
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "==> PATH utilisateur mis a jour (permanent)." -ForegroundColor Green
} else {
    Write-Host "==> PATH utilisateur deja a jour." -ForegroundColor Green
}

# 4. Rendre cloudflared dispo dans la session PowerShell courante.
if (($env:PATH -split ";") -notcontains $toolsDir) {
    $env:PATH += ";$toolsDir"
}

# 5. Verification.
Write-Host ""
Write-Host "==> Verification :" -ForegroundColor Cyan
try {
    & $target --version
    Write-Host ""
    Write-Host "[OK] Cloudflared est installe et pret a l'emploi." -ForegroundColor Green
    Write-Host "     Tu peux maintenant taper 'cloudflared --version' dans cette session."
    Write-Host "     Pour les nouvelles sessions PowerShell, ca marchera aussi (PATH persiste)."
} catch {
    Write-Host "[ERREUR] cloudflared n'a pas pu etre execute : $_" -ForegroundColor Red
    exit 1
}
