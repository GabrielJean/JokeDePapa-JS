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
import time  # Pour le système de blocage
from datetime import datetime
from typing import Any, Dict
import threading

with open("config.json", "r") as f:
    config = json.load(f)

AUDIO_DIR = "./Audio"
REDDIT_SUBREDDITS = ["darkjokes", "jokes", "dadjokes"]
REDDIT_MAX_LENGTH = 350
REDDIT_HEADERS = {"User-Agent": "Mozilla/5.0"}
DEFAULT_GPT_PROMPT = config.get(
    "gpt_system_prompt",
    "You are a helpful assistant. Reply in the language in which the question is asked, either English or French."
)
DEFAULT_SAYVC_INSTRUCTIONS = config.get(
    "say_vc_instructions",
    "Utilise un accent québécois"
)
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
_voice_audio_queues = defaultdict(asyncio.Queue)
_voice_locks = defaultdict(asyncio.Lock)
_vc_blocks = defaultdict(dict)  # (guild_id, channel_id): {user_id: until_ts}

# ----- Historique commandes -----
HISTORY_FILE = "command_history.json"
_history_lock = threading.Lock()

def log_command(user: discord.User, command_name: str, options: Dict[str, Any]):
    entry = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "user_id": user.id,
        "user": str(user),
        "command": command_name,
        "params": options
    }
    with _history_lock:
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as src:
                    history = json.load(src)
            else:
                history = []
        except Exception:
            history = []
        history.append(entry)
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as out:
                json.dump(history, out, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error writing command history: {e}")

def get_recent_history(n=15):
    with _history_lock:
        try:
            if not os.path.exists(HISTORY_FILE):
                return []
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            logging.error(f"Error reading command history: {e}")
            return []
    return items[-n:] if len(items) > n else items

def log_command_decorator(func):
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        # Récupère options/params sous forme d’un dict propre
        param_names = func.__annotations__.keys()
        resolved = {}
        for k in param_names:
            if k == "interaction":
                continue
            if k in kwargs:
                v = kwargs[k]
            elif args:
                # essaye de deviner la position dans args
                argidx = list(param_names).index(k) - 1
                if argidx < len(args):
                    v = args[argidx]
                else:
                    v = None
            else:
                v = None
            # Si discord types (User, Channel...) => to string/preset
            try:
                if hasattr(v, "mention"):
                    v = v.mention
                elif hasattr(v, "name"):
                    v = str(v.name)
            except Exception:
                pass
            resolved[k] = v
        log_command(interaction.user, func.__name__, resolved)
        return await func(interaction, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper
# ----- Fin historique -----

def is_vc_blocked_for_user(guild_id, channel_id, user_list):
    """Return list of users in user_list that block this VC (clean expired first)."""
    now = time.time()
    blocks = _vc_blocks[(guild_id, channel_id)]
    expired = [uid for uid, until in blocks.items() if until < now]
    for uid in expired:
        del blocks[uid]
    return list(set(blocks.keys()) & set(user_list))

def get_voice_channel(interaction, specified: discord.VoiceChannel = None):
    if interaction.user.voice and interaction.user.voice.channel:
        return interaction.user.voice.channel
    elif specified:
        perms = specified.permissions_for(interaction.user)
        if perms.connect and perms.speak:
            return specified
    return None

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

async def play_audio(interaction, file_path, voice_channel):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} not found.")
    guild = interaction.guild
    gid = guild.id if guild else 0
    # LOGIQUE DE BLOCAGE
    channel_id = voice_channel.id
    members_in_channel = [m.id for m in voice_channel.members if not m.bot]
    blockers = is_vc_blocked_for_user(gid, channel_id, members_in_channel)
    if blockers:
        blocked_by = ", ".join(f"<@{uid}>" for uid in blockers)
        raise RuntimeError(f"Accès refusé : bloqué par {blocked_by}. Attends 2h ou demande à retirer le blocage.")
    queue = _voice_audio_queues[gid]
    lock = _voice_locks[gid]
    fut = asyncio.get_event_loop().create_future()
    await queue.put((file_path, fut, voice_channel, interaction))
    if not lock.locked():
        asyncio.create_task(_run_audio_queue(guild, queue, lock))
    await fut

async def _run_audio_queue(guild, queue, lock):
    async with lock:
        while not queue.empty():
            file_path, fut, voice_channel, interaction = await queue.get()
            try:
                vc = discord.utils.get(bot.voice_clients, guild=guild)
                if not vc or not vc.is_connected():
                    vc = await voice_channel.connect()
                elif vc.channel != voice_channel:
                    await vc.move_to(voice_channel)
                vc.play(discord.FFmpegPCMAudio(file_path))
                while vc.is_playing():
                    await asyncio.sleep(1)
                await vc.disconnect()
                fut.set_result(None)
            except Exception as e:
                fut.set_exception(e)
            finally:
                try:
                    if file_path.startswith(tempfile.gettempdir()) and os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as ex:
                    logging.warning(f"Erreur suppression fichier temp: {ex}")

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

@bot.tree.command(name="ping", description="Renvoie Pong !")
@log_command_decorator
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong !", ephemeral=True)

@bot.tree.command(name="bloque", description="Bloque le bot pour 2h de rejoindre ton vocal actuel")
@log_command_decorator
async def bloque(interaction: discord.Interaction):
    user = interaction.user
    if not user.voice or not user.voice.channel:
        await interaction.response.send_message(
            "Tu dois être dans un salon vocal pour bloquer le bot !", ephemeral=True)
        return
    guild = interaction.guild
    channel = user.voice.channel
    key = (guild.id, channel.id)
    _vc_blocks[key][user.id] = time.time() + 2 * 3600
    await interaction.response.send_message(
        f"🔒 Le bot ne peux rejoindre **{channel.name}** pour toi pendant 2h. Refais `/bloque` pour prolonger.",
        ephemeral=True)

@bot.tree.command(name="debloque", description="Enlève ton blocage dans le salon vocal")
@log_command_decorator
async def debloque(interaction: discord.Interaction):
    user = interaction.user
    if not user.voice or not user.voice.channel:
        await interaction.response.send_message(
            "Tu dois être dans un salon vocal pour débloquer ce salon !", ephemeral=True)
        return
    guild = interaction.guild
    channel = user.voice.channel
    key = (guild.id, channel.id)
    if user.id in _vc_blocks[key]:
        del _vc_blocks[key][user.id]
        await interaction.response.send_message(
            f"✅ Le blocage dans **{channel.name}** est retiré. Le bot peut à nouveau venir.", ephemeral=True)
    else:
        await interaction.response.send_message(
            f"Ce salon n’était pas bloqué par toi !", ephemeral=True)

@bot.tree.command(name="jokeqc", description="Blague québécoise mp3")
@app_commands.describe(voice_channel="Salon vocal cible (optionnel)")
@log_command_decorator
async def jokeqc(interaction: discord.Interaction, voice_channel: discord.VoiceChannel = None):
    await interaction.response.defer(thinking=True, ephemeral=True)
    file = random.choice(audio_files)
    vc_channel = get_voice_channel(interaction, voice_channel)
    if not vc_channel:
        await interaction.followup.send(
            "Vous devez être dans un salon vocal, ou préciser un vocal !", ephemeral=True)
        return
    try:
        await asyncio.wait_for(play_audio(interaction, os.path.join(AUDIO_DIR, file), vc_channel), timeout=30)
    except RuntimeError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
    except Exception as exc:
        msg = "Fichier audio non trouvé." if isinstance(exc, FileNotFoundError) \
                else f"Erreur pendant la lecture : {exc}"
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans le salon vocal.", ephemeral=True)

@bot.tree.command(name="joke", description="Blague Reddit en vocal")
@app_commands.describe(voice_channel="Salon vocal cible (optionnel)")
@log_command_decorator
async def joke(interaction: discord.Interaction, voice_channel: discord.VoiceChannel = None):
    await interaction.response.defer(thinking=True, ephemeral=True)
    global reddit_jokes_by_sub
    if not reddit_jokes_by_sub:
        await interaction.followup.send("Aucune blague pour le moment, réessaye plus tard.", ephemeral=True)
        return
    sub = random.choice(list(reddit_jokes_by_sub.keys()))
    posts = reddit_jokes_by_sub[sub]
    bias = 0.02
    weights = [math.exp(-bias * i) for i in range(len(posts))]
    idx = random.choices(range(len(posts)), weights=[w/sum(weights) for w in weights], k=1)[0]
    post = posts[idx]["data"]
    joke_text = f"{post['title']}. {post['selftext']}".strip()
    vc_channel = get_voice_channel(interaction, voice_channel)
    if not vc_channel:
        await interaction.followup.send(
            "Vous devez être dans un salon vocal, ou préciser un vocal !", ephemeral=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        filename = tmp.name
    loop = asyncio.get_running_loop()
    try:
        success = await asyncio.wait_for(
            loop.run_in_executor(None, run_tts, joke_text, filename, "ash",
                                 "Read this joke with a comic tone, as if you are a stand-up comedian."),
            timeout=20
        )
        if not success: raise Exception("Erreur lors de la génération de la synthèse vocale.")
        await asyncio.wait_for(play_audio(interaction, filename, vc_channel), timeout=30)
    except RuntimeError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Erreur : {exc}", ephemeral=True)
    else:
        await interaction.followup.send("Blague lue dans le salon vocal.", ephemeral=True)
    finally:
        try: os.remove(filename)
        except: pass

@bot.tree.command(name="leave", description="Quitte le vocal")
@log_command_decorator
async def leave(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if vc:
        try: await vc.disconnect(force=True)
        except Exception as e:
            await interaction.followup.send("Erreur de déconnexion.", ephemeral=True)
        else:
            await interaction.followup.send("Je quitte le salon vocal.", ephemeral=True)
    else:
        await interaction.followup.send("Le bot n'est pas connecté au vocal.", ephemeral=True)

@bot.tree.command(name="penis", description="Joue un son spécial !")
@app_commands.describe(voice_channel="Salon vocal cible (optionnel)")
@log_command_decorator
async def penis(interaction: discord.Interaction, voice_channel: discord.VoiceChannel = None):
    await interaction.response.defer(thinking=True, ephemeral=True)
    file = os.path.join(AUDIO_DIR, "sort-pas-ton-penis.mp3")
    vc_channel = get_voice_channel(interaction, voice_channel)
    if not vc_channel:
        await interaction.followup.send(
            "Vous devez être dans un salon vocal, ou préciser un vocal !", ephemeral=True
        )
        return
    try:
        await asyncio.wait_for(play_audio(interaction, file, vc_channel), timeout=30)
    except RuntimeError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
    except Exception as exc:
        msg = "Fichier audio non trouvé." if isinstance(exc, FileNotFoundError) \
                else f"Erreur pendant la lecture : {exc}"
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans le salon vocal.", ephemeral=True)

@bot.tree.command(name="say-tc", description="Affiche le texte dans le salon texte")
@app_commands.describe(message="Texte à afficher")
@log_command_decorator
async def say_tc(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)

async def say_with_tts(interaction, message, voice, instructions, voice_channel):
    if not voice_channel:
        await interaction.followup.send("Vous devez être dans un salon vocal ou en préciser un.", ephemeral=True)
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
        await asyncio.wait_for(play_audio(interaction, filename, voice_channel), timeout=30)
    except RuntimeError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Erreur : {exc}", ephemeral=True)
    else:
        await interaction.followup.send("Lecture audio lancée dans le salon vocal.", ephemeral=True)
    finally:
        try: os.remove(filename)
        except: pass

@bot.tree.command(
    name="say-vc",
    description="Lecture TTS en vocal"
)
@app_commands.describe(
    message="Texte à lire",
    instructions="Style de la voix (optionnel)",
    sauvegarder_instructions="Réutiliser le style 24h",
    voice_channel="Salon vocal cible (optionnel)"
)
@log_command_decorator
async def say_vc(
    interaction: discord.Interaction,
    message: str,
    instructions: str = None,
    sauvegarder_instructions: bool = False,
    voice_channel: discord.VoiceChannel = None
):
    gid = interaction.guild.id if interaction.guild else None
    await interaction.response.defer(thinking=True, ephemeral=True)
    if instructions is not None and sauvegarder_instructions:
        _guild_sayvc_instructions[gid] = instructions
        _cancel_task(_guild_sayvc_reset_task.get(gid))
        _guild_sayvc_reset_task[gid] = asyncio.create_task(_delayed_reset_sayvc(gid))
        info = "(Style vocal sauvegardé 24h.)"
    else:
        info = ""
    vc_channel = get_voice_channel(interaction, voice_channel)
    if not vc_channel:
        await interaction.followup.send("Vous devez être dans un salon vocal ou en préciser un.", ephemeral=True)
        return
    current_instructions = instructions if instructions is not None else _guild_sayvc_instructions[gid]
    await say_with_tts(interaction, message, "ash", current_instructions, vc_channel)
    if info:
        await interaction.followup.send(info, ephemeral=True)

@bot.tree.command(
    name="gpt",
    description="Pose une question à GPT-4o puis lit la réponse"
)
@app_commands.describe(
    query="Question à GPT",
    lecture_vocale="Lire la réponse en vocal",
    prompt="Prompt optionnel",
    sauvegarder_prompt="Sauver ce prompt 24h"
)
@log_command_decorator
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
        info = "(Prompt GPT sauvegardé 24h.)"
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
        await interaction.followup.send(f"Erreur GPT : {ex}", ephemeral=True)
        return
    embed = discord.Embed(title="Réponse GPT-4o", color=0x00bcff, description=f"**Q :** {query}")
    maxlen = 1024
    chunks = [reply[i:i+maxlen] for i in range(0, len(reply), maxlen)]
    for idx, chunk in enumerate(chunks[:25]):
        name = "Réponse" if idx == 0 else f"(suite {idx})"
        embed.add_field(name=name, value=chunk, inline=False)
    if len(chunks) > 25:
        embed.add_field(name="Info", value="(réponse tronquée, trop longue !)", inline=False)
    await interaction.followup.send(embed=embed)
    if info:
        await interaction.followup.send(info)
    if lecture_vocale and (interaction.user.voice and interaction.user.voice.channel):
        vc_channel = interaction.user.voice.channel
    else:
        vc_channel = None
    if lecture_vocale and vc_channel and reply:
        short_reply = reply[:500]
        instructions = "Lis la réponse d'une voix naturelle avec un ton informatif."
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            filename = tmp.name
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(None, run_tts, short_reply, filename, "ash", instructions),
                timeout=20
            )
            if success:
                await asyncio.wait_for(play_audio(interaction, filename, vc_channel), timeout=30)
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            pass
        finally:
            try: os.remove(filename)
            except: pass
        await interaction.followup.send("Réponse lue dans le salon vocal.")

@bot.tree.command(
    name="roast",
    description="Roast drôle et custom (1 à 5)"
)
@app_commands.describe(
    cible="Cible du roast",
    intensite="Niveau (1: soft, 5: salé)",
    details="Infos/mèmes à exploiter",
    voice_channel="Salon vocal cible"
)
@log_command_decorator
async def roast(
    interaction: discord.Interaction,
    cible: discord.Member,
    intensite: int = 2,
    details: str = None,
    voice_channel: discord.VoiceChannel = None
):
    intensite = max(1, min(5, intensite))
    noms_intensite = {
        1: "très doux (taquin)",
        2: "moqueur",
        3: "grinçant",
        4: "salé",
        5: "franc-parler punchy"
    }
    username = cible.display_name if hasattr(cible, "display_name") else str(cible)
    ajout_details = ""
    if details:
        ajout_details = f" Utilise : {details}"
    prompt_gpt = (
        f"Fais un roast québécois sur '{username}'. "
        f"Niveau {intensite}/5 : {noms_intensite[intensite]}. "
        f"{ajout_details} "
        "Humour direct, accent québécois, max 4 phrases, pas d'intro."
    )
    titre = f"Roast de {username} (niv. {intensite})"
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    try:
        texte = await asyncio.wait_for(
            loop.run_in_executor(
                None, run_gpt, prompt_gpt,
                "Stand-up québécois, franc-parler et punch."
            ),
            timeout=18
        )
    except Exception as ex:
        await interaction.followup.send(
            f"Erreur génération roast: {ex}", ephemeral=True
        )
        return
    embed = discord.Embed(title=titre, description=texte, color=0xff8800 if intensite < 4 else 0xff0000)
    await interaction.followup.send(embed=embed)
    vc_channel = get_voice_channel(interaction, voice_channel)
    if vc_channel:
        instructions = "Lis ce roast façon humoriste québécois, franc-parler."
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            filename = tmp.name
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(None, run_tts, texte, filename, "ash", instructions),
                timeout=20
            )
            if success:
                await asyncio.wait_for(play_audio(interaction, filename, vc_channel), timeout=30)
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Erreur audio : {e}", ephemeral=True)
        finally:
            try: os.remove(filename)
            except: pass
        await interaction.followup.send("Roast balancé au vocal!", ephemeral=True)
    else:
        await interaction.followup.send("(Rejoins ou précise un salon vocal !)", ephemeral=True)

@bot.tree.command(
    name="compliment",
    description="Compliment personnalisé (fun)"
)
@app_commands.describe(
    cible="Ciblé du compliment",
    details="Infos à flatter",
    voice_channel="Salon vocal cible"
)
@log_command_decorator
async def compliment(
    interaction: discord.Interaction,
    cible: discord.Member,
    details: str = None,
    voice_channel: discord.VoiceChannel = None
):
    username = cible.display_name if hasattr(cible, "display_name") else str(cible)
    ajout_details = f" Met en valeur : {details}" if details else ""
    prompt_gpt = (
        f"Fais un compliment fun à '{username}'."
        f"{ajout_details} "
        "Accentu humoriste québécois, max 4 phrases."
    )
    titre = f"Compliment pour {username}"
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    try:
        texte = await asyncio.wait_for(
            loop.run_in_executor(None, run_gpt, prompt_gpt,
            "Compliments québécois."
        ),timeout=18)
    except Exception as ex:
        await interaction.followup.send(
            f"Erreur génération compliment: {ex}", ephemeral=True
        )
        return
    embed = discord.Embed(title=titre, description=texte, color=0x41d98e)
    await interaction.followup.send(embed=embed)
    vc_channel = get_voice_channel(interaction, voice_channel)
    if vc_channel:
        instructions = "Lis ce compliment façon humoriste québécois, émerveillé."
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp: filename = tmp.name
        try:
            success = await asyncio.wait_for(
                loop.run_in_executor(None, run_tts, texte, filename, "ash", instructions),
                timeout=20
            )
            if success:
                await asyncio.wait_for(play_audio(interaction, filename, vc_channel), timeout=30)
        except RuntimeError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Erreur audio : {e}", ephemeral=True)
        finally:
            try: os.remove(filename)
            except: pass
        await interaction.followup.send("Compliment lancé au vocal!", ephemeral=True)
    else:
        await interaction.followup.send("(Rejoins ou précise un salon vocal !)", ephemeral=True)

@bot.tree.command(name="help", description="Commandes du bot")
@log_command_decorator
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Aide - Commandes du bot",
        color=0x00bcff,
        description="La plupart des commandes vocales acceptent `voice_channel` (optionnel)."
    )
    embed.add_field(
        name="/joke",
        value="Joue une blague Reddit en vocal.\nParams: voice_channel",
        inline=False)
    embed.add_field(
        name="/jokeqc",
        value="Blague québécoise .mp3.\nParams: voice_channel",
        inline=False)
    embed.add_field(
        name="/penis",
        value="Joue un son spécial.\nParams: voice_channel",
        inline=False)
    embed.add_field(
        name="/say-vc",
        value="Lecture TTS personnalisée.\nParams: message, instructions, sauvegarder_instructions, voice_channel",
        inline=False)
    embed.add_field(
        name="/gpt",
        value="GPT-4o Q&A, réponse lue.\nParams: query, lecture_vocale, prompt, sauvegarder_prompt",
        inline=False
    )
    embed.add_field(
        name="/roast",
        value="Roast fun, accent québécois !\nParams: cible, intensite, details, voice_channel",
        inline=False
    )
    embed.add_field(
        name="/compliment",
        value="Compliment drôle/style québécois.\nParams: cible, details, voice_channel",
        inline=False
    )
    embed.add_field(
        name="/bloque",
        value="Bloque le bot pendant 2h de rejoindre ton salon vocal actuel.",
        inline=False
    )
    embed.add_field(
        name="/debloque",
        value="Débloque le bot de rejoindre ton salon vocal actuel.",
        inline=False
    )
    embed.add_field(
        name="/leave",
        value="Fait quitter le salon vocal au bot.",
        inline=False)
    embed.add_field(
        name="/say-tc",
        value="Affiche le texte dans le salon texte. Param: message",
        inline=False)
    embed.add_field(
        name="/reset-prompts",
        value="Reset les prompts/instructions TTS.",
        inline=False
    )
    embed.add_field(
        name="/history",
        value="Affiche les 15 dernières commandes (éphémère).",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="Affiche cette aide détaillée.",
        inline=False
    )
    embed.set_footer(text="Besoin d’être dans un vocal OU d'utiliser voice_channel=...  Utilisez /bloque pour être tranquille!")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="reset-prompts", description="Reset prompts et TTS")
