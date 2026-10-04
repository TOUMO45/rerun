@echo off
rem harness-v1.7 probe launcher (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION", R1 (a) and R4): run by the Windows Task Scheduler, never from a session (D-43).
rem   the owner schedules it:  schtasks /Create /TN RERUN_v17_probe /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.7\probe\launch_probe.cmd" /SC ONCE /ST HH:MM /F
rem                            schtasks /Run /TN RERUN_v17_probe
rem pythonw has no console, so no console control event can end it; its output goes to --log-file.
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\sandbox_verification\v1.7-probes mkdir runs\sandbox_verification\v1.7-probes
echo LAUNCH %DATE% %TIME% v1.7 probe >> runs\sandbox_verification\v1.7-probes\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.7\probe\run_v17_probe.py --go --max-usd 0.10 --log-file runs\sandbox_verification\v1.7-probes\probe_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.7-probes\launcher.txt
