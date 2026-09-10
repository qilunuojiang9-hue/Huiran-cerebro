@echo off
rem ============================================
rem  塞博大脑 Cyber Brain - Web 界面一键启动
rem  双击本文件：自动打开浏览器 + 启动服务
rem  关闭窗口即停止服务
rem ============================================
cd /d "%~dp0"
start "" http://127.0.0.1:8899
"C:\Users\Adminn\.workbuddy\binaries\python\envs\default\Scripts\python.exe" web_ui.py
pause
