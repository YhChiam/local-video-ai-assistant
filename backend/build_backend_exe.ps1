$ErrorActionPreference = 'Stop'

$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $backendDir

if (-not (Test-Path '.\venv\Scripts\python.exe')) {
    throw 'Backend virtual environment not found at .\venv\Scripts\python.exe'
}

& .\venv\Scripts\python.exe -m pip install -r requirements.txt
& .\venv\Scripts\python.exe -m PyInstaller --noconfirm --clean server.spec

$expectedExe = Join-Path $backendDir 'dist\server\server.exe'
if (-not (Test-Path $expectedExe)) {
    throw "PyInstaller completed without creating expected executable: $expectedExe"
}

Write-Host ''
Write-Host 'Packaged backend ready at:' $expectedExe