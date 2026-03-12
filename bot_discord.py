import os
import asyncio
import json
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:
    FUSO = None

from automacao import executar_automacao


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if not DISCORD_BOT_TOKEN:
    raise ValueError("A variável de ambiente DISCORD_BOT_TOKEN não foi definida.")

USUARIOS_AUTORIZADOS = set()

ARQUIVO_DADOS = Path("dados.txt")
ARQUIVO_AGENDAMENTO = Path("agendamento.json")

automacao_em_execucao = False
ultima_execucao_agendada = None


def usuario_autorizado(user_id: int) -> bool:
    if not USUARIOS_AUTORIZADOS:
        return True
    return user_id in USUARIOS_AUTORIZADOS


def agora():
    if FUSO is not None:
        return datetime.now(FUSO)
    return datetime.now()


def agora_formatado():
    return agora().strftime("%d/%m/%Y %H:%M:%S")


def carregar_dados_brutos():
    if not ARQUIVO_DADOS.exists():
        raise FileNotFoundError("Arquivo dados.txt não encontrado.")

    linhas = ARQUIVO_DADOS.read_text(encoding="utf-8").splitlines()

    url = ""
    usuarios = []
    atual = {}

    for linha in linhas:
        linha_limpa = linha.strip()

        if not linha_limpa or linha_limpa.startswith("#"):
            if atual.get("login") and atual.get("senha"):
                usuarios.append(atual)
                atual = {}
            continue

        if "=" not in linha_limpa:
            continue

        chave, valor = linha_limpa.split("=", 1)
        chave = chave.strip().lower()
        valor = valor.strip()

        if chave == "url":
            url = valor
        elif chave in ("login", "senha"):
            atual[chave] = valor

    if atual.get("login") and atual.get("senha"):
        usuarios.append(atual)

    return url, usuarios


def salvar_dados(url: str, usuarios: list[dict]):
    linhas = [f"url={url}", ""]

    for usuario in usuarios:
        linhas.append(f"login={usuario['login']}")
        linhas.append(f"senha={usuario['senha']}")
        linhas.append("")

    ARQUIVO_DADOS.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")


def adicionar_ou_atualizar_login(login: str, senha: str):
    url, usuarios = carregar_dados_brutos()

    atualizado = False
    for usuario in usuarios:
        if usuario["login"] == login:
            usuario["senha"] = senha
            atualizado = True
            break

    if not atualizado:
        usuarios.append({"login": login, "senha": senha})

    salvar_dados(url, usuarios)
    return atualizado, len(usuarios)


def remover_login(login: str):
    url, usuarios = carregar_dados_brutos()

    antes = len(usuarios)
    usuarios = [u for u in usuarios if u["login"] != login]
    depois = len(usuarios)

    if antes == depois:
        return False, antes

    salvar_dados(url, usuarios)
    return True, depois


def carregar_agendamento():
    if not ARQUIVO_AGENDAMENTO.exists():
        return {"ativo": False, "hora": None, "minuto": None, "canal_id": None}

    try:
        dados = json.loads(ARQUIVO_AGENDAMENTO.read_text(encoding="utf-8"))
        return {
            "ativo": bool(dados.get("ativo", False)),
            "hora": dados.get("hora"),
            "minuto": dados.get("minuto"),
            "canal_id": dados.get("canal_id"),
        }
    except Exception:
        return {"ativo": False, "hora": None, "minuto": None, "canal_id": None}


def salvar_agendamento(ativo: bool, hora: int | None, minuto: int | None, canal_id: int | None):
    dados = {
        "ativo": ativo,
        "hora": hora,
        "minuto": minuto,
        "canal_id": canal_id,
    }
    ARQUIVO_AGENDAMENTO.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def validar_horario(texto: str):
    try:
        partes = texto.strip().split(":")
        if len(partes) != 2:
            return None

        hora = int(partes[0])
        minuto = int(partes[1])

        if not (0 <= hora <= 23 and 0 <= minuto <= 59):
            return None

        return hora, minuto
    except Exception:
        return None


