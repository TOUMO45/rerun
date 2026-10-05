@echo off
rem harness-v1.7.2 seal launcher: every live stage of the harness-v1.7.1 seal against harness-v1.7.2-rc. Run by the Windows Task Scheduler, never from a session (D-43).
rem   schtasks /Create /TN RERUN_v172_seal /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.7.2\seal\launch_seal.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_v172_seal
rem /SD far in the future: the entry runs only on /Run and never fires again by itself.
rem cap $1.50 API-reported (the owner's seal bound since v1.4.3); a resumed invocation skips the stages that already passed.
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\sandbox_verification\v1.7.2-seal mkdir runs\sandbox_verification\v1.7.2-seal
echo LAUNCH %DATE% %TIME% v1.7.2 seal >> runs\sandbox_verification\v1.7.2-seal\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.7.2\seal\run_seal_v172.py --go --max-usd 1.50 --log-file runs\sandbox_verification\v1.7.2-seal\seal_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.7.2-seal\launcher.txt
