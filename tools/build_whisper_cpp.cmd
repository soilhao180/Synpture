@echo off
setlocal

set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE_EXE=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
set "BUILD_DIR=third_party\whisper.cpp\build-cuda"

call "%VCVARS%" || exit /b 1
set "VSLANG=1033"

set "CUDA_FLAGS=-allow-unsupported-compiler"

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"

"%CMAKE_EXE%" -S third_party\whisper.cpp -B "%BUILD_DIR%" -G "Ninja" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DGGML_CUDA=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_CUDA_FLAGS="%CUDA_FLAGS%" || exit /b 1
"%CMAKE_EXE%" --build "%BUILD_DIR%" --config Release -j 8 || exit /b 1
