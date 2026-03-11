from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright


HEADLESS = True


def ler_dados(caminho="dados.txt"):
    arquivo = Path(caminho)

    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    url = None
    usuarios = []
    atual = {}

    with arquivo.open("r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()

            if not linha or linha.startswith("#"):
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

    if not url:
        raise ValueError("Campo 'url' ausente no dados.txt.")

    if not usuarios:
        raise ValueError("Nenhum login/senha válido foi encontrado no dados.txt.")

    return url, usuarios


def esperar_altcha_verificado(page):
    page.locator(".altcha").wait_for(state="visible")

    page.wait_for_function(
        """() => {
            const el = document.querySelector('.altcha');
            return el && el.getAttribute('data-state') === 'verified';
        }""",
        timeout=0
    )


def clicar_checkbox_altcha(page):
    checkbox = page.locator("input[id^='altcha_checkbox_']").first
    checkbox.wait_for(state="visible")

    try:
        checkbox.check(force=True)
    except Exception:
        checkbox.click(force=True)


def texto_limpo(texto):
    return " ".join((texto or "").split()).strip()


def ler_notification_container(page):
    try:
        return page.evaluate("""
            () => {
                const el = document.querySelector('#notificationContainer');
                if (!el) return '';
                return (el.innerText || el.textContent || '').trim();
            }
        """)
    except Exception:
        return ""


def eh_notificacao_sem_atividade(texto):
    texto = texto_limpo(texto).lower()

    return (
        ("nenhuma ativ" in texto and "encontr" in texto)
        or "nenhuma atividade encontrada" in texto
        or "nenhuma atividades encontrada" in texto
    )


def eh_notificacao_transitoria(texto):
    texto = texto_limpo(texto).lower()

    avisos_transitorios = [
        "fazendo login",
        "login feito",
        "buscando atividades",
        "carregando atividades",
        "carregando atividade",
        "aguarde",
        "processando",
        "entrando na sua conta",
        "verificando",
    ]

    return any(aviso in texto for aviso in avisos_transitorios)


def eh_notificacao_erro_real(texto):
    texto = texto_limpo(texto).lower()

    erros_reais = [
        "erro",
        "inválid",
        "invalido",
        "incorret",
        "falha",
        "não foi possível",
        "nao foi possivel",
        "acesso negado",
        "bloqueado",
        "expirad",
        "problema",
        "tente novamente",
    ]

    return any(erro in texto for erro in erros_reais)


def esperar_modal_ou_notificacao(page):
    while True:
        try:
            modal = page.locator("#activityModal")

            if modal.count() > 0 and modal.first.is_visible():
                return "MODAL", None

            texto_notificacao = texto_limpo(ler_notification_container(page))

            if texto_notificacao:
                if eh_notificacao_sem_atividade(texto_notificacao):
                    return "SEM_ATIVIDADE", texto_notificacao

                if eh_notificacao_transitoria(texto_notificacao):
                    page.wait_for_timeout(250)
                    continue

                if eh_notificacao_erro_real(texto_notificacao):
                    return "ERRO", texto_notificacao

                page.wait_for_timeout(250)
                continue

        except Exception:
            pass

        page.wait_for_timeout(250)


def detectar_resultado_final(page):
    try:
        sucesso = page.evaluate("""
            () => {
                const fortes = Array.from(document.querySelectorAll('strong'));
                return fortes.some(el =>
                    (el.innerText || el.textContent || '').includes(
                        'Todas as atividades foram processadas com sucesso!'
                    )
                );
            }
        """)
        if sucesso:
            return True, "ATIVIDADES_PROCESSADAS"

        texto_notificacao = texto_limpo(ler_notification_container(page))

        if texto_notificacao:
            if eh_notificacao_sem_atividade(texto_notificacao):
                return True, "SEM_ATIVIDADE"

            if eh_notificacao_transitoria(texto_notificacao):
                return None, None

            if eh_notificacao_erro_real(texto_notificacao):
                return False, texto_notificacao

            return None, None

        return None, None

    except Exception:
        return None, None


def esperar_resultado(page):
    while True:
        status, mensagem = detectar_resultado_final(page)

        if status is not None:
            return status, mensagem

        page.wait_for_timeout(250)


def executar_atividade(page):
    status, mensagem = esperar_modal_ou_notificacao(page)

    if status == "SEM_ATIVIDADE":
        return True, "SEM_ATIVIDADE"

    if status == "ERRO":
        return False, mensagem or "Erro exibido em notificação"

    if status != "MODAL":
        return False, "Não foi possível identificar modal ou notificação."

    page.locator("#selectAll").wait_for(state="visible")
    page.locator("#selectAll").click(force=True)

    page.locator("#startSelected").wait_for(state="visible")
    page.locator("#startSelected").click(force=True)

    return esperar_resultado(page)


def executar_login(page, url, login, senha):
    page.goto(url, wait_until="domcontentloaded")

    page.locator("#studentId").fill(login)
    page.locator("#password").fill(senha)

    if page.locator(".altcha").count() > 0:
        clicar_checkbox_altcha(page)
        esperar_altcha_verificado(page)

    page.locator("#loginNormal").click(force=True)

    return executar_atividade(page)


def montar_resumo(total, sucessos, falhas, sem_atividade, detalhes, inicio, fim):
    duracao = fim - inicio

    linhas = [
        "=" * 70,
        "AUTOMAÇÃO FINALIZADA",
        f"Início: {inicio.strftime('%d/%m/%Y %H:%M:%S')}",
        f"Fim: {fim.strftime('%d/%m/%Y %H:%M:%S')}",
        f"Duração: {str(duracao).split('.')[0]}",
        f"Total: {total}",
        f"Sucessos: {sucessos}",
        f"Falhas: {falhas}",
        f"Sem atividade: {sem_atividade}",
        "-" * 70,
        "DETALHES:"
    ]

    for item in detalhes:
        if item["mensagem"] == "SEM_ATIVIDADE":
            status = "SEM_ATIVIDADE"
        elif item["sucesso"]:
            status = "SUCESSO"
        else:
            status = "ERRO"

        linhas.append(f"{status} | {item['login']} | {item['mensagem']}")

    linhas.append("=" * 70)
    return "\n".join(linhas)


def criar_contexto(browser):
    context = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        locale="pt-BR",
        timezone_id="America/Sao_Paulo"
    )

    page = context.new_page()

    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)

    return context, page


