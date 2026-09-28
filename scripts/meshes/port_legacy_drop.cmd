@echo off
rem Drop Battlezone 1.5 .vdf/.sdf/.odf/.geo/.map files on this script to port
rem them to Redux: each one converts into a <name>_redux folder beside itself.
rem Stock parts and textures come from the detected Battlezone 1.5 install.
rem
rem Extra options (like BZRModelPorter's headlights/pilot_scope .bat files):
rem put them in port_legacy_drop.args beside this script, one per line, e.g.
rem     --scope-type
rem     attached
rem or copy this script and add them to PORT_FLAGS below.
rem All options: python -m bztoolbox meshes port-legacy --help
setlocal
set "PORT_FLAGS="
set "ARGS_FILE=%~dp0port_legacy_drop.args"
set "PYTHONPATH=%~dp0..\..;%PYTHONPATH%"
if exist "%ARGS_FILE%" (
    python -m bztoolbox meshes port-legacy --game15 auto %PORT_FLAGS% "@%ARGS_FILE%" %*
) else (
    python -m bztoolbox meshes port-legacy --game15 auto %PORT_FLAGS% %*
)
echo.
pause
