@echo off
rem harness-v1.8, Phase 2: the 21 old held-out entries re-run as DEV-CONTAMINATED on the working tree (reports\dev\v18\run_dev_v18.py). Task Scheduler only: a paid batch is never a child of a session (D-43).
rem   usage: launch_dev_v18.cmd <SETS> <CAP_USD> [SUBDIR] [IDS]  (several sets or ids joined with +: TEST-B+TEST, 1+2)       e.g.  launch_dev_v18.cmd TEST-B,TEST 30 round1
rem   schtasks /Create /TN RERUN_dev_v18 /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\dev\v18\launch_dev_v18.cmd TEST-B,TEST 30 round1" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_dev_v18        (and afterwards: schtasks /Change /TN RERUN_dev_v18 /DISABLE)
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
rem cmd.exe splits batch arguments at commas: name several sets with + (TEST-B+TEST), turned back into a comma below
set SETS=%1
set SETS=%SETS:+=,%
set CAP=%2
set SUB=%3
set IDS=%4
set IDS=%IDS:+=,%
if "%SUB%"=="" set SUB=round1
if not exist runs\dev_v18\%SUB% mkdir runs\dev_v18\%SUB%
echo LAUNCH %DATE% %TIME% sets=%SETS% cap=%CAP% sub=%SUB% ids=%IDS% >> runs\dev_v18\%SUB%\launcher.txt
if "%IDS%"=="" (
  backend\.venv\Scripts\pythonw.exe -u reports\dev\v18\run_dev_v18.py --sets %SETS% --cap-usd %CAP% --out-subdir %SUB% --go --log-file runs\dev_v18\%SUB%\run_stdout.log
) else (
  backend\.venv\Scripts\pythonw.exe -u reports\dev\v18\run_dev_v18.py --sets %SETS% --ids %IDS% --cap-usd %CAP% --out-subdir %SUB% --go --log-file runs\dev_v18\%SUB%\run_stdout.log
)
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\dev_v18\%SUB%\launcher.txt
