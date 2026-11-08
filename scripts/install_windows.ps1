# Windows 开发机一键安装（后端 + 前端依赖，不含模型）
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
#
# 模型不装在本地：所有模型通过 HTTP 调用云端，本机只留 Web 栈。

param(
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Venv = Join-Path $Backend ".venv"

function Write-Step($n, $text) { Write-Host "`n[$n/5] $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Write-Warn2($text) { Write-Host "  !   $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "  X   $text" -ForegroundColor Red; exit 1 }

Write-Step 1 "查找 Python 3.10+"
$python = $null
foreach ($candidate in @("py -3.11", "py -3.10", "python")) {
    $parts = $candidate.Split(" ")
    try {
        $ver = & $parts[0] $parts[1..($parts.Length - 1)] -c "import sys;print('.'.join(map(str,sys.version_info[:2])))" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]"3.10") {
            $python = $candidate
            Write-Ok "$candidate -> $ver"
            break
        }
    } catch { }
}
if (-not $python) { Fail "没找到 Python 3.10+，请先安装：https://www.python.org/downloads/" }

Write-Step 2 "创建虚拟环境 backend\.venv"
if (Test-Path $Venv) {
    Write-Ok "已存在"
} else {
    $parts = $python.Split(" ")
    & $parts[0] $parts[1..($parts.Length - 1)] -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "创建虚拟环境失败" }
    Write-Ok "创建完成"
}
$py = Join-Path $Venv "Scripts\python.exe"
$pip = Join-Path $Venv "Scripts\pip.exe"

if (-not $SkipDeps) {
    Write-Step 3 "安装后端依赖（约 2–3 分钟，不含任何模型运行时）"
    & $py -m pip install --quiet --upgrade pip
    & $pip install --quiet -r (Join-Path $Backend "requirements-windows.txt")
    if ($LASTEXITCODE -ne 0) { Fail "依赖安装失败" }
    Write-Ok "依赖就绪"
} else {
    Write-Step 3 "跳过依赖安装"
}

Write-Step 4 "生成 backend\.env"
$envFile = Join-Path $Backend ".env"
if (Test-Path $envFile) {
    Write-Ok "已存在，保留不动"
} else {
    & $py (Join-Path $Root "scripts\gen_env.py") --output $envFile
    Write-Warn2 "请打开 backend\.env，把 MYSQL_PASSWORD 改成你本机 MySQL 的密码"
}

Write-Step 5 "环境自检"
& $py (Join-Path $Root "scripts\check_env.py")

Write-Host @"

下一步：
  1. 安装并启动 MySQL 8.0，创建库：
     CREATE DATABASE campus_assistant DEFAULT CHARSET utf8mb4;
  2. 改 backend\.env 里的 MYSQL_USER / MYSQL_PASSWORD
  3. 建表与演示数据：
     backend\.venv\Scripts\python.exe scripts\migrate.py
     backend\.venv\Scripts\python.exe scripts\seed_demo.py
  4. 启动后端（模型指向云端，见 .env 里的 LLM_BASE_URL 等）：
     backend\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --app-dir backend --port 8080 --reload
"@ -ForegroundColor Gray
