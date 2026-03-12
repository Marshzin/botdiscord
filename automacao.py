from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

HEADLESS = True


def ler_dados():
    arquivo = Path("dados.txt")

    if not arquivo.exists():
        raise FileNotFoundError("dados.txt não encontrado")

    linhas = arquivo.read_text(encoding="utf-8").splitlines()

    url = ""
    usuarios = []
    atual = {}

    for linha in linhas:

        linha = linha.strip()

        if not linha:
            if atual.get("login") and atual.get("senha"):
                usuarios.append(atual)
                atual = {}
            continue

        if "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)

        chave = chave.strip().lower()
        valor = valor.strip()

        if chave == "url":
            url = valor

        elif chave in ("login", "senha"):
            atual[chave] = valor

    if atual.get("login") and atual.get("senha"):
        usuarios.append(atual)

    return url, usuarios


def executar_automacao(notify=None):

    url, usuarios = ler_dados()

    inicio = datetime.now()

    total = len(usuarios)

    sucessos = 0
    falhas = 0
    sem_atividade = 0

    detalhes = []

    if notify:
        notify({"tipo": "inicio", "total": total})

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
            ],
        )

        for i, usuario in enumerate(usuarios, start=1):

            login = usuario["login"]
            senha = usuario["senha"]

            if notify:
                notify(
                    {
                        "tipo": "processando",
                        "login": login,
                        "indice": i,
                        "total": total,
                    }
                )

            context = browser.new_context()
            page = context.new_page()

            try:

                page.goto(url)

                page.fill("#studentId", login)
                page.fill("#password", senha)

                page.click("#loginNormal")

                page.wait_for_timeout(2000)

                if page.locator("#notificationContainer").count() > 0:

                    texto = page.locator("#notificationContainer").inner_text()

                    if "Nenhuma atividade" in texto:

                        sem_atividade += 1

                        detalhes.append(
                            {
                                "login": login,
                                "sucesso": False,
                                "mensagem": "SEM_ATIVIDADE",
                            }
                        )

                        if notify:
                            notify(
                                {
                                    "tipo": "sem_atividade",
                                    "login": login,
                                }
                            )

                        context.close()
                        continue

                page.wait_for_selector("#activityModal", timeout=15000)

                page.click("#selectAll")

                page.click("#startSelected")

                page.wait_for_timeout(2000)

                sucessos += 1

                detalhes.append(
                    {
                        "login": login,
                        "sucesso": True,
                        "mensagem": "OK",
                    }
                )

                if notify:
                    notify(
                        {
                            "tipo": "sucesso_login",
                            "login": login,
                        }
                    )

            except Exception as e:

                falhas += 1

                detalhes.append(
                    {
                        "login": login,
                        "sucesso": False,
                        "mensagem": str(e),
                    }
                )

                if notify:
                    notify(
                        {
                            "tipo": "erro_login",
                            "login": login,
                            "mensagem": str(e),
                        }
                    )

            finally:
                context.close()

        browser.close()

    fim = datetime.now()

    resultado = {
        "inicio": inicio,
        "fim": fim,
        "total": total,
        "sucessos": sucessos,
        "falhas": falhas,
        "sem_atividade": sem_atividade,
        "detalhes": detalhes,
    }

    if notify:
        notify({"tipo": "fim", "resultado": resultado})

    return resultado
