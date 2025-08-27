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

import os, re, io, sys, csv, zipfile, shutil, argparse, tempfile, multiprocessing as mp, logging, time
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple, List, Optional, Callable, Iterable, Union
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
DPI_PRESETS: dict[str, int] = {
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
    if sys.platform.startswith("win"):
        tesseract_cmd = Path(r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
        if tesseract_cmd.exists():
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)
    w, h = page.rect.width, page.rect.height
    rect = fitz.Rect(w*roi.x0, h*roi.y0, w*roi.x1, h*roi.y1)
    pm = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False, clip=rect)
    with Image.open(io.BytesIO(pm.tobytes("png"))) as img:
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
    with zipfile.ZipFile(zip_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(dir_path):
            for f in files:
                p = Path(root) / f
                zf.write(p, arcname=p.relative_to(dir_path))

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


def rename_pdfs(
    input_path: Union[str, Path],
    output_zip: Union[str, Path],
    *,
    dpi: int = 300,
    pages: int = 2,
    jobs: Union[str, int] = "auto",
    progress_cls: Callable[[Iterable], Iterable] = tqdm,
) -> Tuple[Path, Path]:
    n_jobs = max(1, (os.cpu_count() or 1)) if jobs == "auto" else max(1, int(jobs))

    src = Path(input_path)
    out_zip = Path(output_zip)

    with tempfile.TemporaryDirectory() as workdir:
        work = Path(workdir)

        # preparar fonte
        src_dir = work / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        if src.is_file() and src.suffix.lower() == ".zip":
            with zipfile.ZipFile(str(src), "r") as zf:
                zf.extractall(src_dir)
        elif src.is_dir():
            for p in src.rglob("*"):
                if p.suffix.lower() == ".pdf":
                    rel = p.relative_to(src)
                    dest = src_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        logging.warning("PDF duplicado ignorado: %s", dest)
                        continue
                    shutil.copy2(p, dest)
        else:
            raise ValueError("Entrada inválida.")

        out_dir = work / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        mapa_csv = out_zip.with_suffix(".csv")

        pdfs = sorted([p for p in src_dir.rglob("*") if p.suffix.lower() == ".pdf"])
        if not pdfs:
            raise ValueError("Nenhum PDF encontrado.")

        tasks = [{"pdf": str(p), "dpi": int(dpi), "pages": int(pages)} for p in pdfs]

        rows = []
        with mp.Pool(processes=n_jobs) as pool:
            last_time = time.perf_counter()
            for res in progress_cls(
                pool.imap_unordered(worker, tasks, chunksize=2),
                total=len(tasks),
                desc=f"Processando ({n_jobs} proc.)",
                unit="pdf",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
            ):
                now = time.perf_counter()
                logging.debug("Concluído %s em %.2fs", res["src"], now - last_time)
                last_time = now
                rows.append(res)
                rel_parent = Path(res["src"]).relative_to(src_dir).parent
                dest = out_dir / rel_parent / res["novo"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    logging.warning("Nome duplicado na saída, pulando: %s", dest)
                    continue
                shutil.copy2(Path(res["src"]), dest)

        zip_dir(out_dir, out_zip)
        with open(mapa_csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=["original", "novo_nome", "criterio", "codigo_detectado"],
            )
            w.writeheader()
            for r in rows:
                w.writerow(
                    {
                        "original": r["original"],
                        "novo_nome": r["novo"],
                        "criterio": r["criterio"],
                        "codigo_detectado": r["codigo"],
                    }
                )

        return out_zip, mapa_csv


def main():
    ap = argparse.ArgumentParser(
        description="Renomeia PDFs para 002025************** (20 dígitos) — robusto para variações."
    )
    ap.add_argument("--input", required=True, help="Pasta com PDFs ou .zip")
    ap.add_argument("--saida", required=True, help="ZIP de saída")
    ap.add_argument("--dpi", type=int, default=300, help="DPI para OCR (padrão 300)")
    ap.add_argument("--pages", type=int, default=2, help="Páginas a tentar (padrão 2)")
    ap.add_argument("--jobs", default="auto", help="processos: 'auto' ou número")
    args = ap.parse_args()

    try:
        out_zip, mapa_csv = rename_pdfs(
            args.input,
            args.saida,
            dpi=args.dpi,
            pages=args.pages,
            jobs=args.jobs,
        )
    except ValueError as e:
        print(str(e))
        sys.exit(2)

    print("OK")
    print(f"ZIP: {out_zip}")
    print(f"MAPA: {mapa_csv}")

if __name__ == "__main__":
    mp.freeze_support()
    main()