def executar_automacao(notify=None):
    if notify is None:
        def notify(payload):
            print(payload)

    inicio = datetime.now()
    url, usuarios = ler_dados()

    total = len(usuarios)
    sucessos = 0
    falhas = 0
    sem_atividade = 0
    detalhes = []

    notify({
        "tipo": "inicio",
        "total": total
    })

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        try:
            for i, usuario in enumerate(usuarios, start=1):
                login = usuario["login"]
                senha = usuario["senha"]

                context, page = criar_contexto(browser)

                page.set_default_timeout(0)
                page.set_default_navigation_timeout(0)

                notify({
                    "tipo": "processando",
                    "login": login,
                    "indice": i,
                    "total": total
                })

                try:
                    sucesso, mensagem = executar_login(page, url, login, senha)

                    if sucesso and mensagem == "SEM_ATIVIDADE":
                        sem_atividade += 1
                        notify({
                            "tipo": "sem_atividade",
                            "login": login,
                            "mensagem": mensagem
                        })

                    elif sucesso:
                        sucessos += 1
                        notify({
                            "tipo": "sucesso_login",
                            "login": login,
                            "mensagem": mensagem
                        })

                    else:
                        falhas += 1
                        notify({
                            "tipo": "erro_login",
                            "login": login,
                            "mensagem": mensagem
                        })

                    detalhes.append({
                        "login": login,
                        "sucesso": sucesso,
                        "mensagem": mensagem
                    })

                except Exception as e:
                    falhas += 1
                    erro = str(e).strip() or "Erro desconhecido"

                    detalhes.append({
                        "login": login,
                        "sucesso": False,
                        "mensagem": erro
                    })

                    notify({
                        "tipo": "erro_login",
                        "login": login,
                        "mensagem": erro
                    })

                finally:
                    context.close()

        finally:
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
        "resumo": montar_resumo(
            total=total,
            sucessos=sucessos,
            falhas=falhas,
            sem_atividade=sem_atividade,
            detalhes=detalhes,
            inicio=inicio,
            fim=fim
        )
    }

    notify({
        "tipo": "fim",
        "resultado": resultado
    })

    return resultado


if __name__ == "__main__":
    executar_automacao()