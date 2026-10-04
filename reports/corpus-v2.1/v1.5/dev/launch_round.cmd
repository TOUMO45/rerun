@echo off
rem DEV round launcher (METHODOLOGY "harness-v1.5 dev/test protocol", D6): run by the Windows Task Scheduler, never from a session.
rem   usage: launch_round.cmd N TAG [DEV_TOTAL]   e.g.  launch_round.cmd 5 harness-v1.7.0 50.00
rem harness-v1.7 (owner, 2026-10-04): entry cap $2.50; DEV_TOTAL is the figure the owner writes in chat (default the pre-registered $40.00)
rem --ledger-ceiling-usd 100.00: the owner's figure written in chat on 2026-10-03 with the $47.96 BILLED reading (METHODOLOGY, budget re-anchoring).
rem pythonw has no console, so no console control event can end the batch (the v1.4.3 gate's python.exe was ended that way twice, D-43); its output goes to --log-file.
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
set DEVTOTAL=%3
if "%DEVTOTAL%"=="" set DEVTOTAL=40.00
if not exist runs\corpus_v2_batch\%2 mkdir runs\corpus_v2_batch\%2
echo LAUNCH %DATE% %TIME% round %1 tag %2 >> runs\corpus_v2_batch\%2\dev_round%1_launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.5\dev\run_dev_round.py --round %1 --tag %2 --entry-cap-usd 2.50 --ledger-ceiling-usd 100.00 --dev-total-usd %DEVTOTAL% --go --log-file runs\corpus_v2_batch\%2\dev_round%1_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\corpus_v2_batch\%2\dev_round%1_launcher.txt
