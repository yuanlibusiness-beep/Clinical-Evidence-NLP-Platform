@echo off
REM =====================================================================
REM  Push this project to a GitHub repository (Windows).
REM
REM  Before running:
REM    1. Install Git for Windows:  https://git-scm.com/download/win
REM    2. Create an EMPTY repository on GitHub - no README, no .gitignore,
REM       no licence. This project already has all three, and pre-filling
REM       them on GitHub's side creates a conflict on the first push.
REM    3. Copy its URL, e.g.
REM       https://github.com/your-name/clinical-evidence-nlp-platform.git
REM
REM  Then double-click this file, or run it from the project root.
REM
REM  Your credentials are never written to disk by this script. Git for
REM  Windows opens its own browser sign-in the first time you push.
REM =====================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo.
echo ==========================================================
echo   Clinical Evidence NLP Platform  -  push to GitHub
echo ==========================================================
echo   Working directory: %CD%
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git is not installed, or not on PATH.
  echo         Install it from https://git-scm.com/download/win
  echo         then close and reopen this window and try again.
  pause
  exit /b 1
)

REM ---- .env must never be committed ----------------------------------
if exist ".env" (
  echo [NOTE] A .env file exists. It is listed in .gitignore and will NOT
  echo        be uploaded. Nothing to do - just so you know.
  echo.
)

REM ---- identity -------------------------------------------------------
for /f "delims=" %%i in ('git config --global user.name 2^>nul') do set GITNAME=%%i
if "!GITNAME!"=="" (
  set /p GITNAME=Your name for commits (e.g. Yuan Li):
  git config --global user.name "!GITNAME!"
)

for /f "delims=" %%i in ('git config --global user.email 2^>nul') do set GITMAIL=%%i
if "!GITMAIL!"=="" (
  set /p GITMAIL=Your GitHub email:
  git config --global user.email "!GITMAIL!"
)

REM ---- repository -----------------------------------------------------
if not exist ".git" (
  echo Initialising a new git repository...
  git init
  if errorlevel 1 goto :failed
)

git branch -M main

set /p REPOURL=Paste your empty GitHub repository URL:
if "!REPOURL!"=="" (
  echo [ERROR] No URL given. Nothing was pushed.
  pause
  exit /b 1
)

git remote remove origin >nul 2>nul
git remote add origin "!REPOURL!"
if errorlevel 1 goto :failed

REM ---- commit ---------------------------------------------------------
echo.
echo Staging files...
git add -A
if errorlevel 1 goto :failed

git diff --cached --quiet
if errorlevel 1 (
  git commit -m "feat: clinical evidence NLP platform - source-grounded extraction with abstention and evaluation"
  if errorlevel 1 goto :failed
) else (
  echo Nothing new to commit; pushing the existing history.
)

REM ---- push -----------------------------------------------------------
echo.
echo Pushing to !REPOURL! ...
echo A browser window may open for you to sign in to GitHub.
git push -u origin main
if errorlevel 1 goto :pushfailed

echo.
echo ==========================================================
echo   Done. Your repository is at:
echo   !REPOURL!
echo ==========================================================
echo.
echo   Next: on GitHub, open Settings - General - and set the
echo   description and topics, then pin the repo to your profile.
echo.
pause
exit /b 0

:pushfailed
echo.
echo [ERROR] The push failed. The two usual causes:
echo.
echo   1. The repository is not empty (you ticked "Add a README").
echo      Fix: delete that repo and create a new EMPTY one, or run
echo           git pull --rebase origin main
echo      and then run this script again.
echo.
echo   2. Authentication was cancelled or rejected.
echo      Fix: run  git push -u origin main  by hand and complete the
echo           browser sign-in.
echo.
pause
exit /b 1

:failed
echo.
echo [ERROR] A git command failed. Scroll up for the message.
pause
exit /b 1
