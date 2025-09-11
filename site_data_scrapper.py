# importações para o script funcionar
import os, re, time, requests
import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, SessionNotCreatedException
from webdriver_manager.chrome import ChromeDriverManager

# ========= Configuração inicial =========
HOME = Path.home()
DOWNLOAD_DIR = str(HOME / "SGD-BAIXADOS")
PROFILE_DIR = str(HOME / r"AppData/Local/Google/Chrome/User Data/Default")
TARGET       = "https://sgd.correios.com.br/sgd/app/"
MIN_BYTES_OK = 1024   # arquivos <1KB costumam ser bloqueio/HTML de login
WINDOW_SIZE  = os.environ.get("CHROME_WINDOW_SIZE", "1280,720")
HTML_ACTION_DELAY = 0.6

driver = None
wait = None

# ========= Helpers para garantir que o site seja acessado =========
def _requests_with_selenium_cookies(driver, referer=None, session=None):
    """Reuse a single requests.Session for lighter resource usage."""
    s = session or requests.Session()
    if not session:
        # user agent + cookies apenas na primeira vez
        ua = driver.execute_script("return navigator.userAgent")
        s.headers.update({
            "User-Agent": ua,
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        })
        for c in driver.get_cookies():
            # requests aceita domínio com/sem ponto inicial
            s.cookies.set(
                name=c["name"],
                value=c["value"],
                domain=c.get("domain"),
                path=c.get("path", "/")
            )
    if referer:
        s.headers.update({"Referer": referer})
    return s

def _sanitize_name(name: str) -> str:
    keep = "-_.() "
    return "".join(ch for ch in name if ch.isalnum() or ch in keep).strip()

def _save_bytes(path: str, content: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)

def _infer_ext_from_content_type(ct: str) -> str:
    ct = (ct or "").lower()
    if "jpeg" in ct or "jpg" in ct: return ".jpg"
    if "png" in ct: return ".png"
    if "gif" in ct: return ".gif"
    if "pdf" in ct: return ".pdf"
    return ".bin"

def load_codes_from_file(path: str) -> list[str]:
    """Read tracking codes from a text file."""
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def _download_img_with_cookies(driver, url: str, out_base: str, referer: str, session):
    s = _requests_with_selenium_cookies(driver, referer=referer, session=session)
    r = s.get(url, timeout=90, allow_redirects=True)

    # redirecionou p/ login? conteúdo HTML?
    ctype = r.headers.get("Content-Type", "")
    if "text/html" in ctype.lower() or (r.status_code in (301,302,303,307,308) and "login" in r.text.lower()):
        return None, "redirecionado_para_login"

    content = r.content
    if len(content) < MIN_BYTES_OK:
        return None, f"arquivo_muito_pequeno({len(content)}B)"

    ext = _infer_ext_from_content_type(ctype)
    out = os.path.join(DOWNLOAD_DIR, _sanitize_name(out_base + ext))
    _save_bytes(out, content)
    return out, None

def _screenshot_element(locator, out_base: str):
    # fallback: screenshot do elemento <img>
    out = os.path.join(DOWNLOAD_DIR, _sanitize_name(out_base + ".png"))
    locator.screenshot(out)
    return out

