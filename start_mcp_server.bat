@echo off
chcp 65001 >nul
title 赛博大脑 MCP 服务器
echo ============================================================
echo  赛博大脑 MCP 服务器  (端口 8765)
echo  豆包连接地址: http://127.0.0.1:8765/mcp
echo  关闭本窗口 = 停止 MCP 服务
echo ============================================================
echo.
cd /d C:\cyber-brain
C:\Users\Adminn\.workbuddy\binaries\python\envs\default\Scripts\python.exe mcp_server.py --port 8765
pause
