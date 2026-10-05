@echo off
rem harness-v1.7 probe follow-up launcher (R1 (a), a dd-written swap file; METHODOLOGY annotation of 2026-10-05): run by the Windows Task Scheduler, never from a session (D-43).
rem   the owner schedules it:  schtasks /Create /TN RERUN_v17_probe_dd /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.7\probe\launch_probe_dd.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem                            schtasks /Run /TN RERUN_v17_probe_dd
rem /SD far in the future: the entry runs only when /Run is typed, and never fires again by itself (the probe's entry would have, on 2026-10-05 at 23:59).
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\sandbox_verification\v1.7-probes mkdir runs\sandbox_verification\v1.7-probes
echo LAUNCH %DATE% %TIME% v1.7 probe dd follow-up >> runs\sandbox_verification\v1.7-probes\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.7\probe\run_v17_probe_dd.py --go --max-usd 0.10 --log-file runs\sandbox_verification\v1.7-probes\probe_dd_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.7-probes\launcher.txt
