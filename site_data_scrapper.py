#importações para o script funcionar
import os, re, time, requests
import customtkinter as ctk
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", light
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

# ========= Pastas, se não existirem o script cria com os.makedirs =========
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

# Limpa travas de perfil se sobrou algo do último crash
for f in ["SingletonLock", "SingletonCookie", "SingletonSocket", "SingletonSemaphore"]:
    p = Path(PROFILE_DIR, f)
    if p.exists():
        try: p.unlink()
        except: pass

# ========= Chrome Options (HEADLESS) roda em segundo plano, sem atrapalhar o usuario =========
options = webdriver.ChromeOptions()
options.add_argument(fr"--user-data-dir={PROFILE_DIR}")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")
options.add_argument("--disable-backgrounding-occluded-windows")
options.add_argument("--disable-features=Translate,MediaRouter,PasswordLeakDetection,AutomationControlled")
options.add_argument("--headless=new")           # <<< HEADLESS
options.add_argument("--disable-gpu")
options.add_argument(f"--window-size={WINDOW_SIZE}")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--no-sandbox")

# Preferências (não dependemos do gerenciador de download)
options.add_experimental_option("prefs", {
    
    "credentials_enable_service": False,       # disable password manager
    "profile.password_manager_enabled": False, # legacy toggle
    "autofill.profile_enabled": False,
    "autofill.credit_card_enabled": False,
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
})

# ========= Driver (Chrome) =========
service = Service(ChromeDriverManager().install())
try:
    driver = webdriver.Chrome(service=service, options=options)
except SessionNotCreatedException:
    print("[ERRO] Falha ao iniciar o Chrome.")
    raise

wait = WebDriverWait(driver, 25)

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

# ========= Navegação inicial =========
driver.get(TARGET)
try:
    WebDriverWait(driver, 12).until(EC.url_contains("https://sgd.correios.com.br/sgd/app/"))
except TimeoutException:
    driver.execute_script("window.location.href = arguments[0];", TARGET)
    WebDriverWait(driver, 12).until(EC.url_contains("https://sgd.correios.com.br/sgd/app/"))

# Tenta abrir o formulário de login (caso haja botão "entrar")
try:
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "entrar"))).click()
except TimeoutException:
    pass  # pode já estar no quadro de login

# =========================
# 1º APP: Captura de usuário/senha e login
# =========================
app=ctk.CTk()
app.title("PRINTPOST A.R AUTOMATIZADO")
app.geometry("500x300")

# Rótulos e entradas
#entrada de usuario e senha
definer_label = ctk.CTkLabel(app, text='ensira os codigos abaixo')
definer_label.pack(pady=10)
user = ctk.CTkEntry(app, placeholder_text="Usuario SGD")
user.pack()
pass_label = ctk.CTkLabel(app, text='ensira a senha' )
pass_label.pack()
password = ctk.CTkEntry(app, placeholder_text="Senha SGD", show="*")
password.pack()

# Indicador de clique/estado
Butão_check = ctk.CTkLabel(app, text='')
Butão_check.pack()
# Ação de login
def entrar_sgd():
    try:
        SGD_USUARIO = user.get()
        SGD_SENHA = password.get()

        # Preenche e envia o formulário
        u = wait.until(EC.presence_of_element_located((By.ID, "username")))
        u.clear(); u.send_keys(SGD_USUARIO)
        pwd = wait.until(EC.presence_of_element_located((By.ID, "password")))
        pwd.clear(); pwd.send_keys(SGD_SENHA)
        pwd.send_keys(Keys.RETURN)

        # Aguarda pós-login
        wait.until(EC.presence_of_element_located((By.ID, "nav-menu")))
        Butão_check.configure(text="Login efetuado.")
        app.after(2000, app.destroy)
    except Exception as e:
        # Se já estava logado ou layout diferente, tenta seguir mesmo assim.
        Butão_check.configure(text=f"Tentando prosseguir... ({e})")
        app.after(2000, app.destroy)

# Botão de login
butão_define = ctk.CTkButton(app, text="Login", command=entrar_sgd)
butão_define.pack(pady=10)

# Loop do 1º app
app.mainloop()

# =========================
# 2º APP: Entrada de códigos e acionar pesquisa
# =========================
app=ctk.CTk()
app.title("PRINTPOST A.R AUTOMATIZADO")
app.geometry("500x300")
#entrada de dados
store_codes = ctk.CTkLabel(app, text='insira os codigos a serem consultados, limite de 200 por vez')
store_codes.pack(pady=10)

Codes_entry = ctk.CTkTextbox(app, width=400, height=150)
Codes_entry.pack()

# Variável global para armazenar os códigos digitados
CODES_SAVE = ""

def consulting_sgds():
    # Coleta do conteúdo e fechamento do app p/ continuar o fluxo
    global CODES_SAVE
    CODES_SAVE = Codes_entry.get("0.0", ctk.END).strip()
    app.after(100, app.destroy)

Codes_button = ctk.CTkButton(app, text="Salvar Codigos", command=consulting_sgds)
Codes_button.pack(pady=10)

# Loop do 2º app (só prossegue quando o usuário clicar em "Salvar Codigos")
app.mainloop()

# =========================
# Fluxo após obter os códigos: Navegação e Pesquisa
# =========================

