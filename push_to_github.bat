@echo off
chcp 65001 >nul
setlocal enableextensions
cd /d "%~dp0"

set "REPO_URL=https://github.com/lyh9712/stratumgenesis.git"
set "PAGES_URL=https://github.com/lyh9712/stratumgenesis/settings/pages"
set "SITE_URL=https://lyh9712.github.io/stratumgenesis/"
set "NEW_REPO=https://github.com/new?name=stratumgenesis"

if /I "%~1"=="--dry-run" goto :dryrun

echo ============================================================
echo   StratumGenesis - 一键推送到 GitHub 并开启 Pages
echo ============================================================
echo.
where git >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 git。请先安装 Git for Windows ^(https://git-scm.com/download/win^)，然后重新双击本文件。
  pause
  exit /b 1
)

echo ------------------------------------------------------------
echo  第 1 步：在 GitHub 上建一个空仓库
echo ------------------------------------------------------------
echo   现在会打开浏览器到「新建仓库」页面：
echo     %NEW_REPO%
echo.
echo   请确认：
echo     - 仓库名 = stratumgenesis
echo     - 可见性 = Public
echo     - 不要勾选 Add a README file / .gitignore / license（保持空仓库）
echo   建好后回到这个窗口，按任意键继续。
echo.
start "" "%NEW_REPO%"
pause

echo.
echo ------------------------------------------------------------
echo  第 2 步：推送代码（会弹一次 GitHub 登录窗口）
echo ------------------------------------------------------------
git remote remove origin >nul 2>nul
git remote add origin "%REPO_URL%"
git branch -M main
echo   正在推送……如果弹出浏览器登录窗口，请用你的 GitHub 账号登录并授权（只需一次）。
echo.
git push -u origin main
if errorlevel 1 (
  echo.
  echo [错误] 推送失败。常见原因：
  echo   1^) 仓库还没建好，或名字不是 stratumgenesis
  echo   2^) 登录窗口被关掉了（重新双击本文件再试一次即可）
  echo   3^) 网络问题
  pause
  exit /b 1
)

echo.
echo ------------------------------------------------------------
echo  第 3 步：开启 GitHub Pages（只读展馆上线）
echo ------------------------------------------------------------
echo   现在会打开 Pages 设置页面：
echo     %PAGES_URL%
echo.
echo   请这样设置：
echo     Source = Deploy from a branch
echo     Branch = main      Folder = / (root)
echo     然后点 Save
echo.
start "" "%PAGES_URL%"
echo.
echo ============================================================
echo  完成！约 1 分钟后，任何人打开下面这个链接就能看到地层剖面：
echo    %SITE_URL%
echo.
echo  想让人「打开就能提案」：按 web/README.md 第 4 节把 vendored 运行时放入
echo  web/vendor/ 后再次推送（14MB，我已排除在 git 之外以免仓库膨胀）。
echo ============================================================
pause
exit /b 0

:dryrun
echo [dry-run] remote : %REPO_URL%
echo [dry-run] pages  : %PAGES_URL%
echo [dry-run] site   : %SITE_URL%
echo [dry-run] newrepo: %NEW_REPO%
git log --oneline -1
git status --porcelain | findstr /r "." >nul
if errorlevel 1 (echo [dry-run] working tree CLEAN) else (echo [dry-run] WARNING: working tree NOT clean)
git remote -v
echo [dry-run] no remote change, no push.
exit /b 0
