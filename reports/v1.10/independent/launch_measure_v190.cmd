@echo off
rem harness-v1.10 pass, task 4: the confirmed independent set through the full pipeline at harness-v1.9.0 (reports/v1.10/behaviour/PROTOCOL.md, "Measurement"). The run step of each patch is the confirmation
rem run (--replay-runs), except the four ids in no_replay_ids.txt. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_m190 /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\independent\launch_measure_v190.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist reports\v1.10\independent\measure_v190 mkdir reports\v1.10\independent\measure_v190
echo LAUNCH %DATE% %TIME% >> reports\v1.10\independent\measure_v190\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\pipeline\measure.py --set reports\v1.10\independent --worktree .claude\worktrees\v110-harness-v1.9.0 --tag harness-v1.9.0 --out reports\v1.10\independent\measure_v190 --ids reports\v1.10\independent\measured_ids.txt --replay-runs reports\v1.10\independent\confirm --no-replay-ids reports\v1.10\independent\no_replay_ids.txt --projection-limit-usd 12 --cap-usd 12 --go --log-file reports\v1.10\independent\measure_v190\run.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> reports\v1.10\independent\measure_v190\launcher.txt
