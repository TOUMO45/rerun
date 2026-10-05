@echo off
rem Out-of-sample scan of harness-v1.7.2 (METHODOLOGY "harness-v1.7.2, the out-of-sample scan and TEST-B"): the 5 repositories picked by select_repos.py
rem (reports\live_scan\oos_v172\selection.json), once each, through RERUN's own API, entry cap $2.50. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_oos_scan /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\live_scan\oos_v172\launch_scan.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_oos_scan
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\live_scan\oos_v1.7.2 mkdir runs\live_scan\oos_v1.7.2
echo LAUNCH %DATE% %TIME% oos scan >> runs\live_scan\oos_v1.7.2\launcher.txt
for /f "usebackq delims=" %%U in (`backend\.venv\Scripts\python.exe -c "import json;print(' '.join(json.load(open('reports/live_scan/oos_v172/selection.json'))['picks']))"`) do set URLS=%%U
backend\.venv\Scripts\pythonw.exe -u reports\live_scan\run_live_scan.py --out-subdir oos_v1.7.2 --log-file runs\live_scan\oos_v1.7.2\scan_stdout.log %URLS%
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\live_scan\oos_v1.7.2\launcher.txt
