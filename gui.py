"""Simple Tkinter GUI for PDF renaming using ``rename_pdfs``."""

import threading
import queue
import time
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
from tkinter import ttk

from trey import rename_pdfs

progress_queue: "queue.Queue[tuple[int, int, float, float] | None]" = queue.Queue()


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def gui_progress(
    iterable, *, total: int = 0, desc: str | None = None, unit: str | None = None, bar_format: str | None = None
):
    start = time.perf_counter()
    for idx, item in enumerate(iterable, 1):
        yield item
        elapsed = time.perf_counter() - start
        remaining = (elapsed / idx) * (total - idx) if idx else 0.0
        progress_queue.put((idx, total, elapsed, remaining))
    progress_queue.put(None)


def run_rename(input_path: str, dpi: int, pages: int, run_btn: Button | None = None) -> None:
    if not input_path:
        if run_btn is not None:
            run_btn.config(state="normal")
        return
    out_zip = Path(input_path).with_name(Path(input_path).stem + "_renomeados.zip")
    try:
        rename_pdfs(
            input_path,
            out_zip,
            dpi=dpi,
            pages=pages,
            jobs="auto",
            progress_cls=gui_progress,
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
        filename = filedialog.askopenfilename(filetypes=[("Arquivos ZIP", "*.zip")])
        if filename:
            input_var.set(filename)

    def start() -> None:
        try:
            pg = int(pages_var.get()) if pages_var.get() else 2
        except ValueError:
            pg = 2
        while not progress_queue.empty():
            progress_queue.get_nowait()
        progress_bar.config(value=0, maximum=1)
        prog_lbl.config(text="")
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
    ).grid(row=0, column=0, padx=5, pady=5, sticky="w")

    Label(
        root,
        textvariable=input_var,
        width=40,
        anchor="w",
        bg="black",
        fg="white",
    ).grid(row=0, column=1, padx=5, pady=5)

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
        ).grid(row=1, column=i + 1, sticky="w")

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
    run_btn.grid(row=3, column=0, columnspan=2, pady=10)

    progress_bar = ttk.Progressbar(root, length=300)
    progress_bar.grid(row=4, column=0, columnspan=2, padx=5, pady=(0, 5))

    prog_lbl = Label(root, text="", bg="black", fg="white")
    prog_lbl.grid(row=5, column=0, columnspan=2, pady=(0, 5))

    def update_progress() -> None:
        try:
            data = progress_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            if data is None:
                progress_bar.config(value=0)
                prog_lbl.config(text="")
            else:
                idx, total, elapsed, remaining = data
                progress_bar.config(maximum=total, value=idx)
                prog_lbl.config(
                    text=f"{idx}/{total} [{_format_time(elapsed)}<{_format_time(remaining)}]"
                )
        root.after(100, update_progress)

    update_progress()
    root.mainloop()


if __name__ == "__main__":
    main()
