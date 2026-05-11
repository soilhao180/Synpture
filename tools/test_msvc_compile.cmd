@echo off
setlocal

call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1

echo int main(void){return 0;} > tools\msvc_smoke_test.c
cl /nologo tools\msvc_smoke_test.c /Fe:tools\msvc_smoke_test.exe
