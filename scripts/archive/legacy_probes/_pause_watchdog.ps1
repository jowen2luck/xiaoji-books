# Pause Watchdog — send Ctrl-C to batch_ingest workers when target books complete
# Usage: powershell -File _pause_watchdog.ps1 -CheckIntervalSec 30 -TargetShardBooks 60
param(
    [int]$CheckIntervalSec = 30,
    [int]$TargetShardBooks = 60
)
$ErrorActionPreference = "Stop"
$shardCheckpoints = @(
    "D:\Pcode\play\_skills\book-library-skill\data\shard1_checkpoint.jsonl",
    "D:\Pcode\play\_skills\book-library-skill\data\shard2_checkpoint.jsonl",
    "D:\Pcode\play\_skills\book-library-skill\data\shard3_checkpoint.jsonl",
    "D:\Pcode\play\_skills\book-library-skill\data\shard4_checkpoint.jsonl"
)
$logFile = "D:\Pcode\play\_skills\book-library-skill\data\logs\watchdog.log"

function Count-Success($file) {
    if (-not (Test-Path $file)) { return 0 }
    $n = 0
    Get-Content $file -Encoding UTF8 | ForEach-Object {
        if ($_ -match '"success"') { $n++ }
    }
    return $n
}

while ($true) {
    $total = 0; $detail = @()
    foreach ($cp in $shardCheckpoints) {
        $n = Count-Success $cp
        $total += $n
        $shardName = [System.IO.Path]::GetFileNameWithoutExtension($cp).Replace("_checkpoint","")
        $detail += "${shardName}=${n}"
    }
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $msg = "$ts shard_completed=$total/$TargetShardBooks ($($detail -join ' '))"
    Add-Content $logFile $msg -Encoding UTF8
    Write-Host $msg
    if ($total -ge $TargetShardBooks) {
        Write-Host "TARGET REACHED! Sending Ctrl-C to batch_ingest workers..."
        $workers = Get-CimInstance Win32_Process -Filter "Name='python.exe' AND CommandLine LIKE '%batch_ingest%'"
        foreach ($w in $workers) {
            Write-Host "  Stopping PID $($w.ProcessId)"
            Stop-Process -Id $w.ProcessId -Force
        }
        Add-Content $logFile "$ts WORKERS_STOPPED" -Encoding UTF8
        break
    }
    Start-Sleep -Seconds $CheckIntervalSec
}
