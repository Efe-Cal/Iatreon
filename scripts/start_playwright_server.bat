@echo off
setlocal

set IMAGE_NAME=iatreon-playwright
set IMAGE_TAG=1.59.0-noble
set CONTAINER_NAME=iatreon-playwright-server
set PLAYWRIGHT_PORT=3000

docker rm -f %CONTAINER_NAME% >nul 2>nul

docker run ^
  --name %CONTAINER_NAME% ^
  --rm ^
  --detach ^
  --init ^
  --ipc=host ^
  --add-host=hostmachine:host-gateway ^
  --publish %PLAYWRIGHT_PORT%:3000 ^
  --workdir /home/pwuser ^
  --user pwuser ^
  %IMAGE_NAME%:%IMAGE_TAG%

if errorlevel 1 exit /b %errorlevel%

echo Playwright server is starting on ws://127.0.0.1:%PLAYWRIGHT_PORT%/
echo If needed, set PLAYWRIGHT_WS_ENDPOINT=ws://127.0.0.1:%PLAYWRIGHT_PORT%/
