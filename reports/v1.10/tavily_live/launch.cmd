@echo off
rem The one live run of reports\v1.10\tavily_live\PLAN.md (owner, 2026-10-11/12, the Tavily gap only): minmaxot at harness-v1.10.0, flag mode, Tavily on, cap 10 USD. Task Scheduler only (D-43).
rem   schtasks /Create /TN RERUN_v1100_tavily /TR "cmd /c B:\Desktop\RERUN_Nvidia\reports\v1.10\tavily_live\launch.cmd" /SC ONCE /ST 23:59 /SD 31/12/2030 /F
rem   schtasks /Run /TN RERUN_v1100_tavily
cd /d %~dp0..\..\..
set PYTHONIOENCODING=utf-8
backend\.venv\Scripts\pythonw.exe -u reports\v1.10\tavily_live\launch.py --go
