@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "install_status=%ERRORLEVEL%"

echo.
if not "%install_status%"=="0" echo Cai dat that bai. Xem loi o phia tren.
echo Nhan phim bat ky de dong cua so nay...
pause >nul

exit /b %install_status%
