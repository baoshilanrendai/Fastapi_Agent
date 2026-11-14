# ============================================================
# 一键停止：后端 + Worker + Redis
# 用法：在本目录执行 .\stop.ps1
# ============================================================

$ErrorActionPreference = "SilentlyContinue"

# 停止 Worker 与后端（按命令行匹配，避免误杀其他 python）
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "my_workers|my_ai_project.my_port.main" } |
    ForEach-Object {
        Write-Host ("停止进程 {0} : {1}" -f $_.ProcessId, $_.Name)
        Stop-Process -Id $_.ProcessId -Force
    }

# 停止 Redis
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "redis-server" } |
    ForEach-Object {
        Write-Host ("停止 Redis {0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force
    }

Start-Sleep -Seconds 1
Write-Host "已全部停止" -ForegroundColor Green
