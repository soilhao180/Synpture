@echo off
setlocal

call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
cd /d C:\Users\59283\Desktop\MP4\third_party\whisper.cpp\build\CMakeFiles\4.2.3-msvc3\CompilerIdCUDA || exit /b 1
"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin\nvcc.exe" --keep --keep-dir tmp -v CMakeCUDACompilerId.cu -o test_cuda_id.exe
