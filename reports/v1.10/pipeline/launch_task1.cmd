@echo off
rem harness-v1.10 pass, task 1: the held-out half through the full pipeline at harness-v1.9.0 (PROTOCOL.md). Task Scheduler only: a paid run is never a child of a session (D-43).
rem   schtasks /Create /TN RERUN_v110_task1 /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\pipeline\launch_task1.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist reports\v1.10\pipeline\heldout_v190 mkdir reports\v1.10\pipeline\heldout_v190
echo LAUNCH %DATE% %TIME% >> reports\v1.10\pipeline\heldout_v190\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\pipeline\measure.py --set heldout --worktree .claude\worktrees\v110-harness-v1.9.0 --tag harness-v1.9.0 --out reports\v1.10\pipeline\heldout_v190 --go --log-file reports\v1.10\pipeline\heldout_v190\run.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> reports\v1.10\pipeline\heldout_v190\launcher.txt
