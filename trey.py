#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
renomear_002025_ocr_v5.py — robusto p/ casos YJ* (mais ROI, normalização OCR)

Melhorias:
- **ROIs múltiplas** no topo: esquerda, centro e direita (cobre deslocamento do código).
- **Normalização** de confusões comuns do OCR (O→0, I/l→1, S→5, B→8, Z→2, g→9, G→6, Q/D→0).
- **Aceita segmentado** com espaços/traços: captura "002025 0501-001160 4209" e compacta para 20 dígitos.
- **Paralelo** (multiprocessing) + **tqdm**.
- **Páginas** configuráveis (padrão 2).

Requisitos:
  - Tesseract OCR instalado (binário no PATH)
  - pip install pytesseract Pillow PyMuPDF tqdm

Uso típico:
  python3 renomear_002025_ocr_v5.py \
    --input ./digital.zip \
    --saida ./digital_renomeados.zip \
    --dpi 300 \
    --pages 2 \
    --jobs auto
"""

import os, re, io, sys, csv, zipfile, shutil, argparse, multiprocessing as mp
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any
from tqdm import tqdm

# ====== Config ======

# pattern permite separadores no meio; depois compactamos só dígitos
PAT_SEGMENTED = re.compile(r"0\s*0\s*2\s*0\s*2\s*5[\s\-\./]*([\s\d\-\./]{10,40})", re.IGNORECASE)
PAT_EXACT20   = re.compile(r"^(002025\d{14})$")
DIGIT_ONLY    = re.compile(r"\D+")

NORM_TABLE = str.maketrans({
    'O':'0','o':'0',
    'I':'1','l':'1',
    'S':'5',
    'B':'8',
    'Z':'2',
    'g':'9','G':'6',
    'Q':'0','D':'0'
})

@dataclass
class ROI:
    x0: float
    y0: float
    x1: float
    y1: float

# ROIs padrão: três blocos no terço superior da página
DEFAULT_ROIS = [
    ROI(0.00, 0.00, 0.50, 0.28),  # esquerda
    ROI(0.25, 0.00, 0.75, 0.30),  # centro
    ROI(0.50, 0.00, 1.00, 0.32),  # direita
]

# predefinições de DPI para facilitar a escolha no CLI/GUI
DPI_PRESETS: Dict[str, int] = {
    "fast": 150,
    "balanced": 300,
    "quality": 600,
}

def normalize_ocr(s: str) -> str:
    return s.translate(NORM_TABLE)

def only_digits(s: str) -> str:
    return DIGIT_ONLY.sub("", s)

def lines_from_roi(page, roi: ROI, dpi: int = 300) -> List[str]:
    import fitz, pytesseract
    from PIL import Image
    w, h = page.rect.width, page.rect.height
    rect = fitz.Rect(w*roi.x0, h*roi.y0, w*roi.x1, h*roi.y1)
    pm = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False, clip=rect)
    img = Image.open(io.BytesIO(pm.tobytes("png")))
    cfg = "--psm 6 -c tessedit_char_whitelist=0123456789OIlSBZgGQD"
    txt = pytesseract.image_to_string(img, lang="eng", config=cfg) or ""
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]

def try_extract_code_from_lines(lines: List[str]) -> Optional[str]:
    # 1) por linha exata
    for ln in lines:
        d = only_digits(ln)
        if PAT_EXACT20.match(d):
            return d
    # 2) por linha normalizada
    for ln in lines:
        d = only_digits(normalize_ocr(ln))
        if PAT_EXACT20.match(d):
            return d
    # 3) buscar padrão segmentado no bloco todo
    blob = "\n".join(lines)
    # tentar também normalizado
    for txt in (blob, normalize_ocr(blob)):
        m = PAT_SEGMENTED.search(txt)
        if m:
            cand = only_digits("002025" + m.group(1))
            if len(cand) >= 20 and cand.startswith("002025"):
                # pegue exatamente 20
                return cand[:20]
    return None

def find_code(pdf_path: Path, dpi: int = 300, pages: int = 2) -> Tuple[Optional[str], str]:
    import fitz
    with fitz.open(str(pdf_path)) as doc:
        lim = min(pages, len(doc))
        # 1) ROIs múltiplas nas páginas
        for pidx in range(lim):
            page = doc[pidx]
            for roi in DEFAULT_ROIS:
                lines = lines_from_roi(page, roi, dpi=dpi)
                code = try_extract_code_from_lines(lines)
                if code:
                    return code, f"ROI[{DEFAULT_ROIS.index(roi)}] p{pidx+1} {dpi}dpi"
        # 2) fallback: página inteira p1 (se existir)
        if len(doc) >= 1:
            page = doc[0]
            full = ROI(0,0,1,1)
            lines = lines_from_roi(page, full, dpi=dpi)
            code = try_extract_code_from_lines(lines)
            if code:
                return code, f"FULL p1 {dpi}dpi"
    return None, "NÃO ENCONTRADO"

def zip_dir(dir_path: Path, zip_out: Path) -> None:
    with zipfile.ZipFile(str(zip_out), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(dir_path):
            for f in files:
                p = Path(root) / f
                zf.write(p, arcname=p.name)

def worker(task):
    pdf = Path(task["pdf"])
    dpi = task["dpi"]
    pages = task["pages"]
    try:
        code, criterio = find_code(pdf, dpi=dpi, pages=pages)
    except Exception as e:
        code, criterio = None, f"ERRO OCR: {e}"
    new_name = f"{(code if code else pdf.stem)}.PDF"
    return {"src": str(pdf), "original": pdf.name, "novo": new_name, "criterio": criterio, "codigo": code or ""}

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Renomeia PDFs para 002025************** (20 dígitos) — robusto para variações.")
    ap.add_argument("--input", required=True, help="Pasta com PDFs ou .zip")
    ap.add_argument("--saida", required=True, help="ZIP de saída")
    ap.add_argument("--dpi", type=int, default=300, help="DPI para OCR (padrão 300)")
    ap.add_argument("--dpi-preset", choices=sorted(DPI_PRESETS.keys()), help="Preset de DPI (sobrepõe --dpi)")
    ap.add_argument("--pages", type=int, default=2, help="Páginas a tentar (padrão 2)")
    ap.add_argument("--jobs", default="auto", help="processos: 'auto' ou número")
    return ap.parse_args(argv)


def process(args):
    if args.dpi_preset:
        args.dpi = DPI_PRESETS[args.dpi_preset]

    # jobs
    jobs = max(1, (os.cpu_count() or 1)) if args.jobs == "auto" else max(1, int(args.jobs))

    src = Path(args.input)
    out_zip = Path(args.saida)
    work = Path.cwd() / "_ren_002025_tmp"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # preparar fonte
    src_dir = work / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    if src.is_file() and src.suffix.lower() == ".zip":
        with zipfile.ZipFile(str(src), "r") as zf:
            zf.extractall(src_dir)
    elif src.is_dir():
        for p in src.rglob("*.pdf"):
            shutil.copy2(p, src_dir / p.name)
        for p in src.rglob("*.PDF"):
            shutil.copy2(p, src_dir / p.name)
    else:
        print("Entrada inválida.")
        sys.exit(2)

    out_dir = work / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    mapa_csv = out_zip.with_suffix(".csv")

    pdfs = sorted([p for p in src_dir.rglob("*") if p.suffix.lower() == ".pdf"])
    if not pdfs:
        print("Nenhum PDF encontrado.")
        sys.exit(3)

    tasks = [{"pdf": str(p), "dpi": int(args.dpi), "pages": int(args.pages)} for p in pdfs]

    rows = []
    with mp.Pool(processes=jobs) as pool:
        for res in tqdm(pool.imap_unordered(worker, tasks, chunksize=2), total=len(tasks), desc=f"Processando ({jobs} proc.)", unit="pdf"):
            rows.append(res)
            shutil.copy2(res["src"], out_dir / res["novo"])

    zip_dir(out_dir, out_zip)
    with open(mapa_csv, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["original","novo_nome","criterio","codigo_detectado"])
        w.writeheader()
        for r in rows:
            w.writerow({"original": r["original"], "novo_nome": r["novo"], "criterio": r["criterio"], "codigo_detectado": r["codigo"]})

    print("OK")
    print(f"ZIP: {out_zip}")
    print(f"MAPA: {mapa_csv}")


def main(argv=None):
    args = parse_args(argv)
    process(args)


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("Renomear 002025 OCR")

    input_var = tk.StringVar()
    output_var = tk.StringVar()
    pages_var = tk.IntVar(value=2)
    jobs_var = tk.StringVar(value="auto")
    dpi_preset_var = tk.StringVar(value="balanced")

    def browse_input():
        path = filedialog.askopenfilename(title="Entrada (pasta ou zip)")
        if path:
            input_var.set(path)

    def browse_output():
        path = filedialog.asksaveasfilename(title="ZIP de saída", defaultextension=".zip")
        if path:
            output_var.set(path)

    def start():
        if not input_var.get() or not output_var.get():
            messagebox.showerror("Erro", "Informe entrada e saída")
            return
        args = argparse.Namespace(
            input=input_var.get(),
            saida=output_var.get(),
            dpi=DPI_PRESETS[dpi_preset_var.get()],
            dpi_preset=dpi_preset_var.get(),
            pages=pages_var.get(),
            jobs=jobs_var.get(),
        )
        try:
            process(args)
            messagebox.showinfo("Concluído", "Processamento finalizado.")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    tk.Label(root, text="Entrada:").grid(row=0, column=0, sticky="e")
    tk.Entry(root, textvariable=input_var, width=40).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(root, text="...", command=browse_input).grid(row=0, column=2, padx=5)

    tk.Label(root, text="Saída ZIP:").grid(row=1, column=0, sticky="e")
    tk.Entry(root, textvariable=output_var, width=40).grid(row=1, column=1, padx=5, pady=5)
    tk.Button(root, text="...", command=browse_output).grid(row=1, column=2, padx=5)

    tk.Label(root, text="Preset DPI:").grid(row=2, column=0, sticky="e")
    tk.OptionMenu(root, dpi_preset_var, *DPI_PRESETS.keys()).grid(row=2, column=1, sticky="w", padx=5, pady=5)

    tk.Label(root, text="Páginas:").grid(row=3, column=0, sticky="e")
    tk.Entry(root, textvariable=pages_var, width=5).grid(row=3, column=1, sticky="w", padx=5, pady=5)

    tk.Label(root, text="Jobs:").grid(row=4, column=0, sticky="e")
    tk.Entry(root, textvariable=jobs_var, width=5).grid(row=4, column=1, sticky="w", padx=5, pady=5)

    tk.Button(root, text="Iniciar", command=start).grid(row=5, column=0, columnspan=3, pady=10)

    root.mainloop()

if __name__ == "__main__":
    main()
