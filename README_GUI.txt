CLIPPER AGENT GUI — V1

1. Copy clipper_gui.py ke:
   C:\Clipper Agent\clipper\

2. Install PySide6 ke virtualenv project:
   .\.venv\Scripts\python.exe -m pip install PySide6

3. Jalankan:
   .\.venv\Scripts\python.exe .\clipper_gui.py

4. Atau:
   .\run_clipper_gui.ps1

GUI V1:
- URL YouTube input + Paste
- Jalankan full pipeline via main.py
- Stage 1 / 2 / 4 / 5 status cards
- Activity log realtime
- Gemini API status
- Stage 5 placeholder page untuk Design/Layout/Subtitle/Render
- Settings/History shell

Catatan:
- GUI tidak menggantikan main.py.
- GUI menjalankan main.py menggunakan .venv yang sama.
- Subtitle tetap tidak diubah.
- Hook line spacing -50 tetap menjadi rule Stage 5.
