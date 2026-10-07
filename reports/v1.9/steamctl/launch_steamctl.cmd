@echo off
rem harness-v1.9, task 4: steamctl x3 at harness-v1.7.2 and x3 at harness-v1.8.0 (reports\v1.9\steamctl\PLAN.md). Task Scheduler only: a paid run is never a child of a session (D-43).
rem   schtasks /Create /TN RERUN_v19_steamctl /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.9\steamctl\launch_steamctl.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_v19_steamctl        (afterwards: schtasks /Change /TN RERUN_v19_steamctl /DISABLE)
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\v1.9\steamctl mkdir runs\v1.9\steamctl
echo LAUNCH %DATE% %TIME% >> runs\v1.9\steamctl\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.9\steamctl\run_steamctl.py --go --log-file runs\v1.9\steamctl\run_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\v1.9\steamctl\launcher.txt