def criar_embed_inicio(total):
    embed = discord.Embed(
        title="🚀 Automação iniciada",
        description="O sistema começou a processar os logins configurados.",
        color=discord.Color.blue()
    )
    embed.add_field(name="📌 Total de logins", value=str(total), inline=True)
    embed.add_field(name="🕒 Início", value=agora_formatado(), inline=True)
    embed.set_footer(text="Sistema de automação")
    return embed


def criar_embed_processando(login, indice, total):
    embed = discord.Embed(
        title="⚙️ Processando login",
        description="A automação está executando este usuário.",
        color=discord.Color.gold()
    )
    embed.add_field(name="👤 Login", value=f"`{login}`", inline=False)
    embed.add_field(name="📍 Progresso", value=f"{indice}/{total}", inline=True)
    embed.add_field(name="🕒 Horário", value=agora_formatado(), inline=True)
    embed.set_footer(text="Aguarde a conclusão desta etapa")
    return embed


def criar_embed_sucesso(login):
    embed = discord.Embed(
        title="✅ Login concluído com sucesso",
        description="As atividades deste usuário foram processadas corretamente.",
        color=discord.Color.green()
    )
    embed.add_field(name="👤 Login", value=f"`{login}`", inline=False)
    embed.add_field(name="🕒 Horário", value=agora_formatado(), inline=False)
    embed.set_footer(text="Prosseguindo para o próximo login")
    return embed


def criar_embed_sem_atividade(login):
    embed = discord.Embed(
        title="🟡 Nenhuma atividade disponível",
        description="Este usuário não possui atividades para executar.",
        color=discord.Color.yellow()
    )
    embed.add_field(name="👤 Login", value=f"`{login}`", inline=False)
    embed.add_field(name="🕒 Horário", value=agora_formatado(), inline=False)
    embed.set_footer(text="Prosseguindo para o próximo login")
    return embed


def criar_embed_erro(login, erro):
    erro = (erro or "Erro não informado").strip()

    if len(erro) > 1000:
        erro = erro[:1000] + "..."

    embed = discord.Embed(
        title="❌ Erro no processamento",
        description="Ocorreu um problema durante a execução deste login.",
        color=discord.Color.red()
    )
    embed.add_field(name="👤 Login", value=f"`{login}`", inline=False)
    embed.add_field(name="⚠️ Motivo", value=erro, inline=False)
    embed.add_field(name="🕒 Horário", value=agora_formatado(), inline=False)
    embed.set_footer(text="O sistema seguirá para o próximo login")
    return embed


def criar_embed_resumo(resultado):
    embed = discord.Embed(
        title="📊 Resumo final da automação",
        description="A execução foi encerrada com o consolidado abaixo.",
        color=discord.Color.blurple()
    )

    inicio = resultado["inicio"].strftime("%d/%m/%Y %H:%M:%S")
    fim = resultado["fim"].strftime("%d/%m/%Y %H:%M:%S")
    duracao = str(resultado["fim"] - resultado["inicio"]).split(".")[0]

    embed.add_field(name="📌 Total", value=str(resultado["total"]), inline=True)
    embed.add_field(name="✅ Sucessos", value=str(resultado["sucessos"]), inline=True)
    embed.add_field(name="❌ Falhas", value=str(resultado["falhas"]), inline=True)
    embed.add_field(name="🟡 Sem atividade", value=str(resultado["sem_atividade"]), inline=True)
    embed.add_field(name="🕒 Início", value=inicio, inline=True)
    embed.add_field(name="🕒 Fim", value=fim, inline=True)
    embed.add_field(name="⏱ Duração", value=duracao, inline=True)

    detalhes = []
    for item in resultado["detalhes"]:
        msg = item["mensagem"] or ""

        if msg == "SEM_ATIVIDADE":
            status = "🟡"
            texto = "Sem atividade"
        elif item["sucesso"]:
            status = "✅"
            texto = "Atividades processadas com sucesso"
        else:
            status = "❌"
            texto = msg

        if len(texto) > 80:
            texto = texto[:80] + "..."

        detalhes.append(f"{status} `{item['login']}` — {texto}")

    detalhes_texto = "Nenhum detalhe disponível." if not detalhes else "\n".join(detalhes[:20])
    if len(detalhes) > 20:
        detalhes_texto += f"\n... e mais {len(detalhes) - 20} item(ns)."

    embed.add_field(name="📝 Detalhes", value=detalhes_texto, inline=False)
    embed.set_footer(text="Automação concluída")
    return embed


