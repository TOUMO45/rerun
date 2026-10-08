@echo off
rem harness-v1.10 pass, task 4: a pilot of the v1.10 driver on a sample of the DEV half in the real sandbox (development; checks the tracer end to end). Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_ablate /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\behaviour\launch_pilot.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist reports\v1.10\behaviour\pilot_rc2_ablate_static mkdir reports\v1.10\behaviour\pilot_rc2_ablate_static
echo LAUNCH %DATE% %TIME% >> reports\v1.10\behaviour\pilot_rc2_ablate_static\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\pipeline\measure.py --set dev --worktree .claude\worktrees\v110-rc2 --tag harness-v1.10.0-rc2 --out reports\v1.10\behaviour\pilot_rc2_ablate_static --ids reports\v1.10\behaviour\ablation_ids.txt --projection-limit-usd 6 --ablate-static --go --log-file reports\v1.10\behaviour\pilot_rc2_ablate_static\run.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> reports\v1.10\behaviour\pilot_rc2_ablate_static\launcher.txt
