@echo off
setlocal

call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
where cl || exit /b 1
where ninja
where nmake
echo VSCMD_ARG_TGT_ARCH=%VSCMD_ARG_TGT_ARCH%
echo VCINSTALLDIR=%VCINSTALLDIR%
