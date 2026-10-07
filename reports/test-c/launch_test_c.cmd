@echo off
rem TEST-C launcher (reports\dev\v18\DIAGNOSIS_RUBRIC.md; backend\app\batch\corpus_v4\prereg.json): Task Scheduler only, never from a session (D-43).
rem   schtasks /Create /TN RERUN_test_c /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\test-c\launch_test_c.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_test_c
rem The tag is always harness-v1.8.0; the caps are the pre-registered ones (the runner refuses any other).
cd /d %~dp0..\..
set PYTHONIOENCODING=utf-8
if not exist runs\corpus_v4_batch\harness-v1.8.0 mkdir runs\corpus_v4_batch\harness-v1.8.0
echo LAUNCH %DATE% %TIME% TEST-C >> runs\corpus_v4_batch\harness-v1.8.0\test_c_launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\test-c\run_test_c.py --cap-usd 100 --entry-cap-usd 2.50 --go --log-file runs\corpus_v4_batch\harness-v1.8.0\test_c_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\corpus_v4_batch\harness-v1.8.0\test_c_launcher.txt
