"""Simple Tkinter GUI for PDF renaming using ``rename_pdfs``."""

import threading
from pathlib import Path
from tkinter import (
    Tk,
    Button,
    Label,
    Radiobutton,
    IntVar,
    StringVar,
    Entry,
    filedialog,
)

from tqdm import tqdm_gui

from trey import rename_pdfs


def run_rename(input_path: str, dpi: int, pages: int) -> None:
    if not input_path:
        return
    out_zip = Path(input_path).with_name(
        Path(input_path).stem + "_renomeados.zip"
    )
    rename_pdfs(
        input_path,
        out_zip,
        dpi=dpi,
        pages=pages,
        jobs="auto",
        progress_cls=tqdm_gui,
    )


def main() -> None:
    root = Tk()
    root.title("PDF Renamer")

    input_var = StringVar()
    dpi_var = IntVar(value=300)
    pages_var = StringVar(value="2")

    def select_zip() -> None:
        filename = filedialog.askopenfilename(
            filetypes=[("ZIP files", "*.zip")]
        )
        if filename:
            input_var.set(filename)

    def start() -> None:
        try:
            pg = int(pages_var.get()) if pages_var.get() else 2
        except ValueError:
            pg = 2
        threading.Thread(
            target=run_rename,
            args=(input_var.get(), dpi_var.get(), pg),
            daemon=True,
        ).start()

    Button(root, text="Select ZIP", command=select_zip).grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    Label(root, textvariable=input_var, width=40, anchor="w").grid(
        row=0, column=1, padx=5, pady=5
    )

    Label(root, text="DPI:").grid(row=1, column=0, sticky="w")
    for i, d in enumerate([150, 300, 600]):
        Radiobutton(root, text=str(d), variable=dpi_var, value=d).grid(
            row=1, column=i + 1, sticky="w"
        )

    Label(root, text="Pages:").grid(row=2, column=0, sticky="w")
    Entry(root, textvariable=pages_var, width=5).grid(row=2, column=1, sticky="w")

    Button(root, text="Run", command=start).grid(
        row=3, column=0, columnspan=2, pady=10
    )

    root.mainloop()


if __name__ == "__main__":
    main()

