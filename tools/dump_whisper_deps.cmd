@echo off
setlocal

call "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
dumpbin /dependents "C:\Users\59283\Desktop\MP4\third_party\whisper.cpp-prebuilt\Release\whisper-cli.exe"
dumpbin /dependents "C:\Users\59283\Desktop\MP4\third_party\whisper.cpp-prebuilt\Release\whisper.dll"
dumpbin /dependents "C:\Users\59283\Desktop\MP4\third_party\whisper.cpp-prebuilt\Release\ggml-cuda.dll"