def criar_embed_status_em_execucao():
    embed = discord.Embed(
        title="🟡 Status da automação",
        description="Existe uma execução em andamento neste momento.",
        color=discord.Color.gold()
    )
    embed.add_field(name="Situação", value="Em execução", inline=False)
    embed.add_field(name="Horário", value=agora_formatado(), inline=False)
    return embed


def criar_embed_status_parado():
    embed = discord.Embed(
        title="🟢 Status da automação",
        description="Nenhuma automação está em execução neste momento.",
        color=discord.Color.green()
    )
    embed.add_field(name="Situação", value="Parada", inline=False)
    embed.add_field(name="Horário", value=agora_formatado(), inline=False)
    return embed


def criar_embed_agendamento(hora: int, minuto: int):
    embed = discord.Embed(
        title="⏰ Agendamento salvo",
        description="A automação foi agendada para rodar todos os dias.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Horário", value=f"`{hora:02d}:{minuto:02d}`", inline=False)
    embed.add_field(name="Fuso", value="America/Sao_Paulo" if FUSO else "Horário local do sistema", inline=False)
    embed.add_field(name="Salvo em", value=agora_formatado(), inline=False)
    return embed


def criar_embed_agendamento_desativado():
    embed = discord.Embed(
        title="⏹️ Agendamento desativado",
        description="A execução automática diária foi desativada.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Horário", value=agora_formatado(), inline=False)
    return embed


def criar_embed_erro_geral(erro):
    erro = str(erro).strip() if erro else "Erro não informado"

    if len(erro) > 1000:
        erro = erro[:1000] + "..."

    embed = discord.Embed(
        title="🚨 Erro geral",
        description="Ocorreu uma falha durante a operação.",
        color=discord.Color.dark_red()
    )
    embed.add_field(name="Detalhes", value=erro, inline=False)
    embed.add_field(name="🕒 Horário", value=agora_formatado(), inline=False)
    return embed


def criar_embed_alunos():
    url, usuarios = carregar_dados_brutos()

    embed = discord.Embed(
        title="👥 Lista de alunos",
        description="Abaixo estão os logins e senhas atualmente salvos.",
        color=discord.Color.blurple()
    )

    embed.add_field(name="🌐 URL", value=url or "Não definida", inline=False)

    if not usuarios:
        embed.add_field(name="Alunos", value="Nenhum login cadastrado.", inline=False)
    else:
        linhas = []
        for i, usuario in enumerate(usuarios, start=1):
            linhas.append(f"**{i}.** Login: `{usuario['login']}` | Senha: `{usuario['senha']}`")

        texto = "\n".join(linhas)

        if len(texto) > 1000:
            partes = []
            atual = ""

            for linha in linhas:
                if len(atual) + len(linha) + 1 > 1000:
                    partes.append(atual)
                    atual = linha
                else:
                    atual = f"{atual}\n{linha}".strip()

            if atual:
                partes.append(atual)

            for idx, parte in enumerate(partes[:5], start=1):
                embed.add_field(name=f"Alunos {idx}", value=parte, inline=False)
        else:
            embed.add_field(name="Alunos", value=texto, inline=False)

    embed.set_footer(text="Use os botões abaixo para adicionar ou remover")
    return embed


