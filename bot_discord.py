import os
import asyncio
import discord
from discord.ext import commands

from automacao import executar_automacao


TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


async def enviar(canal, embed):

    try:
        await canal.send(embed=embed)
    except Exception as e:
        print("Erro ao enviar mensagem:", e)


def embed_inicio(total):

    e = discord.Embed(
        title="🚀 Automação iniciada",
        color=discord.Color.blue(),
    )

    e.add_field(name="Total de logins", value=str(total))

    return e


def embed_processando(login, indice, total):

    e = discord.Embed(
        title="⚙️ Processando",
        color=discord.Color.gold(),
    )

    e.add_field(name="Login", value=login)
    e.add_field(name="Progresso", value=f"{indice}/{total}")

    return e


def embed_sucesso(login):

    e = discord.Embed(
        title="✅ Sucesso",
        color=discord.Color.green(),
    )

    e.add_field(name="Login", value=login)

    return e


def embed_sem_atividade(login):

    e = discord.Embed(
        title="🟡 Sem atividades",
        color=discord.Color.yellow(),
    )

    e.add_field(name="Login", value=login)

    return e


def embed_erro(login, msg):

    e = discord.Embed(
        title="❌ Erro",
        color=discord.Color.red(),
    )

    e.add_field(name="Login", value=login)
    e.add_field(name="Motivo", value=msg)

    return e


def embed_final(resultado):

    e = discord.Embed(
        title="📊 Resultado final",
        color=discord.Color.blurple(),
    )

    e.add_field(name="Total", value=str(resultado["total"]))
    e.add_field(name="Sucessos", value=str(resultado["sucessos"]))
    e.add_field(name="Falhas", value=str(resultado["falhas"]))
    e.add_field(name="Sem atividade", value=str(resultado["sem_atividade"]))

    return e


async def executar_no_canal(canal):

    loop = asyncio.get_running_loop()

    def notify(payload):

        tipo = payload["tipo"]

        if tipo == "inicio":
            asyncio.run_coroutine_threadsafe(
                enviar(canal, embed_inicio(payload["total"])), loop
            )

        elif tipo == "processando":
            asyncio.run_coroutine_threadsafe(
                enviar(
                    canal,
                    embed_processando(
                        payload["login"],
                        payload["indice"],
                        payload["total"],
                    ),
                ),
                loop,
            )

        elif tipo == "sucesso_login":
            asyncio.run_coroutine_threadsafe(
                enviar(canal, embed_sucesso(payload["login"])), loop
            )

        elif tipo == "sem_atividade":
            asyncio.run_coroutine_threadsafe(
                enviar(canal, embed_sem_atividade(payload["login"])), loop
            )

        elif tipo == "erro_login":
            asyncio.run_coroutine_threadsafe(
                enviar(canal, embed_erro(payload["login"], payload["mensagem"])), loop
            )

        elif tipo == "fim":
            asyncio.run_coroutine_threadsafe(
                enviar(canal, embed_final(payload["resultado"])), loop
            )

    await asyncio.to_thread(executar_automacao, notify)


@bot.event
async def on_ready():

    print("Bot conectado:", bot.user)


@bot.tree.command(name="start", description="Executa a automação")
async def start(interaction: discord.Interaction):

    await interaction.response.send_message(
        "Automação iniciando...", ephemeral=True
    )

    canal = interaction.channel

    asyncio.create_task(executar_no_canal(canal))


bot.run(TOKEN)