@log_command_decorator
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
        f"Prompts/instructions réinitialisés sur ce serveur.",
        ephemeral=True
    )
    logging.info(f"[{gid}] All prompts/instructions reset by {interaction.user}.")

# ======== Commande historique ========
@bot.tree.command(name="history", description="Afficher tes 15 dernières commandes du bot (éphémère)")
@log_command_decorator
async def history(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    items = get_recent_history(15)
    if not items:
        await interaction.followup.send("Aucun historique de commandes trouvé.", ephemeral=True)
        return
    embed = discord.Embed(
        title=f"15 dernières commandes (tous users)",
        color=0xcccccc
    )
    for entry in items:
        t = entry["timestamp"]
        user = entry["user"]
        cmd = entry["command"]
        params = entry.get("params", {})
        ptxt = ', '.join(f"{k}={v!r}" for k, v in params.items() if v is not None)
        txt = f"`{t}` - **{user}** : /{cmd} {ptxt}"
        embed.add_field(name="\u200b", value=txt[:1000], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)
# ======== Fin historique =============

@bot.event
async def on_app_command_error(interaction, error):
    try: await interaction.response.send_message(f"Erreur commande : {error}", ephemeral=True)
    except: await interaction.followup.send(f"Erreur commande : {error}", ephemeral=True)
    logging.error(f"Unhandled app command error: {error}")

if __name__ == "__main__":
    print("Starting bot... Jokes will fetch in background.")
    logging.info("Bot starting up. Jokes will fetch in background.")
    bot.run(config["token"])