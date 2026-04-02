@echo off
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do (
	set "%%A=%%B"
)

if "%DOCKER_PROJECT_NAME%"=="" set "DOCKER_PROJECT_NAME=contentedge"

docker logs %DOCKER_PROJECT_NAME%-agent-api-1 --tail 30 -f