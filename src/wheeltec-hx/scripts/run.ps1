# wheeltec-hx 运行入口（PowerShell）：PYTHONPATH=src python -m app.main …
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "src"
python -m app.main @args
