@echo off
rem harness-v1.10 pass: one paid run of minmaxot at harness-v1.10.0-rc5 with the behavioural checks turned on (PLAN.md, including its deviation section), cap 5 USD. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_live /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\live_v110\launch_live_v110.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
rem rc5 turns the checks off by default; this run is the check of their wiring, so it turns them on for itself.
set BEHAVIOUR_CHECKS=true
if not exist runs\v1.10\live_v110 mkdir runs\v1.10\live_v110
rem Transport workaround (PLAN.md, deviation): on 2026-10-09 the first attempt ended INFRA_ERROR (git fetch of the repository timed out four times at about 12 KB/s from this machine to GitHub; record kept as attempt1_infra_error_git_timeout.json).
rem If a local bare mirror of the repository exists, git reads that URL from the mirror. It changes where the bytes come from, not the commit, the pipeline or any harness file.
if exist "%TEMP%\minmaxot_mirror.git\HEAD" set GIT_CONFIG_COUNT=1
if exist "%TEMP%\minmaxot_mirror.git\HEAD" set GIT_CONFIG_KEY_0=url.%TEMP%\minmaxot_mirror.git.insteadOf
if exist "%TEMP%\minmaxot_mirror.git\HEAD" set GIT_CONFIG_VALUE_0=https://github.com/stephaneckstein/minmaxot
if exist "%TEMP%\minmaxot_mirror.git\HEAD" echo MIRROR %TEMP%\minmaxot_mirror.git >> runs\v1.10\live_v110\launcher.txt
echo LAUNCH %DATE% %TIME% harness-v1.10.0-rc5 BEHAVIOUR_CHECKS=%BEHAVIOUR_CHECKS% >> runs\v1.10\live_v110\launcher.txt
backend\.venv\Scripts\pythonw.exe -u .claude\worktrees\v110-rc5\scripts\live_run.py --name stephaneckstein__minmaxot --corpus .claude\worktrees\v110-rc5\backend\app\batch\corpus_v4\corpus.yaml --out runs\v1.10\live_v110\02_stephaneckstein__minmaxot_rc5.json --cost-cap-usd 5.00 --dev-run --batch-meta "{\"harness_tag\":\"harness-v1.10.0-rc5\",\"label\":\"POST-HOC wiring check of the behavioural checks, never merged into TEST-C\"}" > runs\v1.10\live_v110\run_stdout.log 2>&1
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\v1.10\live_v110\launcher.txt