class ModalAdicionarAluno(discord.ui.Modal, title="Adicionar aluno"):
    login = discord.ui.TextInput(
        label="Login",
        placeholder="Digite o login do aluno",
        required=True,
        max_length=100
    )

    senha = discord.ui.TextInput(
        label="Senha",
        placeholder="Digite a senha do aluno",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not usuario_autorizado(interaction.user.id):
            await interaction.response.send_message(
                "⛔ Você não tem permissão para executar esta ação.",
                ephemeral=True
            )
            return

        try:
            atualizado, total = adicionar_ou_atualizar_login(str(self.login), str(self.senha))

            embed = discord.Embed(
                title="➕ Aluno salvo",
                description="O login e a senha foram salvos com sucesso.",
                color=discord.Color.green()
            )
            embed.add_field(name="👤 Login", value=f"`{self.login}`", inline=False)
            embed.add_field(name="Ação", value="Senha atualizada" if atualizado else "Novo aluno adicionado", inline=False)
            embed.add_field(name="📌 Total de logins", value=str(total), inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                embed=criar_embed_erro_geral(e),
                ephemeral=True
            )


class ModalRemoverAluno(discord.ui.Modal, title="Remover aluno"):
    login = discord.ui.TextInput(
        label="Login",
        placeholder="Digite o login que deseja remover",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not usuario_autorizado(interaction.user.id):
            await interaction.response.send_message(
                "⛔ Você não tem permissão para executar esta ação.",
                ephemeral=True
            )
            return

        try:
            removido, total = remover_login(str(self.login))

            if removido:
                embed = discord.Embed(
                    title="➖ Aluno removido",
                    description="O login foi removido com sucesso.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="👤 Login", value=f"`{self.login}`", inline=False)
                embed.add_field(name="📌 Total de logins", value=str(total), inline=False)
            else:
                embed = discord.Embed(
                    title="🔎 Login não encontrado",
                    description="Não foi encontrado nenhum login com esse identificador.",
                    color=discord.Color.red()
                )
                embed.add_field(name="👤 Login", value=f"`{self.login}`", inline=False)

            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                embed=criar_embed_erro_geral(e),
                ephemeral=True
            )


class ViewAlunos(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Adicionar", style=discord.ButtonStyle.success, emoji="➕")
    async def adicionar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not usuario_autorizado(interaction.user.id):
            await interaction.response.send_message(
                "⛔ Você não tem permissão para executar esta ação.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(ModalAdicionarAluno())

    @discord.ui.button(label="Remover", style=discord.ButtonStyle.danger, emoji="➖")
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not usuario_autorizado(interaction.user.id):
            await interaction.response.send_message(
                "⛔ Você não tem permissão para executar esta ação.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(ModalRemoverAluno())


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


async def safe_send(canal, *, content=None, embed=None, view=None):
    try:
        return await canal.send(content=content, embed=embed, view=view)
    except Exception as e:
        print(f"Erro ao enviar mensagem no Discord: {e}")


async def executar_automacao_no_canal(canal):
    global automacao_em_execucao

    if automacao_em_execucao:
        await safe_send(canal, content="⚠️ Já existe uma automação em execução.")
        return

    automacao_em_execucao = True
    loop = asyncio.get_running_loop()

    try:
        await safe_send(canal, content="🤖 Automação iniciando...")

        def notify_sync(payload):
            tipo = payload.get("tipo")

            if tipo == "inicio":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(canal, embed=criar_embed_inicio(payload["total"])),
                    loop
                )
                future.result()

            elif tipo == "processando":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(
                        canal,
                        embed=criar_embed_processando(
                            payload["login"],
                            payload["indice"],
                            payload["total"]
                        )
                    ),
                    loop
                )
                future.result()

            elif tipo == "sucesso_login":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(canal, embed=criar_embed_sucesso(payload["login"])),
                    loop
                )
                future.result()

            elif tipo == "sem_atividade":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(canal, embed=criar_embed_sem_atividade(payload["login"])),
                    loop
                )
                future.result()

            elif tipo == "erro_login":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(canal, embed=criar_embed_erro(payload["login"], payload["mensagem"])),
                    loop
                )
                future.result()

            elif tipo == "fim":
                future = asyncio.run_coroutine_threadsafe(
                    safe_send(canal, embed=criar_embed_resumo(payload["resultado"])),
                    loop
                )
                future.result()

        await asyncio.to_thread(executar_automacao, notify_sync)

    except Exception as e:
        await safe_send(canal, embed=criar_embed_erro_geral(e))
        print(f"Erro geral em executar_automacao_no_canal: {e}")
    finally:
        automacao_em_execucao = False


