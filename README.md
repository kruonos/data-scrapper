# data-scrapper

## Prerequisites

- Python 3.10 or newer
- Install project dependencies: `pip install -r requirements.txt`
- Install [PyInstaller](https://pyinstaller.org/): `pip install pyinstaller`
- Install [Tesseract OCR for Windows](https://github.com/UB-Mannheim/tesseract/wiki) and note the installation directory (default `C:\\Program Files\\Tesseract-OCR`)

## Building the GUI executable on Windows

Run the build script from a command prompt:

```
build_win.bat
```

PyInstaller creates `dist\\gui.exe`. If Tesseract is installed in a custom location, edit `build_win.bat` and update the `TESSERACT` path accordingly.
