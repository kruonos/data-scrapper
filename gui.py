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
    messagebox,
)

try:
    from tqdm import tqdm_gui as progress_cls
except ModuleNotFoundError:
    from tqdm import tqdm as progress_cls
else:  # ensure matplotlib is available for the GUI variant
    try:  # pragma: no cover - simple import check
        import matplotlib  # noqa: F401
    except ModuleNotFoundError:  # pragma: no cover
        from tqdm import tqdm as progress_cls

from trey import rename_pdfs


def run_rename(input_path: str, dpi: int, pages: int, run_btn: Button | None = None) -> None:
    if not input_path:
        if run_btn is not None:
            run_btn.config(state="normal")
        return
    out_zip = Path(input_path).with_name(
        Path(input_path).stem + "_renomeados.zip"
    )
    try:
        rename_pdfs(
            input_path,
            out_zip,
            dpi=dpi,
            pages=pages,
            jobs="auto",
            progress_cls=progress_cls,
        )
    except Exception as exc:  # pylint: disable=broad-except
        messagebox.showerror("Erro", f"Falha ao renomear PDFs: {exc}")
    finally:
        if run_btn is not None:
            run_btn.config(state="normal")


def main() -> None:
    root = Tk()
    root.title("Renomeador de PDF")
    root.configure(bg="black")

    input_var = StringVar()
    dpi_var = IntVar(value=300)
    pages_var = StringVar(value="2")

    def select_zip() -> None:
        filename = filedialog.askopenfilename(
            filetypes=[("Arquivos ZIP", "*.zip")]
        )
        if filename:
            input_var.set(filename)

    def start() -> None:
        try:
            pg = int(pages_var.get()) if pages_var.get() else 2
        except ValueError:
            pg = 2
        run_btn.config(state="disabled")
        threading.Thread(
            target=run_rename,
            args=(input_var.get(), dpi_var.get(), pg, run_btn),
            daemon=True,
        ).start()

    Button(
        root,
        text="Selecionar ZIP",
        command=select_zip,
        bg="black",
        fg="white",
        activebackground="gray20",
        activeforeground="white",
    ).grid(
        row=0, column=0, padx=5, pady=5, sticky="w"
    )
    Label(
        root,
        textvariable=input_var,
        width=40,
        anchor="w",
        bg="black",
        fg="white",
    ).grid(
        row=0, column=1, padx=5, pady=5
    )

    Label(root, text="DPI:", bg="black", fg="white").grid(row=1, column=0, sticky="w")
    for i, d in enumerate([150, 300, 600]):
        Radiobutton(
            root,
            text=str(d),
            variable=dpi_var,
            value=d,
            bg="black",
            fg="white",
            activebackground="gray20",
            activeforeground="white",
        ).grid(
            row=1, column=i + 1, sticky="w"
        )

    Label(root, text="Páginas:", bg="black", fg="white").grid(row=2, column=0, sticky="w")
    Entry(
        root,
        textvariable=pages_var,
        width=5,
        bg="black",
        fg="white",
        insertbackground="white",
    ).grid(row=2, column=1, sticky="w")

    run_btn = Button(
        root,
        text="Executar",
        command=start,
        bg="black",
        fg="white",
        activebackground="gray20",
        activeforeground="white",
    )
    run_btn.grid(
        row=3, column=0, columnspan=2, pady=10
    )

    root.mainloop()


if __name__ == "__main__":
    main()
