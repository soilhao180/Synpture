@echo off
setlocal

set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE_EXE=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"

call "%VCVARS%" || exit /b 1
set "VSLANG=1033"

"%CMAKE_EXE%" -S third_party\whisper.cpp -B third_party\whisper.cpp\build-core -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_OPENMP=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 || exit /b 1
"%CMAKE_EXE%" --build third_party\whisper.cpp\build-core --config Release -j 8 || exit /b 1
