@echo off
rem TEST-B launcher (METHODOLOGY "harness-v1.7.2, the out-of-sample scan and TEST-B"; backend\app\batch\corpus_v3\prereg.json): Task Scheduler only, never from a session (D-43).
rem   schtasks /Create /TN RERUN_test_b /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\test-b\launch_test_b.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_test_b
rem The tag is always harness-v1.7.2; the caps are the pre-registered ones (the runner refuses any other).
cd /d %~dp0..\..
set PYTHONIOENCODING=utf-8
if not exist runs\corpus_v3_batch\harness-v1.7.2 mkdir runs\corpus_v3_batch\harness-v1.7.2
echo LAUNCH %DATE% %TIME% TEST-B >> runs\corpus_v3_batch\harness-v1.7.2\test_b_launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\test-b\run_test_b.py --cap-usd 95 --entry-cap-usd 2.50 --go --log-file runs\corpus_v3_batch\harness-v1.7.2\test_b_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\corpus_v3_batch\harness-v1.7.2\test_b_launcher.txt
