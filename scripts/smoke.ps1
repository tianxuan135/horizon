# Horizon 端到端冒烟测试（只读 + 可选写操作）
# 用法：
#   pwsh -File scripts/smoke.ps1                      # 默认 http://127.0.0.1:8000
#   pwsh -File scripts/smoke.ps1 -Base http://127.0.0.1:8010
# 说明：本脚本只调用项目自身的 BFF/API，不访问任何第三方付费接口，可安全用于 CI。
param(
  [string]$Base = "http://127.0.0.1:8000",
  [switch]$WriteTests
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$script:pass = 0
$script:fail = 0

function Hit {
  param([string]$Name, [string]$Method = "GET", [string]$Path, $Body, [int]$Expect = 200)
  $url = "$Base$Path"
  $status = 0
  $content = ""
  try {
    if ($Method -eq "GET") {
      $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30
    } else {
      $json = if ($null -ne $Body) { $Body | ConvertTo-Json -Depth 6 -Compress } else { "{}" }
      $r = Invoke-WebRequest -Uri $url -Method $Method -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec 60
    }
    $status = [int]$r.StatusCode
    $content = [string]$r.Content
  } catch {
    if ($null -ne $_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    if ($status -ne $Expect) {
      $script:fail++
      Write-Host ("  [FAIL] {0,-34} {1} {2}" -f $Name, $status, $_.Exception.Message) -ForegroundColor Red
      return
    }
    $script:pass++
    Write-Host ("  [OK]   {0,-34} {1} (预期)" -f $Name, $status) -ForegroundColor Green
    return
  }
  if ($status -ne $Expect) {
    $script:fail++
    Write-Host ("  [FAIL] {0,-34} {1} (期望 {2})" -f $Name, $status, $Expect) -ForegroundColor Red
    return
  }
  $script:pass++
  Write-Host ("  [OK]   {0,-34} {1} {2,7} bytes" -f $Name, $status, $content.Length) -ForegroundColor Green
  return
}

Write-Host "Horizon smoke @ $Base" -ForegroundColor Cyan

Write-Host "`n[1] meta / 健康检查"
Hit "GET /health" -Path "/health"
Hit "meta/status (us)" -Path "/api/v1/meta/status?market=us"
Hit "meta/status (cn)" -Path "/api/v1/meta/status?market=cn"

Write-Host "`n[2] 市场拥挤度（2 市场 × 7 周期，13 固定行业随响应返回）"
foreach ($m in @("us", "cn")) {
  foreach ($p in @("1d", "3d", "5d", "10d", "30d", "90d", "250d")) {
    Hit "crowding $m/$p" -Path "/api/v1/crowding/score?market=$m&period=$p"
  }
}
Hit "crowding history us" -Path "/api/v1/crowding/history?market=us&days=365"
Hit "crowding industries" -Path "/api/v1/crowding/industries?market=us"

Write-Host "`n[3] 风格轮动"
Hit "rotation size us" -Path "/api/v1/rotation/score?market=us&group=size"
Hit "rotation style us" -Path "/api/v1/rotation/score?market=us&group=style"
Hit "rotation size cn" -Path "/api/v1/rotation/score?market=cn&group=size"
Hit "rotation style cn" -Path "/api/v1/rotation/score?market=cn&group=style"

Write-Host "`n[4] 估值分析"
Hit "valuation search" -Path "/api/v1/valuation/search?q=apple&market=us"
Hit "valuation search cn" -Path ("/api/v1/valuation/search?q=" + [uri]::EscapeDataString("茅台") + "&market=cn")
Hit "valuation watchlist" -Path "/api/v1/valuation/watchlist?market=us"
Hit "valuation score AAPL" -Path "/api/v1/valuation/score/AAPL?market=us"
Hit "valuation score 600519" -Path "/api/v1/valuation/score/600519?market=cn"

Write-Host "`n[5] 因子策略"
Hit "factor strategies" -Path "/api/v1/factor/strategies"
Hit "factor benchmarks us" -Path "/api/v1/factor/benchmarks?market=us"
Hit "factor benchmarks cn" -Path "/api/v1/factor/benchmarks?market=cn"
Hit "factor backtest" -Method "POST" -Path "/api/v1/factor/backtest" -Body @{
  market = "us"; strategyId = "momentum"; start = "2023-01-01"; end = "2024-12-31"; benchmark = "spx"
}
Hit "factor mine" -Path "/api/v1/factor/mine?market=us&window=252"

Write-Host "`n[6] 期权策略"
Hit "options strategies" -Path "/api/v1/options/strategies"
Hit "options spot AAPL" -Path "/api/v1/options/spot/AAPL?market=us"
Hit "options expiries AAPL" -Path "/api/v1/options/expiries/AAPL?market=us"
Hit "options payoff straddle" -Method "POST" -Path "/api/v1/options/payoff" -Body @{
  spot = 230.0; strategy = "straddle"; rangePct = 0.25; legs = @(
    @{ type = "call"; side = "long"; strike = 230; premium = 5.2; qty = 1 },
    @{ type = "put"; side = "long"; strike = 230; premium = 4.9; qty = 1 }
  )
}
Hit "options payoff butterfly" -Method "POST" -Path "/api/v1/options/payoff" -Body @{
  spot = 230.0; strategy = "butterfly"; rangePct = 0.25; legs = @(
    @{ type = "call"; side = "long"; strike = 225; premium = 6.1; qty = 1 },
    @{ type = "call"; side = "short"; strike = 230; premium = 3.2; qty = 2 },
    @{ type = "call"; side = "long"; strike = 235; premium = 1.4; qty = 1 }
  )
}
Hit "options backtest" -Method "POST" -Path "/api/v1/options/backtest" -Body @{
  market = "us"; strategyId = "covered_call"; start = "2023-01-01"; end = "2024-12-31"; benchmark = "spx"
}

Write-Host "`n[7] 账号（开源部署默认关闭认证，403/400 属预期）"
Hit "auth/me 无令牌" -Path "/api/v1/auth/me" -Expect 401
Hit "auth/config" -Path "/api/v1/auth/config"

if ($WriteTests) {
  Write-Host "`n[8] 写操作（会改动本地数据库）"
  Hit "watchlist add" -Method "POST" -Path "/api/v1/valuation/watchlist" -Body @{ symbol = "MSFT"; market = "us" }
  Hit "watchlist reorder" -Method "POST" -Path "/api/v1/valuation/watchlist/reorder" -Body @{ ids = @() }
}

Write-Host ""
Write-Host ("共 {0} 项检查：PASS {1} / FAIL {2}" -f ($script:pass + $script:fail), $script:pass, $script:fail) -ForegroundColor Cyan
if ($script:fail -eq 0) {
  Write-Host "ALL PASS" -ForegroundColor Green
  exit 0
} else {
  Write-Host ("FAILED: {0} endpoint(s)" -f $script:fail) -ForegroundColor Red
  exit 1
}