@echo off
setlocal

set IMAGE_NAME=iatreon-playwright
set IMAGE_TAG=1.59.0-noble

docker build -t %IMAGE_NAME%:%IMAGE_TAG% -f docker\playwright-server\Dockerfile .
if errorlevel 1 exit /b %errorlevel%

echo Built %IMAGE_NAME%:%IMAGE_TAG%