def baixar_ars_da_tela(expected=0, progress_callback=None):
    """Download AR images visible on the current page.

    Parameters
    ----------
    expected: int, optional
        Quantidade total de ARs esperados; usado para atualizar o progresso
        caso menos itens sejam encontrados.
    progress_callback: callable, optional
        Função chamada após processar cada item.

    Returns
    -------
    tuple[list[dict], list[dict]]
        Listas de itens baixados e pulados.
    """

    baixados, pulados = [], []
    session = _requests_with_selenium_cookies(driver)
    try:
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.verArDigital")))
    except TimeoutException:
        if progress_callback:
            for _ in range(expected):
                progress_callback()
        return baixados, [{"pos": "-", "motivo": "nenhum link verArDigital encontrado"}]

    anchors = driver.find_elements(By.CSS_SELECTOR, "a.verArDigital")
    for idx, a in enumerate(anchors, start=1):
        style = (a.get_attribute("style") or "").replace(" ", "").lower()
        onclick = a.get_attribute("onclick") or ""

        # pula indisponíveis
        if "opacity:0.2" in style or "verArDigital" not in onclick:
            pulados.append({"pos": idx, "motivo": "indisponivel"})
            continue

        m = re.search(r"verArDigital\('([^']+)'\)", onclick)
        codigo = m.group(1) if m else f"desconhecido_{idx}"

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", a)
        time.sleep(HTML_ACTION_DELAY)

        before = set(driver.window_handles)
        # tenta clicar normal; se bloquear, força via JS
        try:
            time.sleep(HTML_ACTION_DELAY)
            a.click()
        except ElementClickInterceptedException:
            time.sleep(HTML_ACTION_DELAY)
            driver.execute_script("arguments[0].click();", a)

        # pode abrir na MESMA aba ou em NOVA aba; tratamos ambos:
        time.sleep(0.5)
        new_handles = list(set(driver.window_handles) - before)
        if new_handles:
            # Nova aba
            parent_handle = driver.current_window_handle
            new_handle = new_handles[0]
            driver.switch_to.window(new_handle)
        else:
            # Mesma aba
            parent_handle = None

        # Aguarda o <img src*="verArDigital.php">
        try:
            img = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'img[src*="verArDigital.php"]'))
            )
        except TimeoutException:
            # Se não apareceu o IMG, tenta salvar a URL atual (talvez seja o próprio verArDigital.php)
            current_url = driver.current_url
            if "verArDigital.php" in current_url:
                img = None
            else:
                pulados.append(
                    {
                        "pos": idx,
                        "codigo": codigo,
                        "motivo": "img verArDigital.php não encontrada",
                    }
                )
                # fecha aba se for nova
                if parent_handle:
                    try:
                        driver.close()
                    except Exception as e:
                        print(f"[WARN] Falha ao fechar aba após erro no código {codigo}: {e}")
                    driver.switch_to.window(parent_handle)
                continue

        referer = driver.current_url
        img_url = img.get_attribute("src") if img else referer  # fallback p/ URL da própria página

        # Tenta baixar via requests com cookies
        out_base = f"{codigo}"
        out_path, err = _download_img_with_cookies(driver, img_url, out_base, referer, session)

        if out_path and not err:
            baixados.append({"pos": idx, "codigo": codigo, "arquivos": [os.path.basename(out_path)]})
        else:
            # Fallback: screenshot do elemento <img>
            try:
                if img:
                    shot_path = _screenshot_element(img, out_base)
                else:
                    shot_path = os.path.join(
                        DOWNLOAD_DIR,
                        _sanitize_name(out_base + "_page.png"),
                    )
                    driver.save_screenshot(shot_path)
                baixados.append(
                    {
                        "pos": idx,
                        "codigo": codigo,
                        "arquivos": [os.path.basename(shot_path)],
                        "fallback": True,
                        "motivo": err,
                    }
                )
            except Exception as e:
                pulados.append(
                    {
                        "pos": idx,
                        "codigo": codigo,
                        "motivo": f"falha_download_e_fallback: {err or ''}; {e}",
                    }
                )

        # Fecha aba nova (se houve) e volta
        if parent_handle:
            try:
                driver.close()
            except Exception as e:
                print(f"[WARN] Não foi possível fechar aba para código {codigo}: {e}")
            driver.switch_to.window(parent_handle)
            time.sleep(0.1)

        if progress_callback:
            progress_callback()

    if progress_callback and expected > len(anchors):
        for _ in range(expected - len(anchors)):
            progress_callback()

    return baixados, pulados


