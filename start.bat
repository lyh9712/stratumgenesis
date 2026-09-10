@echo off
chcp 65001 >nul
setlocal
title StratumGenesis v0.3 (local experiment)
REM ===========================================================================
REM  StratumGenesis v0.3 - one-click local launcher (Windows)
REM  Local experiment prototype only. Not for public deployment.
REM  Comments kept ASCII-only so cmd.exe never mis-parses this file.
REM  See LICENSE / LICENSE-SCOPE.md / NOTICE / README.md for details.
REM ===========================================================================
REM  Python discovery: first real install wins. The %LOCALAPPDATA%\Microsoft\
REM  WindowsApps\python.exe stub is deliberately NOT a candidate: it is a
REM  symlink to AppInstallerPythonRedirector.exe, so "if exist" reports true
REM  while it is not a usable interpreter, and it would otherwise overwrite
REM  an earlier real match. PATH-based discovery is used as the last resort.

set "PY="
for %%C in (
  "C:\Users\12285\AppData\Local\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do if not defined PY if exist "%%~C" set "PY=%%~C"

if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"

if not defined PY (
  echo [start.bat] python.exe not found.
  echo [start.bat] Install Python 3.10+ and tick "Add python.exe to PATH",
  echo [start.bat] then run start.bat again.
  pause
  exit /b 1
)

echo [start.bat] Python: %PY%
"%PY%" --version

echo [start.bat] Installing runtime dependency (only third-party dep: ecdsa)...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [start.bat] Dependency install failed. Check network and retry, or run manually:
  echo [start.bat]   %PY% -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo.
echo [start.bat] Starting local server (127.0.0.1:28417 only, local machine only)...
echo [start.bat] Open http://127.0.0.1:28417/index.html in your browser.
echo [start.bat] Press Ctrl+C or close this window to stop.
echo.
echo [start.bat] NOTE: data/chain_v1.json contains plaintext miner private keys.
echo [start.bat] It is excluded by .gitignore - do NOT upload or publish it.
echo [start.bat] Public exports must strip the miners field (LICENSE-SCOPE.md sec.5).
echo.
"%PY%" server.py
