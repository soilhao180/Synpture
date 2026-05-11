@echo off
setlocal

set "DIR=C:\Users\59283\Desktop\MP4\third_party\whisper.cpp-hybrid\Release"
set "MODEL=C:\Users\59283\Desktop\MP4\models\ggml-large-v3-turbo-q5_0.bin"
set "AUDIO=C:\Users\59283\Desktop\MP4\output\3_20260424_120354\audio_local_chunk_05.wav"
set "OUT=C:\Users\59283\Desktop\MP4\output\whispercpp_smoke_hybrid"

set "PATH=%DIR%;%PATH%"
cd /d %DIR% || exit /b 1
whisper-cli.exe -m "%MODEL%" -f "%AUDIO%" -l zh -ojf -of "%OUT%" > "%OUT%.stdout.log" 2> "%OUT%.stderr.log"
echo EXITCODE=%ERRORLEVEL%
exit /b %ERRORLEVEL%
