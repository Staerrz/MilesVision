# Run one observe loop. The click is dry-run.
#   powershell -ExecutionPolicy Bypass -File .\scripts\run-example.ps1 "Read the window title"

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$Instruction = $args -join " "
if (-not $Instruction) {
    $Instruction = "Observe the screen and report visible text."
}

& $Python -m desktop_agent.agents.example_loop $Instruction
exit $LASTEXITCODE
