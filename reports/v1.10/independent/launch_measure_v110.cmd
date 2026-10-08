@echo off
rem harness-v1.10 pass, task 4: the confirmed independent set through the full pipeline at the v1.10 release candidate that was reviewed and frozen (reports/v1.10/behaviour/PROTOCOL.md). Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_m110 /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\independent\launch_measure_v110.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist reports\v1.10\independent\measure_v110 mkdir reports\v1.10\independent\measure_v110
echo LAUNCH %DATE% %TIME% >> reports\v1.10\independent\measure_v110\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\pipeline\measure.py --set reports\v1.10\independent --worktree .claude\worktrees\v110-rc4 --tag harness-v1.10.0-rc4 --out reports\v1.10\independent\measure_v110 --ids reports\v1.10\independent\measured_ids.txt --projection-limit-usd 25 --cap-usd 25 --go --log-file reports\v1.10\independent\measure_v110\run.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> reports\v1.10\independent\measure_v110\launcher.txt
