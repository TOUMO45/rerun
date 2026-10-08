@echo off
rem harness-v1.10 pass, task 5: one paid run of minmaxot at harness-v1.9.0 (PLAN.md), cap 5 USD. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_mkdir /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\mkdir_live\launch_mkdir_live.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\v1.10\mkdir_live mkdir runs\v1.10\mkdir_live
echo LAUNCH %DATE% %TIME% >> runs\v1.10\mkdir_live\launcher.txt
backend\.venv\Scripts\pythonw.exe -u .claude\worktrees\v110-harness-v1.9.0\scripts\live_run.py --name stephaneckstein__minmaxot --corpus .claude\worktrees\v110-harness-v1.9.0\backend\app\batch\corpus_v4\corpus.yaml --out runs\v1.10\mkdir_live\02_stephaneckstein__minmaxot_v190.json --cost-cap-usd 5.00 --dev-run --batch-meta "{\"harness_tag\":\"harness-v1.9.0\",\"label\":\"POST-HOC live check of the output_dir repair, never merged into TEST-C\"}" > runs\v1.10\mkdir_live\run_stdout.log 2>&1
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\v1.10\mkdir_live\launcher.txt
