import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import random
import json
import asyncio
import requests
import tempfile
import logging
import math
from collections import defaultdict
with open("config.json", "r") as f:
    config = json.load(f)
AUDIO_DIR = "./Audio"
REDDIT_SUBREDDITS = ["darkjokes", "jokes", "dadjokes"]
REDDIT_MAX_LENGTH = 350
REDDIT_HEADERS = {"User-Agent": "Mozilla/5.0"}
DEFAULT_GPT_PROMPT = config.get("gpt_system_prompt", "You are a helpful assistant. Reply in the language in which the question is asked, either English or French.")
DEFAULT_SAYVC_INSTRUCTIONS = config.get("say_vc_instructions", "Utilise un accent québécois")
audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(".mp3")]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)
_guild_gpt_prompt = defaultdict(lambda: DEFAULT_GPT_PROMPT)
_guild_sayvc_instructions = defaultdict(lambda: DEFAULT_SAYVC_INSTRUCTIONS)
_guild_gpt_prompt_reset_task = {}
_guild_sayvc_reset_task = {}
reddit_jokes_by_sub = defaultdict(list)
async def fetch_reddit_top(subreddit, headers, max_posts=1000):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=year&limit=1000"
    loop = asyncio.get_event_loop()
    def fetch():
        posts, after = [], None
        while len(posts) < max_posts:
            page_url = url + (f"&after={after}" if after else "")
            try:
                r = requests.get(page_url, headers=headers, timeout=10)
                r.raise_for_status()
                data = r.json()["data"]
                children = data.get("children", [])
                if not children: break
                posts.extend(children)
                after = data.get("after")
                if not after or len(children) < 100: break
            except Exception as ex:
                logging.warning(f"Reddit fetch error: {ex}")
                break
        return posts[:max_posts]
    return await loop.run_in_executor(None, fetch)
async def load_reddit_jokes():
    logging.info("Loading Reddit jokes...")
    unique = defaultdict(list)
    seen = set()
    for sub in REDDIT_SUBREDDITS:
        posts = await fetch_reddit_top(sub, REDDIT_HEADERS, max_posts=1000)
        for post in posts:
            d = post["data"]
            joke_text = f"{d.get('title','')}. {d.get('selftext','')}".strip()
            k = joke_text.lower()
            if 0 < len(joke_text) <= REDDIT_MAX_LENGTH and k not in seen:
                unique[d.get('subreddit', sub).lower()].append(post)
                seen.add(k)
    logging.info(f"Loaded {sum(len(x) for x in unique.values())} jokes unique from Reddit.")
    return unique
def run_tts(joke_text, filename, voice, instructions):
    try:
        resp = requests.post(
            config["tts_url"],
            headers={
                "api-key": config["api_key"],
                "Content-Type": "application/json"
            },
            json={
                "input": joke_text,
                "model": "gpt-4o-mini-tts",
                "voice": voice,
                "response_format": "mp3",
                "speed": 1.0,
                "instructions": instructions
            },
            timeout=15
        )
        if resp.status_code == 200:
            with open(filename, "wb") as f: f.write(resp.content)
            return True
        else:
            logging.error(f"TTS error: {resp.status_code} {resp.text}")
            return False
    except Exception as ex:
        logging.error(f"TTS network error: {ex}")
        return False
def run_gpt(query, system_prompt):
    try:
        resp = requests.post(
            config["azure_gpt_url"],
            headers={
                "api-key": config["api_key"],
                "Content-Type": "application/json"
            },
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "max_tokens": 400
            },
            timeout=20
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            logging.error(f"GPT error: {resp.status_code} {resp.text}")
            return "Erreur : la réponse d'Azure OpenAI a échoué."
    except Exception as ex:
        logging.error(f"GPT network error: {ex}")
        return "Erreur : impossible de contacter Azure OpenAI."
