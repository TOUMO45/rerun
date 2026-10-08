@echo off
rem harness-v1.10 pass: one paid run of minmaxot at harness-v1.10.0-rc4 (PLAN.md), cap 5 USD. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_live /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\live_v110\launch_live_v110.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\v1.10\live_v110 mkdir runs\v1.10\live_v110
echo LAUNCH %DATE% %TIME% >> runs\v1.10\live_v110\launcher.txt
backend\.venv\Scripts\pythonw.exe -u .claude\worktrees\v110-rc4\scripts\live_run.py --name stephaneckstein__minmaxot --corpus .claude\worktrees\v110-rc4\backend\app\batch\corpus_v4\corpus.yaml --out runs\v1.10\live_v110\02_stephaneckstein__minmaxot_rc4.json --cost-cap-usd 5.00 --dev-run --batch-meta "{\"harness_tag\":\"harness-v1.10.0-rc4\",\"label\":\"POST-HOC wiring check of the behavioural checks, never merged into TEST-C\"}" > runs\v1.10\live_v110\run_stdout.log 2>&1
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\v1.10\live_v110\launcher.txt