@tasks.loop(seconds=20)
async def verificador_agendamento():
    global ultima_execucao_agendada

    config = carregar_agendamento()
    if not config["ativo"]:
        return

    hora = config["hora"]
    minuto = config["minuto"]
    canal_id = config["canal_id"]

    if hora is None or minuto is None or canal_id is None:
        return

    agora_local = agora()
    hoje = agora_local.date()

    if agora_local.hour == hora and agora_local.minute == minuto:
        if ultima_execucao_agendada == hoje:
            return

        ultima_execucao_agendada = hoje

        canal = bot.get_channel(canal_id)
        if canal is not None:
            await executar_automacao_no_canal(canal)


@verificador_agendamento.before_loop
async def before_verificador():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print("Slash commands sincronizados.")
    except Exception as e:
        print(f"Erro ao sincronizar slash commands: {e}")

    if not verificador_agendamento.is_running():
        verificador_agendamento.start()

    print(f"Bot conectado como {bot.user}")


@bot.tree.command(name="start", description="Inicia a automação agora")
async def start(interaction: discord.Interaction):
    if not usuario_autorizado(interaction.user.id):
        await interaction.response.send_message(
            "⛔ Você não tem permissão para executar este comando.",
            ephemeral=True
        )
        return

    if automacao_em_execucao:
        await interaction.response.send_message(
            "⚠️ Já existe uma automação em execução.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "✅ Comando recebido. Iniciando automação no canal...",
        ephemeral=True
    )

    canal = interaction.channel
    if canal is None:
        await interaction.followup.send(
            "❌ Não consegui identificar o canal para enviar as mensagens.",
            ephemeral=True
        )
        return

    asyncio.create_task(executar_automacao_no_canal(canal))


@bot.tree.command(name="status", description="Mostra o status atual da automação")
async def status(interaction: discord.Interaction):
    if not usuario_autorizado(interaction.user.id):
        await interaction.response.send_message(
            "⛔ Você não tem permissão para executar este comando.",
            ephemeral=True
        )
        return

    if automacao_em_execucao:
        await interaction.response.send_message(
            embed=criar_embed_status_em_execucao(),
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            embed=criar_embed_status_parado(),
            ephemeral=True
        )


@bot.tree.command(name="alunos", description="Mostra a lista de alunos com botões para adicionar e remover")
async def alunos(interaction: discord.Interaction):
    if not usuario_autorizado(interaction.user.id):
        await interaction.response.send_message(
            "⛔ Você não tem permissão para executar este comando.",
            ephemeral=True
        )
        return

    try:
        embed = criar_embed_alunos()
        view = ViewAlunos()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(
            embed=criar_embed_erro_geral(e),
            ephemeral=True
        )


@bot.tree.command(name="agendar", description="Agenda a automação para rodar todos os dias")
@app_commands.describe(
    horario="Horário no formato HH:MM",
    ativo="True para ativar, False para desativar"
)
async def agendar(interaction: discord.Interaction, horario: str, ativo: bool = True):
    if not usuario_autorizado(interaction.user.id):
        await interaction.response.send_message(
            "⛔ Você não tem permissão para executar este comando.",
            ephemeral=True
        )
        return

    if interaction.channel is None:
        await interaction.response.send_message(
            "❌ Não consegui identificar o canal deste comando.",
            ephemeral=True
        )
        return

    if not ativo:
        try:
            salvar_agendamento(False, None, None, interaction.channel.id)
            await interaction.response.send_message(
                embed=criar_embed_agendamento_desativado(),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=criar_embed_erro_geral(e),
                ephemeral=True
            )
        return

    horario_parseado = validar_horario(horario)
    if not horario_parseado:
        await interaction.response.send_message(
            "Formato inválido. Use `HH:MM`, por exemplo: `15:00`.",
            ephemeral=True
        )
        return

    hora, minuto = horario_parseado

    try:
        salvar_agendamento(True, hora, minuto, interaction.channel.id)
        await interaction.response.send_message(
            embed=criar_embed_agendamento(hora, minuto),
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            embed=criar_embed_erro_geral(e),
            ephemeral=True
        )


bot.run(DISCORD_BOT_TOKEN)
