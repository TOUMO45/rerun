@echo off
rem TEST phase launcher (METHODOLOGY "harness-v1.5 dev/test protocol", section T): run by the Windows Task Scheduler, never from a session.
rem   usage: launch_test.cmd TEST_CAP_USD        e.g.  launch_test.cmd 26.50
rem The tag is always harness-v1.5-final. pythonw has no console, so no console control event can end the batch (D-43); its output goes to --log-file.
cd /d %~dp0..\..\..\..
set PYTHONIOENCODING=utf-8
if not exist runs\corpus_v2_batch\harness-v1.5-final mkdir runs\corpus_v2_batch\harness-v1.5-final
echo LAUNCH %DATE% %TIME% test cap %1 >> runs\corpus_v2_batch\harness-v1.5-final\test_launcher.txt
backend\.venv\Scripts\pythonw.exe -u reports\corpus-v2.1\v1.5\test\run_test_phase.py --tag harness-v1.5-final --test-cap-usd %1 --entry-cap-usd 2.50 --go --log-file runs\corpus_v2_batch\harness-v1.5-final\test_stdout.log
echo PYTHONW_RETURNED %ERRORLEVEL% %DATE% %TIME% >> runs\corpus_v2_batch\harness-v1.5-final\test_launcher.txt
