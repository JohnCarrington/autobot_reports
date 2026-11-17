# dukascopy_fetch.ps1 — Addendum M data recovery for 9–17 Nov 2026
#
# Downloads GBP/USD hourly tick files (.bi5, LZMA-compressed) from Dukascopy's
# public data feed and packages them into a single zip for transfer to the
# research droplet.
#
# This script does not decompress the .bi5 files — decompression happens on
# the research droplet using scripts/dukascopy_decode.py so the Windows
# machine does not need an LZMA tool installed.
#
# Verified Dukascopy URL pattern (as of 2026):
#     https://datafeed.dukascopy.com/datafeed/{INSTR}/{YYYY}/{MM0}/{DD}/{HH}h_ticks.bi5
#   where MM0 is the zero-based month index (November = 10). This is Dukascopy's
#   long-standing public price-history endpoint used by dukascopy-node, jforex,
#   and dukascopy-python. There is no API key, no account, and no sign-in.
#
# Usage from PowerShell (not cmd):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\dukascopy_fetch.ps1
#
# If every download fails (connection refused / timeout for all 7 trading
# days), the script prints a clear block message and exits with code 2.
# The operator then reports back and we pick a different route.

$ErrorActionPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Instrument = 'GBPUSD'

# 2026-11-09 Mon through 2026-11-17 Tue. Weekends (14 Sat, 15 Sun) excluded —
# FX market is closed.
$Dates = @(
    [datetime]'2026-11-09'   # Mon
    [datetime]'2026-11-10'   # Tue
    [datetime]'2026-11-11'   # Wed
    [datetime]'2026-11-12'   # Thu
    [datetime]'2026-11-13'   # Fri
    [datetime]'2026-11-16'   # Mon
    [datetime]'2026-11-17'   # Tue (today)
)

# Output lands beside the script.
$OutRoot = Join-Path $PSScriptRoot 'dukascopy_gbpusd_2026-11-09_17'
if (-not (Test-Path $OutRoot)) { New-Item -ItemType Directory -Path $OutRoot | Out-Null }

$Headers = @{
    'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

$NonEmpty  = 0   # .bi5 files with payload bytes (market open hour)
$EmptyOk   = 0   # 0-byte .bi5 files (expected during FX-closed hours)
$Failed    = @() # URLs where the download itself failed
$Attempted = 0

foreach ($d in $Dates) {
    $y  = $d.Year
    $m0 = '{0:D2}' -f ($d.Month - 1)         # zero-based month per Dukascopy
    $m  = '{0:D2}' -f $d.Month
    $dd = '{0:D2}' -f $d.Day
    $DateDir = Join-Path $OutRoot "$y-$m-$dd"
    if (-not (Test-Path $DateDir)) { New-Item -ItemType Directory -Path $DateDir | Out-Null }

    # Each weekday: 24 hourly files. On the current day (today), the files
    # for hours past the current UTC hour won't exist yet — they'll 404 and
    # are recorded as "not yet published" (NOT as failed downloads).
    for ($h = 0; $h -lt 24; $h++) {
        $hh  = '{0:D2}' -f $h
        $Url = "https://datafeed.dukascopy.com/datafeed/$Instrument/$y/$m0/$dd/${hh}h_ticks.bi5"
        $Dst = Join-Path $DateDir "${hh}h_ticks.bi5"
        if (Test-Path $Dst) { continue }      # resumable: skip already downloaded
        $Attempted++
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Dst -Headers $Headers -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
            $size = (Get-Item $Dst).Length
            if ($size -eq 0) {
                $EmptyOk++
                Write-Host ("  {0}-{1}-{2} {3}h  empty (market closed hour)" -f $y, $m, $dd, $hh) -ForegroundColor DarkGray
            } else {
                $NonEmpty++
                Write-Host ("  {0}-{1}-{2} {3}h  {4} bytes" -f $y, $m, $dd, $hh, $size)
            }
        } catch {
            if (Test-Path $Dst) { Remove-Item $Dst -Force -ErrorAction SilentlyContinue }
            $errMsg = $_.Exception.Message
            if ($errMsg -match '404') {
                # The hour hasn't been published yet (future / today-late-hours)
                Write-Host ("  {0}-{1}-{2} {3}h  404 not yet published" -f $y, $m, $dd, $hh) -ForegroundColor DarkYellow
            } else {
                $Failed += $Url
                Write-Warning ("FAIL {0} -- {1}" -f $Url, $errMsg)
            }
        }
        Start-Sleep -Milliseconds 150    # polite rate limit
    }
}

