@echo off
rem harness-v1.7.0 seal launcher (option B; METHODOLOGY "harness-v1.7 - PRE-REGISTRATION"): run by the Windows Task Scheduler, never from a session (D-43).
rem   the owner schedules it:  schtasks /Create /TN RERUN_v17_seal /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.7\seal\launch_seal.cmd" /SC ONCE /ST HH:MM /F
rem                            schtasks /Run /TN RERUN_v17_seal
rem cap $1.50 API-reported (the owner's seal bound since v1.4.3); a resumed invocation skips the stages that already passed.
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\sandbox_verification\v1.7-seal mkdir runs\sandbox_verification\v1.7-seal
echo LAUNCH %DATE% %TIME% v1.7 seal >> runs\sandbox_verification\v1.7-seal\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.7\seal\run_seal_v17.py --go --max-usd 1.50 --log-file runs\sandbox_verification\v1.7-seal\seal_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.7-seal\launcher.txt
