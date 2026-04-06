@echo off
REM ═══════════════════════════════════════════════════════════════════
REM  build.cmd — Build Docker images from project root context
REM
REM  Usage:  build.cmd              Build se-ce-tools only (default)
REM          build.cmd agent        Build agent only
REM          build.cmd all          Build both images
REM ═══════════════════════════════════════════════════════════════════

set SE_CE_TOOLS_IMAGE=rocketsoftware2030/se-ce-tools:12.6.0
set SE_AGENT_IMAGE=rocketsoftware2030/se-agent:1.0.0
pushd ..
set BUILD_CE=0
set BUILD_AGENT=0

if /i "%~1"=="agent" (
    set BUILD_AGENT=1
) else if /i "%~1"=="all" (
    set BUILD_CE=1
    set BUILD_AGENT=1
) else (
    set BUILD_CE=1
)

REM ── Build se-ce-tools ──────────────────────────────────────────────
if %BUILD_CE%==1 (
    echo.
    echo Building SE ContentEdge Tools [%SE_CE_TOOLS_IMAGE%]...
    docker build --network host -t %SE_CE_TOOLS_IMAGE% -f web_app/Dockerfile .
    if errorlevel 1 (
        echo ERROR: se-ce-tools build failed
        goto :usage
    )
    echo   OK: %SE_CE_TOOLS_IMAGE%
)

REM ── Build agent ────────────────────────────────────────────────────
if %BUILD_AGENT%==1 (
    echo.
    echo Building SE Agent [%SE_AGENT_IMAGE%]...
    docker build --network host -t %SE_AGENT_IMAGE% -f agent/Dockerfile .
    if errorlevel 1 (
        echo ERROR: se-agent build failed
        goto :usage
    )
    echo   OK: %SE_AGENT_IMAGE%
)

docker image prune -f >nul 2>&1

echo.
echo Build completed successfully.

set /p push_answer="Do you want to run 'docker push'? (y/N): "
if /i "%push_answer%"=="y" (
    docker login -u rocketsoftware2030 -p %DOCKER_REPO_PASSWORD%
    if %BUILD_CE%==1 docker push %SE_CE_TOOLS_IMAGE%
    if %BUILD_AGENT%==1 docker push %SE_AGENT_IMAGE%
)

:usage
echo.
echo ===================================================================
echo  build.cmd              Build se-ce-tools only (default)
echo  build.cmd agent        Build agent only
echo  build.cmd all          Build both images
echo -------------------------------------------------------------------
echo  deploy\start.cmd           Start se-ce-tools + workers
echo  deploy\start.cmd agent     Start everything (+ agent + qdrant + redis)
echo  deploy\stop.cmd            Stop all services
echo ===================================================================
popd