async def play_audio(interaction, file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} not found.")
    user = interaction.user
    if not (user.voice and user.voice.channel):
        raise RuntimeError("Vous devez être connecté à un salon vocal pour exécuter cette commande.")
    vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    try:
        if not vc or not vc.is_connected():
            vc = await user.voice.channel.connect()
        elif vc.channel != user.voice.channel:
            await vc.move_to(user.voice.channel)
        vc.play(discord.FFmpegPCMAudio(file_path))
        while vc.is_playing(): await asyncio.sleep(1)
        await vc.disconnect()
    except Exception as e:
        raise RuntimeError(f"Erreur pendant la lecture audio : {e}")
async def _delayed_reset_gpt(gid):
    await asyncio.sleep(24 * 3600)
    _guild_gpt_prompt[gid] = DEFAULT_GPT_PROMPT
    _guild_gpt_prompt_reset_task[gid] = None
async def _delayed_reset_sayvc(gid):
    await asyncio.sleep(24 * 3600)
    _guild_sayvc_instructions[gid] = DEFAULT_SAYVC_INSTRUCTIONS
    _guild_sayvc_reset_task[gid] = None
def _cancel_task(task):
    if task and not task.done():
        task.cancel()
@bot.event
async def on_ready():
    logging.info(f"Bot logged in as {bot.user}!")
    print(f"Logged in as {bot.user}!")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)} cmds")
    except Exception as e:
        print(e)
    await bot.change_presence(activity=discord.Game(name="Tape /help"))
    preload_jokes_task.start()
@tasks.loop(count=1)
async def preload_jokes_task():
    global reddit_jokes_by_sub
    await asyncio.sleep(2)
    reddit_jokes_by_sub = await load_reddit_jokes()