# Abre menu e vai para Consulta Objetos
try:
    wait.until(EC.element_to_be_clickable((By.ID, "nav-menu"))).click()
except TimeoutException:
    # Se o menu já estiver aberto, segue
    pass

try:
    wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "expandir"))).click()
except TimeoutException:
    pass

wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Consulta Objetos"))).click()

try:
    wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "opcoes"))).click()
except TimeoutException:
    pass

# Ativa "Consultar Vários"
try:
    chk = wait.until(EC.element_to_be_clickable((By.ID, "chkConsultarVariosObjetos")))
    chk.click()
except TimeoutException:
    pass

# Campo de códigos
campo_codigos = wait.until(EC.presence_of_element_located((By.ID, "txtAreaObjetos")))
campo_codigos.clear()
if CODES_SAVE:
    campo_codigos.send_keys(CODES_SAVE)

# Pesquisar
wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Pesquisar"))).click()

# ========= Baixar ARs (HEADLESS; sem Ctrl+S) =========
def baixar_ars_da_tela():
    baixados, pulados = [], []
    session = _requests_with_selenium_cookies(driver)
    try:
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.verArDigital")))
    except TimeoutException:
        return baixados, [{"pos":"-", "motivo":"nenhum link verArDigital encontrado"}]

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
        time.sleep(0.15)

        before = set(driver.window_handles)
        # tenta clicar normal; se bloquear, força via JS
        try:
            a.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", a)

        # pode abrir na MESMA aba ou em NOVA aba; tratamos ambos:
        time.sleep(0.5)
        new_handles = list(set(driver.window_handles) - before)
        if new_handles:
            # Nova aba
            main_handle = driver.current_window_handle
            new_handle = new_handles[0]
            driver.switch_to.window(new_handle)
        else:
            # Mesma aba
            main_handle = None

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
                pulados.append({"pos": idx, "codigo": codigo, "motivo": "img verArDigital.php não encontrada"})
                # fecha aba se for nova
                if main_handle:
                    try: driver.close()
                    except: pass
                    driver.switch_to.window(main_handle)
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
                    # Se não temos o elemento img, faz screenshot da página toda
                    shot_path = os.path.join(DOWNLOAD_DIR, _sanitize_name(out_base + "_page.png"))
                    driver.save_screenshot(shot_path)
                baixados.append({"pos": idx, "codigo": codigo, "arquivos": [os.path.basename(shot_path)], "fallback": True, "motivo": err})
            except Exception as e:
                pulados.append({"pos": idx, "codigo": codigo, "motivo": f"falha_download_e_fallback: {err or ''}; {e}"})

        # Fecha aba nova (se houve) e volta
        if main_handle:
            try: driver.close()
            except: pass
            driver.switch_to.window(main_handle)
            time.sleep(0.1)

    return baixados, pulados
# ========= App final: Converter para PDF e deletar PNG =========
# quando acionado fecha o app em 2 segundos
def destroy():
    app.after(2000, app.destroy)
    # quando acionado apaga os arquivos PNG da pasta de download
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
        # quando acionado converte os arquivos PNG/JPG para PDF
def pdf_convert():
    try:
        # pega apenas imagens suportadas
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
                # converte para RGB se necessário
                if image.mode in ("RGBA", "P", "CMYK"):
                    image = image.convert("RGB")

                pdf_path = img.rsplit('.', 1)[0] + '.pdf'
                image.save(pdf_path, "PDF", resolution=100.0)
            print(f"OK {img} -> {pdf_path}")   # no Unicode symbols
            sucess.configure(text='arquivos convertidos para PDF \n na mesma pasta de download')
    except Exception as e:
        print(f"Erro durante a conversao: {e}")

# ========= Execução =========
try:
    b_ok, b_skip = baixar_ars_da_tela()

    print("ARs baixados")
    for b in b_ok:
        tag_fb = "(fallback)" if b.get("fallback") else ""
        print(f"[{b['pos']:03}] {b.get('codigo','?')} -> {b['arquivos']}{tag_fb}")
    print(" Itens pulados")
    #ultima interface grafica, com botões para converter e deletar, e mensagem de conclusão
    app=ctk.CTk()
    app.title("PRINTPOST A.R AUTOMATIZADO")
    app.geometry("400x300")
    finish = ctk.CTkLabel(app, text='Processo concluido, verifique a pasta de downloads,\n''localizada em C:/Users/seu_usuario/SGD-BAIXADOS')
    finish.pack(pady=10)
    pdf_entry = ctk.CTkButton(app, text="converter para pdf", command=pdf_convert)
    pdf_entry.pack(pady=10)
    sucess = ctk.CTkLabel(app, text=f'')
    sucess.pack(pady=10)
    button_quit = ctk.CTkButton(app, text="Fechar", command=app.destroy)
    button_quit.pack(pady=10)
    delete_button = ctk.CTkButton(app, text="deletar arquivos PNG", command=delete_png)
    delete_button.pack(pady=10)
    delete = ctk.CTkLabel(app, text=f'')
    delete.pack(pady=10)
    app.mainloop()
    # relatório final no console
    for p in b_skip:
        print(f"[{p['pos']:03}] {p.get('codigo','?')} -> {p['motivo']}")
except Exception as e:
    print(f"[ERRO] Falha ao baixar ARs: {e}")
#fim do script
finally:
    time.sleep(1)
    driver.quit()
