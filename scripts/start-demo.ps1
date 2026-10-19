# Starts the mock CloudLink receiver, the firewall backend and the Angular dev server,
# each in its own PowerShell window. Run from the repository root after completing setup:
#   powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Error "Backend virtual environment not found. Follow the setup steps in README.md first."
    exit 1
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Error "Frontend dependencies not installed. Run 'npm install --legacy-peer-deps' in frontend first."
    exit 1
}

Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$python' -m uvicorn app.integrations.mock_cloudlink:app --host 127.0.0.1 --port 8100"
Start-Process powershell -WorkingDirectory $backend -ArgumentList '-NoExit', '-Command', "& '$python' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Process powershell -WorkingDirectory $frontend -ArgumentList '-NoExit', '-Command', 'npx ng serve --port 4200'

Write-Host 'Starting services:'
Write-Host '  Mock CloudLink  http://localhost:8100/health'
Write-Host '  Firewall API    http://localhost:8000/api/health  (docs: http://localhost:8000/docs)'
Write-Host '  Angular UI      http://localhost:4200'
