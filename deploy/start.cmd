@echo off
setlocal
pushd "%~dp0"

for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    set "%%A=%%B"
)

if "%DOCKER_PROJECT_NAME%"=="" set "DOCKER_PROJECT_NAME=contentedge"

REM Usage: start.cmd          → starts se_ce_tools + workers only
REM        start.cmd agent    → starts everything including the AI agent
REM        start.cmd llama_cpp→ starts optional llama.cpp services only
REM        start.cmd all      → starts all services, including agent + llama.cpp
set "MODE=%~1"

if /i "%MODE%"=="agent" goto :start_agent
if /i "%MODE%"=="llama_cpp" goto :start_llama
if /i "%MODE%"=="all" goto :start_all
goto :start_default

:start_agent
echo Starting SE ContentEdge Tools + Workers + Agent...
docker compose -p %DOCKER_PROJECT_NAME% --profile agent up -d --force-recreate
goto :cleanup

:start_llama
echo Starting llama.cpp optional services...
docker compose -p %DOCKER_PROJECT_NAME% --profile llama_cpp up -d --force-recreate llama-cpp-models-init llama-cpp-chat llama-cpp-embed
goto :cleanup

:start_all
echo Starting all services (Tools + Workers + Agent + llama.cpp)...
docker compose -p %DOCKER_PROJECT_NAME% --profile agent --profile llama_cpp up -d --force-recreate
goto :cleanup

:start_default
echo Starting SE ContentEdge Tools + Workers...
docker compose -p %DOCKER_PROJECT_NAME% up -d --force-recreate
goto :cleanup

:cleanup
popd
endlocal

