# Addendum M data recovery — 9–17 November 2026 GBP/USD

The research droplet's egress is blocked to `datafeed.dukascopy.com` (the Dukascopy data-feed CDN at `194.8.15.180` times out). Yahoo, Stooq, Finnhub-forex and AlphaVantage are also unavailable here (429 / paywall / key-gated). This folder provides a Windows-side fetcher so you can pull the data on a machine with a different egress path.

## Two files you'll use

- `dukascopy_fetch.ps1` — PowerShell script that runs on your Windows machine.
- `dukascopy_decode.py` — Python script that runs on this droplet once the archive is uploaded.

## Step 1 — on your Windows machine

1. Put `dukascopy_fetch.ps1` anywhere on disk (e.g. `C:\Users\<you>\Downloads\`).
2. Open a **PowerShell** window (not cmd) in that folder.
3. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\dukascopy_fetch.ps1
   ```

4. The script downloads the hourly `.bi5` tick files directly from `https://datafeed.dukascopy.com/datafeed/GBPUSD/...` for each market-open hour across 9, 10, 11, 12, 13, 16, 17 November 2026. It skips the weekend and expects some empty files during the Friday 22:00 → Sunday 22:00 UTC market-closed window.
5. When the script finishes, it prints:

   - a per-date summary of non-empty / empty / 404 files,
   - the path to `dukascopy_gbpusd_2026-11-09_17.zip`,
   - the exact `scp` command for step 2 (with placeholders).

## Step 1b — if Dukascopy is blocked from Windows too

The script exits with code `2` and prints a block message if *zero* files download. In that case, don't SCP anything — report back and we'll pick a fallback:

- free API key (TwelveData / AlphaVantage / Polygon — all have no-cc sign-up pages),
- HistData.com monthly ASCII M1 manual download via browser,
- IG REST via the retired bot's credentials (shared allowance with the new droplet).

## Step 2 — transfer the archive

Replace `<ssh-user>` and `<droplet-host>` with the values you use for this session. The script will print this command for you with the real path substituted:

```
scp C:\...\dukascopy_gbpusd_2026-11-09_17.zip <ssh-user>@<droplet-host>:/tmp/
```

## Step 3 — on this droplet (I run this after you SCP)

```
cd /home/autobot/tradingbot-wt/addendum-m/gbpusd_pia_exhaustion_20261117
python3 scripts/dukascopy_decode.py /tmp/dukascopy_gbpusd_2026-11-09_17.zip
```

The decode script:

1. Unpacks the zip in memory.
2. Decompresses each hourly `.bi5` using the standard LZMA-alone format.
3. Parses the 20-byte tick records (big-endian JForex layout: `msec, ask×1e5, bid×1e5, ask_vol, bid_vol`).
4. Aggregates ticks into 5-minute MID OHLC bars (MID = (bid + ask) / 2).
5. Writes one CSV per trading day to `data/candles_recovered/GBPUSD/2026-11-DD.csv` with the same schema as `/opt/tradingbot/data/candles/GBPUSD/2026-*.csv` (× 10000 scale).
6. Prints a per-date bar-count / first-ts / last-ts validation summary.

## Data choices and why

- **MID price**, not BID or ASK alone, to match the 2026 era of `/opt/tradingbot/data/candles/GBPUSD` (see `project_tick_backtest_framework_phase2_20261027` memory).
- **UTC timestamps** throughout — no BST conversion. The 2026 candle archive is already true UTC (see `project_candle_vs_tick_offset_20260928`).
- **Decode on the droplet**, not on Windows — avoids requiring 7-Zip or `pylzma` to be installed on your Windows machine.
- **No overwriting** of `/opt/tradingbot/data/candles/`. Outputs land in the worktree under `data/candles_recovered/GBPUSD/` and the reconstruction script is pointed at both the original archive (through 2026-11-06) and the recovered CSVs.

## Verification notes

- The brief required me to use a verified Dukascopy download method. The URL pattern `https://datafeed.dukascopy.com/datafeed/{INSTR}/{YYYY}/{MM0:02}/{DD:02}/{HH:02}h_ticks.bi5` (zero-based month) is the one used by `dukascopy-node`, `dukascopy-python` and JForex — no API key, no account, public data feed.
- The script resumes safely: existing non-empty files are skipped on re-run.
- Each weekday should yield ~20–22 non-empty hourly files; 22:00–23:59 UTC Fri and 00:00–21:59 UTC Sun will be empty (market closed). Monday 09 Nov may have empty 00h–01h before the Asian session opens.
