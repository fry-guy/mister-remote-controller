@echo off
echo Starting MiSTer Keyboard...
start "" "%~dp0mister-keyboard.html"
python "%~dp0ws-to-tcp.py"