@echo off
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do (
    set "%%A=%%B"
)

if "%DOCKER_PROJECT_NAME%"=="" set "DOCKER_PROJECT_NAME=contentedge"

docker compose -p %DOCKER_PROJECT_NAME% --profile agent down

