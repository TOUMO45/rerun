@echo off
rem harness-v1.10 seal launcher: the live checks of what the behavioural checks changed in the sandbox-touching files (run_seal_v110.py). Run by the Windows Task Scheduler, never from a session (D-43).
rem   schtasks /Create /TN RERUN_v110_seal /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\corpus-v2.1\v1.10\seal\launch_seal.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_v110_seal
rem /SD far in the future: the entry runs only on /Run and never fires again by itself.
rem cap $1.50 API-reported (the owner's seal bound since v1.4.3); a resumed invocation skips the stages that already passed.
rem RERUN_V110_RC_TAG must name the release candidate tag that was measured (set below by the person who launches it).
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if "%RERUN_V110_RC_TAG%"=="" set RERUN_V110_RC_TAG=harness-v1.10.0-rc5
if not exist runs\sandbox_verification\v1.10-seal mkdir runs\sandbox_verification\v1.10-seal
rem Transport workaround, recorded in the seal notes: on 2026-10-08 the download of the entry-7 repository (albertometelli/pfqi) from this machine stalled at about 20 KB/s, so the old entry-7 check lost 4 x 300 s to git timeouts.
rem If a local bare mirror of it exists (git clone --bare --depth 1), git reads that URL from the mirror. It changes where the bytes come from, not what the check does or any harness file.
if exist "%TEMP%\pfqi_mirror.git\HEAD" set GIT_CONFIG_COUNT=1
if exist "%TEMP%\pfqi_mirror.git\HEAD" set GIT_CONFIG_KEY_0=url.%TEMP%\pfqi_mirror.git.insteadOf
if exist "%TEMP%\pfqi_mirror.git\HEAD" set GIT_CONFIG_VALUE_0=https://github.com/albertometelli/pfqi
if exist "%TEMP%\pfqi_mirror.git\HEAD" echo MIRROR %TEMP%\pfqi_mirror.git >> runs\sandbox_verification\v1.10-seal\launcher.txt
echo LAUNCH %DATE% %TIME% v1.10 seal %RERUN_V110_RC_TAG% >> runs\sandbox_verification\v1.10-seal\launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.10\seal\run_seal_v110.py --go --max-usd 1.50 --log-file runs\sandbox_verification\v1.10-seal\seal_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\sandbox_verification\v1.10-seal\launcher.txt