def consultar_codigos(codes: list[str], progress_callback=None, batch_size: int = 200):
    """Consulta códigos em lotes sequenciais.

    Parâmetros
    -----------
    codes : list[str]
        Lista de códigos a serem consultados.
    progress_callback : callable, opcional
        Função chamada após o processamento de cada item.
    batch_size : int, opcional
        Quantidade máxima de códigos por requisição. O padrão é 200.
    """

    def chunk(lst, size):
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    # Abre menu e vai para Consulta Objetos
    try:
        menu = wait.until(EC.element_to_be_clickable((By.ID, "nav-menu")))
        time.sleep(HTML_ACTION_DELAY)
        menu.click()
    except TimeoutException as e:
        print(f"[WARN] Falha ao clicar no menu principal (nav-menu): {e}")

    try:
        expandir = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "expandir")))
        time.sleep(HTML_ACTION_DELAY)
        expandir.click()
    except TimeoutException as e:
        print(f"[WARN] Falha ao expandir o menu: {e}")

    consulta_obj = wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Consulta Objetos")))
    time.sleep(HTML_ACTION_DELAY)
    consulta_obj.click()

    try:
        opcoes = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "opcoes")))
        time.sleep(HTML_ACTION_DELAY)
        opcoes.click()
    except TimeoutException as e:
        print(f"[WARN] Falha ao abrir opções de consulta: {e}")

    try:
        chk = wait.until(EC.element_to_be_clickable((By.ID, "chkConsultarVariosObjetos")))
        time.sleep(HTML_ACTION_DELAY)
        chk.click()
    except TimeoutException as e:
        print(f"[WARN] Falha ao marcar 'Consultar vários objetos': {e}")

    all_ok, all_skip = [], []
    for batch in chunk(codes, batch_size):
        campo = wait.until(EC.presence_of_element_located((By.ID, "txtAreaObjetos")))
        time.sleep(HTML_ACTION_DELAY)
        campo.clear()
        time.sleep(HTML_ACTION_DELAY)
        campo.send_keys("\n".join(batch))
        pesquisar = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Pesquisar")))
        time.sleep(HTML_ACTION_DELAY)
        pesquisar.click()
        b_ok, b_skip = baixar_ars_da_tela(
            expected=len(batch), progress_callback=progress_callback
        )
        all_ok.extend(b_ok)
        all_skip.extend(b_skip)

    return all_ok, all_skip