Write-Host ""
Write-Host "========== SUMMARY =========="  -ForegroundColor Cyan
Write-Host ("Attempted downloads : {0}" -f $Attempted)
Write-Host ("Non-empty .bi5 files: {0}" -f $NonEmpty)
Write-Host ("Empty files (closed hours expected): {0}" -f $EmptyOk)
Write-Host ("Failed downloads    : {0}" -f $Failed.Count)

# Hard-failure detection: if nothing was downloaded, the Dukascopy CDN is
# inaccessible from Windows too and we need a different route.
if ($NonEmpty -eq 0 -and $EmptyOk -eq 0) {
    Write-Host ""
    Write-Host "!!! Dukascopy appears to be blocked from this Windows machine too." -ForegroundColor Red
    Write-Host "    0 of $Attempted downloads succeeded (not even an empty-file response)." -ForegroundColor Red
    Write-Host "    Report this back to the research session. Next-best options:"      -ForegroundColor Red
    Write-Host "      - signup for a free TwelveData / AlphaVantage / Polygon key"     -ForegroundColor Red
    Write-Host "      - download HistData.com monthly ASCII M1 manually via browser"   -ForegroundColor Red
    Write-Host "      - use the retired AutoBot's IG REST credentials (shared quota)"  -ForegroundColor Red
    exit 2
}

# Per-date validation
Write-Host ""
Write-Host "========== PER-DATE VALIDATION ==========" -ForegroundColor Cyan
$ExpectedCount = 24
$MissingDates = @()
foreach ($d in $Dates) {
    $dstr = $d.ToString('yyyy-MM-dd')
    $dir  = Join-Path $OutRoot $dstr
    if (-not (Test-Path $dir)) {
        Write-Host "  $dstr : directory missing" -ForegroundColor Red
        $MissingDates += $dstr
        continue
    }
    $files = Get-ChildItem $dir -File
    $nNonEmpty = ($files | Where-Object { $_.Length -gt 0 }).Count
    $nEmpty = ($files | Where-Object { $_.Length -eq 0 }).Count
    $nMissing = $ExpectedCount - $files.Count
    $flag = ''
    if ($nNonEmpty -lt 6) {         # <6 market hours is suspicious even for Mon/Fri
        $flag = ' *** suspicious — fewer than 6 non-empty hours'
        $MissingDates += $dstr
    }
    Write-Host ("  {0} : {1} non-empty, {2} empty, {3} missing hour files{4}" -f $dstr, $nNonEmpty, $nEmpty, $nMissing, $flag)
}

# Zip for transfer
$Zip = Join-Path $PSScriptRoot 'dukascopy_gbpusd_2026-11-09_17.zip'
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $OutRoot -DestinationPath $Zip -CompressionLevel Optimal
$ZipSize = (Get-Item $Zip).Length
Write-Host ""
Write-Host ("Archive: {0}" -f $Zip)                    -ForegroundColor Green
Write-Host ("Size   : {0:N0} bytes ({1:N1} KB)" -f $ZipSize, ($ZipSize / 1024)) -ForegroundColor Green

if ($MissingDates.Count -gt 0) {
    Write-Host ""
    Write-Host "Dates with suspicious / missing data:"  -ForegroundColor Yellow
    $MissingDates | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "========== TRANSFER ==========" -ForegroundColor Cyan
Write-Host 'Replace <ssh-user> and <droplet-host>, then run:'
Write-Host ("  scp '{0}' <ssh-user>@<droplet-host>:/tmp/" -f $Zip) -ForegroundColor Green
Write-Host ""
Write-Host 'After scp completes, tell the research session: "archive at /tmp/dukascopy_gbpusd_2026-11-09_17.zip".'
