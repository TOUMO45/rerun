@echo off
rem harness-v1.10 pass, task 1: the six patches whose first attempt ended in an API error (PROTOCOL.md: a driver error is re-run once). Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_task1_retry /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\pipeline\launch_task1_retry.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
echo LAUNCH %DATE% %TIME% >> reports\v1.10\pipeline\heldout_v190\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\pipeline\measure.py --set heldout --worktree .claude\worktrees\v110-harness-v1.9.0 --tag harness-v1.9.0 --out reports\v1.10\pipeline\heldout_v190 --retry-errors --go --log-file reports\v1.10\pipeline\heldout_v190\run.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> reports\v1.10\pipeline\heldout_v190\launcher.txt