@bot.tree.command(name="ping", description="Renvoie Pong ! (test de connexion)")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong !", ephemeral=True)
@bot.tree.command(name="jokeqc", description="Joue une blague québécoise (mp3)")
async def jokeqc(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    file = random.choice(audio_files)
    try:
        await asyncio.wait_for(play_audio(interaction, os.path.join(AUDIO_DIR, file)), timeout=30)
    except Exception as exc:
        msg = "Erreur : le fichier audio n'a pas été trouvé." if isinstance(exc, FileNotFoundError) \
                else f"Erreur pendant la lecture : {exc}"
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans votre salon vocal.", ephemeral=True)
@bot.tree.command(name="joke", description="Joue une blague Reddit en vocal")
async def joke(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    global reddit_jokes_by_sub
    if not reddit_jokes_by_sub:
        await interaction.followup.send("Aucune blague disponible pour le moment. Veuillez réessayer dans quelques secondes.", ephemeral=True)
        return
    sub = random.choice(list(reddit_jokes_by_sub.keys()))
    posts = reddit_jokes_by_sub[sub]
    bias = 0.02
    weights = [math.exp(-bias * i) for i in range(len(posts))]
    idx = random.choices(range(len(posts)), weights=[w/sum(weights) for w in weights], k=1)[0]
    post = posts[idx]["data"]
    joke_text = f"{post['title']}. {post['selftext']}".strip()
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.followup.send("Vous devez être connecté à un salon vocal pour écouter la blague.", ephemeral=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        filename = tmp.name
    loop = asyncio.get_running_loop()
    try:
        success = await asyncio.wait_for(
            loop.run_in_executor(None, run_tts, joke_text, filename, "ash","Read this joke with a comic tone, as if you are a stand-up comedian."),
            timeout=20
        )
        if not success: raise Exception("Erreur lors de la génération de la synthèse vocale.")
        await asyncio.wait_for(play_audio(interaction, filename), timeout=30)
    except Exception as exc:
        await interaction.followup.send(f"Erreur : {exc}", ephemeral=True)
    else:
        await interaction.followup.send("Blague lue dans le salon vocal.", ephemeral=True)
    finally:
        try: os.remove(filename)
        except: pass
@bot.tree.command(name="leave", description="Force le bot à quitter le vocal")
async def leave(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if vc:
        try: await vc.disconnect(force=True)
        except Exception as e:
            await interaction.followup.send("Erreur lors de la déconnexion du salon vocal.", ephemeral=True)
        else:
            await interaction.followup.send("Je quitte le salon vocal.", ephemeral=True)
    else:
        await interaction.followup.send("Le bot n'est pas connecté à un salon vocal sur ce serveur.", ephemeral=True)
@bot.tree.command(name="penis", description="Joue un son spécial !")
async def penis(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    file = os.path.join(AUDIO_DIR, "sort-pas-ton-penis.mp3")
    try:
        await asyncio.wait_for(play_audio(interaction, file), timeout=30)
    except Exception as exc:
        msg = "Erreur : le fichier audio n'a pas été trouvé." if isinstance(exc, FileNotFoundError) \
                else f"Erreur pendant la lecture : {exc}"
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans votre salon vocal.", ephemeral=True)
@bot.tree.command(name="say-tc", description="Fait afficher un texte dans le channel")
@app_commands.describe(message="Texte à afficher")
async def say_tc(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)
async def say_with_tts(interaction, message, voice, instructions):
    if not (interaction.user.voice and interaction.user.voice.channel):
        await interaction.followup.send("Vous devez être connecté à un salon vocal.", ephemeral=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        filename = tmp.name
    loop = asyncio.get_running_loop()
    try:
        success = await asyncio.wait_for(
            loop.run_in_executor(None, run_tts, message, filename, voice, instructions),
            timeout=20
        )
        if not success: raise Exception("Erreur lors de la génération de la synthèse vocale.")
        await asyncio.wait_for(play_audio(interaction, filename), timeout=30)
    except Exception as exc:
        await interaction.followup.send(f"Erreur : {exc}", ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans votre salon vocal.", ephemeral=True)
    finally:
        try: os.remove(filename)
        except: pass
@bot.tree.command(
    name="say-vc",
    description="Fait lire du texte en vocal (accent québécois personnalisable)"
)
@app_commands.describe(
    message="Texte à lire",
    instructions="Instructions personnalisées pour cette lecture vocale",
    sauvegarder_instructions="Si vrai, utiliser ces instructions aussi pour les prochaines lectures sur ce serveur pendant 24h."
)
async def say_vc(
    interaction: discord.Interaction,
    message: str,
    instructions: str = None,
    sauvegarder_instructions: bool = False
):
    gid = interaction.guild.id if interaction.guild else None
    await interaction.response.defer(thinking=True, ephemeral=True)
    if instructions is not None and sauvegarder_instructions:
        _guild_sayvc_instructions[gid] = instructions
        _cancel_task(_guild_sayvc_reset_task.get(gid))
        _guild_sayvc_reset_task[gid] = asyncio.create_task(_delayed_reset_sayvc(gid))
        info = "(Les instructions seront utilisées sur ce serveur pendant 24h.)"
    else:
        info = ""
    current_instructions = instructions if instructions is not None else _guild_sayvc_instructions[gid]
    await say_with_tts(interaction, message, "ash", current_instructions)
    if info:
        await interaction.followup.send(info, ephemeral=True)
@bot.tree.command(
    name="gpt",
    description="Pose une question à GPT-4o Azure et lis la réponse en vocal"
)
@app_commands.describe(
    query="Ce que tu demandes à GPT",
    lecture_vocale="Lire la réponse dans le salon vocal",
    prompt="Prompt système personnalisé (optionnel)",
    sauvegarder_prompt="Si vrai, mémoriser ce prompt sur ce serveur pour 24h"
)
async def gpt(
    interaction: discord.Interaction,
    query: str,
    lecture_vocale: bool = True,
    prompt: str = None,
    sauvegarder_prompt: bool = False
):
    gid = interaction.guild.id if interaction.guild else None
    if prompt is not None and sauvegarder_prompt:
        _guild_gpt_prompt[gid] = prompt
        _cancel_task(_guild_gpt_prompt_reset_task.get(gid))
        _guild_gpt_prompt_reset_task[gid] = asyncio.create_task(_delayed_reset_gpt(gid))
        info = "(Le prompt GPT sera utilisé sur ce serveur pendant 24h.)"
    else:
        info = ""
    system_prompt = prompt if prompt is not None else _guild_gpt_prompt[gid]
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    try:
        reply = await asyncio.wait_for(
            loop.run_in_executor(None, run_gpt, query, system_prompt),
            timeout=22
        )
    except Exception as ex:
        await interaction.followup.send(f"Erreur pendant l'appel à GPT : {ex}")
        return
    embed = discord.Embed(title="Réponse GPT-4o", color=0x00bcff, description=f"**Q :** {query}")
    maxlen = 1024
    chunks = [reply[i:i+maxlen] for i in range(0, len(reply), maxlen)]
    for idx, chunk in enumerate(chunks[:25]):
        name = "Réponse" if idx == 0 else f"(suite {idx})"
        embed.add_field(name=name, value=chunk, inline=False)
    if len(chunks) > 25:
        embed.add_field(name="Info", value="(réponse tronquée, trop longue pour Discord !)", inline=False)
    await interaction.followup.send(embed=embed)
    if info:
        await interaction.followup.send(info)
    if lecture_vocale and interaction.user.voice and interaction.user.voice.channel and reply:
        short_reply = reply[:500]
        instructions = "Lis la réponse comme un assistant vocal naturel avec un ton informatif."
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            filename = tmp.name
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(None, run_tts, short_reply, filename, "ash", instructions),
                timeout=20
            )
            if success:
                await asyncio.wait_for(play_audio(interaction, filename), timeout=30)
        except Exception:
            pass
        finally:
            try: os.remove(filename)
            except: pass
        await interaction.followup.send("Réponse lue dans le salon vocal.")
@bot.tree.command(name="help", description="Aide sur les commandes du bot")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="Commandes disponibles :", color=0x00bcff)
    embed.add_field(name="/help", value="Affiche ce message", inline=False)
    embed.add_field(name="/joke", value="Joue une blague Reddit en vocal", inline=False)
    embed.add_field(name="/jokeqc", value="Joue une blague québécoise locale", inline=False)
    embed.add_field(name="/penis", value="Joue un son spécial", inline=False)
    embed.add_field(name="/ping", value="Pong !", inline=False)
    embed.add_field(name="/leave", value="Force le bot à quitter le salon vocal.", inline=False)
    embed.add_field(name="/say-tc <texte>", value="Affiche le texte dans le salon textuel", inline=False)
    embed.add_field(name="/say-vc <texte>", value="Lecture vocale accent québécois (instructions personnalisables)", inline=False)
    embed.add_field(name="/gpt <question>", value="Pose une question à GPT-4o (Azure), réponse texte et audio", inline=False)
    embed.set_footer(text="Tous droits réservés à Jean")
    await interaction.response.send_message(embed=embed, ephemeral=True)
@bot.tree.command(name="reset-prompts", description="Réinitialise immédiatement les prompts et instructions TTS")
async def reset_prompts(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    gid = interaction.guild.id if interaction.guild else None
    _guild_gpt_prompt[gid] = DEFAULT_GPT_PROMPT
    _guild_sayvc_instructions[gid] = DEFAULT_SAYVC_INSTRUCTIONS
    _cancel_task(_guild_gpt_prompt_reset_task.get(gid))
    _guild_gpt_prompt_reset_task[gid] = None
    _cancel_task(_guild_sayvc_reset_task.get(gid))
    _guild_sayvc_reset_task[gid] = None
    await interaction.followup.send(
        f"Les prompts et instructions ont été réinitialisés sur ce serveur par {interaction.user.mention}. Le prompt GPT et les instructions TTS sont revenus à leur valeur par défaut.",
        ephemeral=True
    )
    logging.info(f"[{gid}] All prompts/instructions reset by {interaction.user}.")
@bot.event
async def on_app_command_error(interaction, error):
    try: await interaction.response.send_message(f"Erreur dans la commande : {error}", ephemeral=True)
    except: await interaction.followup.send(f"Erreur dans la commande : {error}", ephemeral=True)
    logging.error(f"Unhandled app command error: {error}")
if __name__ == "__main__":
    print("Starting bot... Jokes will fetch in background.")
    logging.info("Bot starting up. Jokes will fetch in background.")
    bot.run(config["token"])