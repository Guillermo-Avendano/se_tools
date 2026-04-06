@echo off
setlocal
pushd "%~dp0"

for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    set "%%A=%%B"
)

if "%DOCKER_PROJECT_NAME%"=="" set "DOCKER_PROJECT_NAME=contentedge"

REM Usage: start.cmd          → starts se_ce_tools + workers only
REM        start.cmd agent    → starts everything including the AI agent
set "MODE=%~1"

if /i "%MODE%"=="agent" goto :start_agent
goto :start_default

:start_agent
echo Starting SE ContentEdge Tools + Workers + Agent...
docker compose -p %DOCKER_PROJECT_NAME% --profile agent up -d --force-recreate
goto :cleanup

:start_default
echo Starting SE ContentEdge Tools + Workers...
docker compose -p %DOCKER_PROJECT_NAME% up -d --force-recreate
goto :cleanup

:cleanup
popd
endlocal

