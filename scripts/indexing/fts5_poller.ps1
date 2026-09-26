# FTS5 Background Poller — incremental refresh every 10-15 minutes
# Runs build_fts5.py against all evidence dirs (main + shard*)
param(
    [int]$IntervalMinutes = 12,
    [int]$MaxIterations = 0  # 0 = infinite
)
$ErrorActionPreference = "Stop"
$py = "C:\Users\31239\.meituan-catpaw\runtimes\python\versions\3.12.13\python.exe"
$wd = "D:\Pcode\play\_skills\book-library-skill"
$logFile = "$wd\data\logs\fts5_poller.log"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$iteration = 0
$lastCount = 0
while ($MaxIterations -eq 0 -or $iteration -lt $MaxIterations) {
    $iteration++
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    try {
        $output = & $py -u "$scriptDir\build_fts5.py" --evidence-dir "$wd\data\evidence" 2>&1
        $rc = $LASTEXITCODE
        $json = $output | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1
        $msg = "$ts [iter=$iteration] rc=$rc output=$json"
        Add-Content -Path $logFile -Value $msg -Encoding UTF8
        if ($json) {
            $info = $json | ConvertFrom-Json
            $cnt = $info.pages_indexed
            $delta = $cnt - $lastCount
            if ($delta -gt 0) {
                Write-Host "$ts [FTS5] +$delta pages indexed (total: $cnt, books: $($info.books))"
                $lastCount = $cnt
            }
        }
    } catch {
        $errMsg = "$ts [iter=$iteration] ERROR: $_"
        Add-Content -Path $logFile -Value $errMsg -Encoding UTF8
    }
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}
