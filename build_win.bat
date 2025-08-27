@echo off
REM Build Windows GUI executable for data-scrapper

set "TESSERACT=C:\\Program Files\\Tesseract-OCR"

pyinstaller --onefile --windowed gui.py ^
    --add-data "trey.py;." ^
    --add-data "%TESSERACT%\\tesseract.exe;." ^
    --add-data "%TESSERACT%\\libtesseract-5.dll;." ^
    --add-data "%TESSERACT%\\liblept-5.dll;."
