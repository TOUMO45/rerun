@echo off
rem harness-v1.10 seal, the two stages that test what v1.10 changed in the sandbox (the smoke launcher and the tracer), run before the v140 stage: on 2026-10-09 the v140 stage's
rem entry-7 check could not upload its 56 MB tree from this machine (about 0.4 MB/s up, below the harness's 0.987 MB/s upload assumption; eight attempts, each stopped by an
rem ApiTimeoutError on POST /sandboxes/v1/files). The seal is still complete only when all three stages are ok in SEAL_RUN.json; this only changes the order. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v110_seal_stages /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.10\seal\launch_seal_stages.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if "%RERUN_V110_RC_TAG%"=="" set RERUN_V110_RC_TAG=harness-v1.10.0-rc5
if not exist runs\sandbox_verification\v1.10-seal mkdir runs\sandbox_verification\v1.10-seal
echo LAUNCH %DATE% %TIME% v1.10 seal stages smoke+v110 %RERUN_V110_RC_TAG% >> runs\sandbox_verification\v1.10-seal\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.10\seal\run_seal_v110.py --go --max-usd 1.50 --stage smoke --stage v110 --log-file runs\sandbox_verification\v1.10-seal\seal_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.10-seal\launcher.txt
