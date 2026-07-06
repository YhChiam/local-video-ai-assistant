# Environment Notes

Date: 2026-07-06

## Host OS
- OS: Microsoft Windows 11 Pro
- Version: 10.0.26200
- Build: 26200

## Runtime Versions
- Python: 3.14.5
- Node.js: v24.15.0
- npm: 11.4.2
- .NET SDK: 10.0.301
- .NET runtimes:
  - Microsoft.AspNetCore.App 10.0.9
  - Microsoft.NETCore.App 6.0.16
  - Microsoft.NETCore.App 10.0.9
  - Microsoft.WindowsDesktop.App 10.0.9
- Rust: rustc 1.96.1 (31fca3adb 2026-06-26)
- Cargo: cargo 1.96.1 (356927216 2026-06-26)

## OCR and Vision Dependencies
- Tesseract: v5.5.0.20241111
- `TESSERACT_CMD`: C:\Users\Lauren\scoop\shims\tesseract.exe
- `TESSDATA_PREFIX`: C:\Users\Lauren\scoop\apps\tesseract-languages\current

## Project-Specific Notes
- C# launcher target framework: `net10.0`
- Launcher preferred backend path: `backend/dist/server/server.exe`
- Launcher fallback backend path: `backend/venv/Scripts/python.exe backend/server.py`
- Packaged backend build script: `backend/build_backend_exe.ps1`

## Main Run Workflow
1. Start backend (launcher):
   - `dotnet run --project c:\yhchiam\local-video-ai-assistant\launcher\BackendLauncher.csproj`
2. Start desktop app:
   - `cd c:\yhchiam\local-video-ai-assistant\frontend`
   - `npm run tauri dev`
