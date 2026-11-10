# 测试入口（PowerShell）：不需要 ROS/真机
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONPATH = "src"
python -m pytest test/ @args
