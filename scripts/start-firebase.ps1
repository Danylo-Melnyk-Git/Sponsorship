param([int]$Port = 8177)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$credentialPath = Join-Path $projectDirectory 'secrets/firebase-service-account.json'
if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'Нет локального ключа secrets/firebase-service-account.json' }
$previousCredential = $env:GOOGLE_APPLICATION_CREDENTIALS
try {
    $env:GOOGLE_APPLICATION_CREDENTIALS = $credentialPath
    & (Join-Path $projectDirectory '.venv-server/Scripts/python.exe') (Join-Path $projectDirectory 'sponsor.py') --database firestore://sponsoradar-1580e serve --port $Port
} finally {
    $env:GOOGLE_APPLICATION_CREDENTIALS = $previousCredential
}