def main():
    global driver, wait
    ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", light
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)

    for f in ["SingletonLock", "SingletonCookie", "SingletonSocket", "SingletonSemaphore"]:
        p = Path(PROFILE_DIR, f)
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                print(f"[WARN] Não foi possível remover {p}: {e}")

    options = webdriver.ChromeOptions()
    options.add_argument(fr"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-backgrounding-occluded-windows")
    # Desabilita recursos que podem interferir no fluxo do Selenium.
    # A inclusão de PasswordCheck busca evitar o aviso de senha comprometida
    # que bloqueia a interação automática em novos perfis do Chrome.
    options.add_argument(
        "--disable-features=Translate,MediaRouter,PasswordLeakDetection,PasswordCheck,AutomationControlled"
    )
    options.add_argument("--headless=new")           # <<< HEADLESS
    options.add_argument("--disable-gpu")
    options.add_argument(f"--window-size={WINDOW_SIZE}")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")

    options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "autofill.profile_enabled": False,
        "autofill.credit_card_enabled": False,
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        # Desabilita SafeBrowsing e verificações de vazamento de senhas
        # para evitar pop-ups que atrapalham a automação.
        "safebrowsing.enabled": False,
        "safebrowsing.disable_download_protection": True,
        # Desativa por completo o gerenciador de senhas e a checagem de vazamentos.
        "profile.password_manager_leak_detection": False,
        "profile.password_manager_auto_signin": False,
    })

    service = Service(ChromeDriverManager().install())
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException:
        print("[ERRO] Falha ao iniciar o Chrome.")
        raise

    wait = WebDriverWait(driver, 25)

    driver.get(TARGET)
    try:
        WebDriverWait(driver, 12).until(EC.url_contains("https://sgd.correios.com.br/sgd/app/"))
    except TimeoutException:
        driver.execute_script("window.location.href = arguments[0];", TARGET)
        WebDriverWait(driver, 12).until(EC.url_contains("https://sgd.correios.com.br/sgd/app/"))

    try:
        btn_entrar = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "entrar"))
        )
        time.sleep(HTML_ACTION_DELAY)
        btn_entrar.click()
    except TimeoutException as e:
        print(f"[WARN] Botão 'entrar' não disponível (pode já estar no quadro de login): {e}")

    # =========================
    # 1º APP: Captura de usuário/senha e login
    # =========================
    app = ctk.CTk()
    app.title("PRINTPOST A.R AUTOMATIZADO")
    app.geometry("500x300")

    definer_label = ctk.CTkLabel(app, text='ensira os codigos abaixo')
    definer_label.pack(pady=10)
    user = ctk.CTkEntry(app, placeholder_text="Usuario SGD")
    user.pack()
    pass_label = ctk.CTkLabel(app, text='ensira a senha' )
    pass_label.pack()
    password = ctk.CTkEntry(app, placeholder_text="Senha SGD", show="*")
    password.pack()

    Butão_check = ctk.CTkLabel(app, text='')
    Butão_check.pack()

    def entrar_sgd():
        try:
            SGD_USUARIO = user.get()
            SGD_SENHA = password.get()

            u = wait.until(EC.presence_of_element_located((By.ID, "username")))
            time.sleep(HTML_ACTION_DELAY)
            u.clear()
            time.sleep(HTML_ACTION_DELAY)
            u.send_keys(SGD_USUARIO)
            pwd = wait.until(EC.presence_of_element_located((By.ID, "password")))
            time.sleep(HTML_ACTION_DELAY)
            pwd.clear()
            time.sleep(HTML_ACTION_DELAY)
            pwd.send_keys(SGD_SENHA)
            time.sleep(HTML_ACTION_DELAY)
            pwd.send_keys(Keys.RETURN)

            wait.until(EC.presence_of_element_located((By.ID, "nav-menu")))
            Butão_check.configure(text="Login efetuado.")
        except Exception as e:
            Butão_check.configure(text=f"Tentando prosseguir... ({e})")
        finally:
            app.after(2000, app.destroy)

    butão_define = ctk.CTkButton(app, text="Login", command=entrar_sgd)
    butão_define.pack(pady=10)

    app.mainloop()

    # -------------------------
    # Função: 2º APP (entrada de códigos) + processamento
    # -------------------------
    def run_codes_flow():
        # 2º APP
        app2 = ctk.CTk()
        app2.title("PRINTPOST A.R AUTOMATIZADO")
        app2.geometry("500x350")
        store_codes = ctk.CTkLabel(
            app2,
            text='insira os codigos a serem consultados; serão processados em lotes de 200',
        )
        store_codes.pack(pady=10)

        Codes_entry = ctk.CTkTextbox(app2, width=400, height=150)
        Codes_entry.pack()

        def select_file():
            path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt")])
            if path:
                codes = load_codes_from_file(path)
                Codes_entry.delete("0.0", ctk.END)
                Codes_entry.insert("0.0", "\n".join(codes))

        select_button = ctk.CTkButton(app2, text="Selecionar arquivo", command=select_file)
        select_button.pack(pady=5)

        progress = ctk.CTkProgressBar(app2, width=400)

        CODES_LIST = []
        RESULT_OK, RESULT_SKIP = [], []

        def start_process():
            nonlocal CODES_LIST, RESULT_OK, RESULT_SKIP
            CODES_LIST = [c for c in re.findall(r"\S+", Codes_entry.get("0.0", ctk.END))]
            total = len(CODES_LIST)
            if not total:
                return
            Codes_entry.configure(state="disabled")
            select_button.configure(state="disabled")
            Codes_button.configure(state="disabled")
            progress.pack(pady=10)
            progress.set(0)
            app2.update_idletasks()

            counter = {"v": 0}

            def update_progress():
                counter["v"] += 1
                progress.set(counter["v"] / total)
                app2.update_idletasks()

            batch_size = 200
            total_batches = (total + batch_size - 1) // batch_size
            print(
                f"Processando {total} códigos em {total_batches} lote(s) de até {batch_size}."
            )
            RESULT_OK, RESULT_SKIP = consultar_codigos(
                CODES_LIST, progress_callback=update_progress, batch_size=batch_size
            )
            app2.after(500, app2.destroy)

        Codes_button = ctk.CTkButton(app2, text="Iniciar", command=start_process)
        Codes_button.pack(pady=10)

        app2.mainloop()
        return RESULT_OK, RESULT_SKIP

    # ========= Loop para permitir consultar mais códigos sem fechar =========
    try:
        while True:
            RESULT_OK, RESULT_SKIP = run_codes_flow()

            # Log simples no console
            print("ARs baixados")
            for b in RESULT_OK:
                tag_fb = "(fallback)" if b.get("fallback") else ""
                print(f"[{b['pos']:03}] {b.get('codigo','?')} -> {b['arquivos']}{tag_fb}")
            print("Itens pulados")
            for p in RESULT_SKIP:
                print(f"[{p['pos']:03}] {p.get('codigo','?')} -> {p['motivo']}")

            # 3º APP: opções finais (converter/deletar/voltar a consultar)
            app3 = ctk.CTk()
            app3.title("PRINTPOST A.R AUTOMATIZADO")
            app3.geometry("420x340")
            finish = ctk.CTkLabel(app3, text='Processo concluido, verifique a pasta de downloads,\nlocalizada em C:/Users/seu_usuario/SGD-BAIXADOS')
            finish.pack(pady=10)
            sucess = ctk.CTkLabel(app3, text='')
            sucess.pack(pady=6)
            delete = ctk.CTkLabel(app3, text='')
            delete.pack(pady=6)

            def delete_png():
                try:
                    count = 0
                    for f in os.listdir(DOWNLOAD_DIR):
                        if f.lower().endswith(".png"):
                            os.remove(os.path.join(DOWNLOAD_DIR, f))
                            count += 1
                    print(f"{count} arquivos PNG removidos.")
                    delete.configure(text='arquivos deleteados')
                except Exception as e:
                    print(f"Erro ao deletar PNGs: {e}")

            def pdf_convert():
                try:
                    allimages = [
                        os.path.join(DOWNLOAD_DIR, f)
                        for f in os.listdir(DOWNLOAD_DIR)
                        if f.lower().endswith(('.png', '.jpg', '.jpeg'))
                    ]
                    if not allimages:
                        print("Nenhuma imagem encontrada.")
                        return
                    for img in allimages:
                        with Image.open(img) as image:
                            if image.mode in ("RGBA", "P", "CMYK"):
                                image = image.convert("RGB")
                            pdf_path = img.rsplit('.', 1)[0] + '.pdf'
                            image.save(pdf_path, "PDF", resolution=100.0)
                        print(f"OK {img} -> {pdf_path}")
                        sucess.configure(text='arquivos convertidos para PDF \n na mesma pasta de download')
                except Exception as e:
                    print(f"Erro durante a conversao: {e}")

            # Novo: voltar para o 2º APP (consultar mais códigos)
            want_again = {"value": False}
            def voltar_para_consulta():
                want_again["value"] = True
                app3.destroy()

            pdf_entry      = ctk.CTkButton(app3, text="Converter para PDF", command=pdf_convert)
            delete_button  = ctk.CTkButton(app3, text="Deletar arquivos PNG", command=delete_png)
            again_button   = ctk.CTkButton(app3, text="Consultar mais códigos", command=voltar_para_consulta)
            close_button   = ctk.CTkButton(app3, text="Fechar", command=app3.destroy)

            pdf_entry.pack(pady=8)
            delete_button.pack(pady=8)
            again_button.pack(pady=12)
            close_button.pack(pady=8)

            app3.mainloop()

            # Se o usuário clicou em "Consultar mais códigos", repete o loop.
            if want_again["value"]:
                continue
            # Caso contrário, sai do loop e encerra.
            break

    except Exception as e:
        print(f"[ERRO] Falha ao baixar ARs: {e}")
    finally:
        time.sleep(1)
        driver.quit()


if __name__ == "__main__":
    main()
