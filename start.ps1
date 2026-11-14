# ============================================================
# 一键启动：Redis + 后端(FastAPI) + Worker
# 用法：在本目录右键“使用 PowerShell 运行”，或执行 .\start.ps1
# 说明：每次启动前先杀掉旧的后端/worker 残留进程，确保跑的是最新代码
# ============================================================

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$RedisDir = Join-Path $Root "my_ai_project\Redis-x64-5.0.14.1"
$RedisServer = Join-Path $RedisDir "redis-server.exe"
$RedisConf = Join-Path $RedisDir "redis.windows.conf"
$Port = 8001

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Stop-OldProcesses {
    # 按命令行匹配杀掉旧的后端与 worker，避免改完代码后旧实例残留抢任务
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "my_workers|my_ai_project.my_port.main" } |
        ForEach-Object {
            Write-Host ("  清理旧进程 {0} ({1})" -f $_.ProcessId, $_.Name)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

# 1. Redis（已在运行就保留）
if (Test-Port 6379) {
    Write-Host "[1/3] Redis 6379 已在运行，跳过" -ForegroundColor Green
} else {
    Write-Host "[1/3] 启动 Redis ..." -ForegroundColor Cyan
    Start-Process -FilePath $RedisServer -ArgumentList $RedisConf -WorkingDirectory $RedisDir -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

# 2. 重启后端 FastAPI（先清旧实例，再起新的）
Write-Host "[2/3] 启动 FastAPI 后端 :$Port ..." -ForegroundColor Cyan
Stop-OldProcesses
Start-Sleep -Seconds 1
$uvicornArgs = "-m uvicorn my_ai_project.my_port.main:app --host 127.0.0.1 --port $Port"
Start-Process -FilePath $Python -ArgumentList $uvicornArgs -WorkingDirectory $Root -WindowStyle Minimized
Start-Sleep -Seconds 3

# 3. 重启 Worker（先清旧实例，再起新的）
Write-Host "[3/3] 启动 Worker ..." -ForegroundColor Cyan
Start-Process -FilePath $Python -ArgumentList "-m my_ai_project.my_workers.main" -WorkingDirectory $Root -WindowStyle Minimized
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "全部就绪：" -ForegroundColor Yellow
Write-Host "  前端页面： http://127.0.0.1:$Port"
Write-Host "  接口文档： http://127.0.0.1:$Port/docs"
Write-Host ""
Write-Host "停止服务请运行 .\stop.ps1" -ForegroundColor Gray
