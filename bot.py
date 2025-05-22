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

# -------- CONFIG & GLOBALS --------
with open("config.json", "r") as f:
    config = json.load(f)

gpt_system_prompt_default = config.get(
    "gpt_system_prompt",
    "You are a helpful assistant. Reply in the language in which the question is asked, either English or French."
)
gpt_system_prompt = gpt_system_prompt_default
say_vc_instructions_default = config.get("say_vc_instructions", "Utilise un accent québécois")
say_vc_instructions = say_vc_instructions_default
gpt_prompt_reset_task = None
sayvc_reset_task = None

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.voice_states = True

AUDIO_DIR = "./Audio"
files = [f for f in os.listdir(AUDIO_DIR) if os.path.isfile(os.path.join(AUDIO_DIR, f)) and f.endswith('.mp3')]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

REDDIT_SUBREDDITS = ["darkjokes", "jokes", "dadjokes"]
REDDIT_MAX_LENGTH = 300
REDDIT_HEADERS = {"User-Agent": "Mozilla/5.0"}
reddit_jokes_by_sub = defaultdict(list)

# -------- UTILS --------
async def fetch_all_jokes_async(url, headers, max_posts=1000):
    loop = asyncio.get_event_loop()
    def fetch():
        all_posts = []
        after = None
        while len(all_posts) < max_posts:
            paged_url = url + (f"&after={after}" if after else "")
            try:
                response = requests.get(paged_url, headers=headers, timeout=10)
                response.raise_for_status()
            except Exception as ex:
                logging.warning(f"Network error: {ex}")
                break
            data = response.json()
            posts = data.get("data", {}).get("children", [])
            if not posts:
                break
            all_posts.extend(posts)
            after = data["data"].get("after")
            if not after or len(posts) < 100:
                break
        logging.info(f"Fetched {len(all_posts)} posts from Reddit ({url})")
        return all_posts[:max_posts]
    return await loop.run_in_executor(None, fetch)

async def get_reddit_jokes_async():
    logging.info("Loading jokes from Reddit asynchronously...")
    all_posts = []
    for subreddit in REDDIT_SUBREDDITS:
        base_url = f"https://www.reddit.com/r/{subreddit}/top.json?t=year&limit=100"
        posts = await fetch_all_jokes_async(base_url, REDDIT_HEADERS, max_posts=100)
        all_posts.extend(posts)
    seen = set()
    unique_posts_by_sub = defaultdict(list)
    for post in all_posts:
        title = post["data"]["title"]
        selftext = post["data"]["selftext"]
        joke_text = f"{title}. {selftext}".strip()
        if 0 < len(joke_text) <= REDDIT_MAX_LENGTH:
            key = joke_text.lower()
            if key not in seen:
                seen.add(key)
                sub = post["data"].get("subreddit", "unknown").lower()
                unique_posts_by_sub[sub].append(post)
    total = sum(len(lst) for lst in unique_posts_by_sub.values())
    logging.info(f"Loaded {total} unique jokes from Reddit in {len(unique_posts_by_sub)} subreddits.")
    return unique_posts_by_sub

def joke_to_tts(joke_text, filename, tts_url, api_key, instructions, voice="ash"):
    tts_headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "input": joke_text,
        "model": "gpt-4o-mini-tts",
        "voice": voice,
        "response_format": "mp3",
        "speed": 1.0,
        "instructions": instructions
    }
    try:
        response = requests.post(tts_url, headers=tts_headers, json=data, timeout=15)
        if response.status_code == 200:
            with open(filename, "wb") as f:
                f.write(response.content)
            logging.info(f"TTS audio generated and saved to {filename}")
            return True
        else:
            logging.error(f"TTS request failed: {response.status_code} {response.text}")
            return False
    except Exception as ex:
        logging.error(f"TTS network error: {ex}")
        return False

def azure_gpt_chat(query, azure_gpt_url, azure_api_key, system_prompt):
    headers = {
        "api-key": azure_api_key,
        "Content-Type": "application/json"
    }
    data = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ],
        "max_tokens": 400
    }
    try:
        response = requests.post(azure_gpt_url, headers=headers, json=data, timeout=20)
        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        else:
            logging.error(f"Azure GPT request failed: {response.status_code} {response.text}")
            return "Erreur : la réponse d'Azure OpenAI a échoué."
    except Exception as ex:
        logging.error(f"Azure GPT network error: {ex}")
        return "Erreur : impossible de contacter Azure OpenAI."

bot = commands.Bot(command_prefix="!", intents=intents)

async def reset_gpt_prompt_after_delay():
    global gpt_system_prompt, gpt_prompt_reset_task
    await asyncio.sleep(24 * 3600)
    gpt_system_prompt = gpt_system_prompt_default
    gpt_prompt_reset_task = None
    logging.info("gpt_system_prompt reset to default after 24h.")

async def reset_sayvc_prompt_after_delay():
    global say_vc_instructions, sayvc_reset_task
    await asyncio.sleep(24 * 3600)
    say_vc_instructions = say_vc_instructions_default
    sayvc_reset_task = None
    logging.info("say_vc_instructions reset to default after 24h.")

async def play_audio(interaction, file):
    if not os.path.exists(file):
        await interaction.response.send_message("Erreur : le fichier audio est introuvable.", ephemeral=True)
        logging.warning(f"File {file} not found.")
        return
    user = interaction.user
    if user.voice and user.voice.channel:
        vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
        try:
            if not vc or not vc.is_connected():
                vc = await user.voice.channel.connect()
            elif vc.channel != user.voice.channel:
                await vc.move_to(user.voice.channel)
            logging.info(f"Playing audio file: {file}")
            vc.play(discord.FFmpegPCMAudio(file))
            try:
                await interaction.response.send_message("(Lecture...)", ephemeral=True)
            except discord.InteractionResponded:
                pass
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            logging.info(f"Audio finished, disconnected from voice channel: {user.voice.channel}")
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message("Erreur lors de la lecture.", ephemeral=True)
            logging.error(f"Error playing audio: {e}")
    else:
        await interaction.response.send_message("Vous devez être dans un voice channel pour faire cela.", ephemeral=True)
        logging.warning(f"User {user} tried to play audio without being in a voice channel.")

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
    logging.info("Preloading Reddit jokes in background...")
    reddit_jokes_by_sub = await get_reddit_jokes_async()
    logging.info(f"Fetched jokes from Reddit (background).")

@bot.tree.command(description="Renvoie Pong ! (test de connexion)")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong !")

@bot.tree.command(description="Joue une blague québécoise (mp3)")
async def jokeqc(interaction: discord.Interaction):
    file = random.choice(files)
    await play_audio(interaction, os.path.join(AUDIO_DIR, file))

@bot.tree.command(description="Joue une blague Reddit en vocal")
async def joke(interaction: discord.Interaction):
    global reddit_jokes_by_sub
    if not reddit_jokes_by_sub:
        await interaction.response.send_message("Aucune blague disponible. Essaye dans quelques secondes.", ephemeral=True)
        logging.warning("No jokes in cache.")
        return
    subreddits = list(reddit_jokes_by_sub.keys())
    chosen_sub = random.choice(subreddits)
    posts = reddit_jokes_by_sub[chosen_sub]
    bias_factor = 0.02
    weights = [math.exp(-bias_factor * i) for i in range(len(posts))]
    total = sum(weights)
    weights = [w/total for w in weights]
    idx = random.choices(range(len(posts)), weights=weights, k=1)[0]
    post = posts[idx]
    title = post["data"]["title"]
    selftext = post["data"]["selftext"]
    joke_text = f"{title}. {selftext}".strip()
    logging.info(f"Slash-joke by {interaction.user} - {chosen_sub} idx {idx}")
    if interaction.user.voice and interaction.user.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config["tts_url"]
        api_key = config["api_key"]
        instructions = "Read this joke with a comic tone, as if you are a stand-up comedian."
        async with interaction.channel.typing():
            success = joke_to_tts(joke_text, filename, tts_url, api_key, instructions, voice="ash")
        if success:
            await play_audio(interaction, filename)
            try:
                embed = discord.Embed(title=f"Voici ta blague ! ({chosen_sub})", color=0x00bcff)
                embed.add_field(name="Titre :", value=title, inline=False)
                await interaction.followup.send(embed=embed)
            except Exception: pass
            finally:
                try: os.remove(filename)
                except Exception: pass
        else:
            await interaction.response.send_message("Erreur lors de la génération TTS.", ephemeral=True)
    else:
        await interaction.response.send_message("Vous devez être dans un vocal pour entendre la blague.", ephemeral=True)

@bot.tree.command(description="Force le bot à quitter le vocal")
async def leave(interaction: discord.Interaction):
    vc = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if vc:
        try:
            await vc.disconnect(force=True)
            await interaction.response.send_message("Je quitte le salon vocal !")
            logging.info(f"Bot forcibly disconnected from voice channel in guild {interaction.guild.name} by command (leave).")
        except Exception as e:
            await interaction.response.send_message("Erreur lors de la déconnexion du salon vocal.")
            logging.error(f"Error disconnecting from voice channel: {e}")
    else:
        await interaction.response.send_message("Je ne suis dans aucun salon vocal ici.")

@bot.tree.command(description="Joue un son spécial !")
async def penis(interaction: discord.Interaction):
    file = "sort-pas-ton-penis.mp3"
    await play_audio(interaction, os.path.join(AUDIO_DIR, file))

@bot.tree.command(description="Fait afficher un texte dans le channel")
@app_commands.describe(message="Texte à afficher")
async def say_tc(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)

@bot.tree.command(description="Fait lire du texte en vocal (accent québécois personnalisable)")
@app_commands.describe(message="Texte à lire")
async def say_vc(interaction: discord.Interaction, message: str):
    global say_vc_instructions
    if interaction.user.voice and interaction.user.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config["tts_url"]
        api_key = config["api_key"]
        async with interaction.channel.typing():
            success = joke_to_tts(message, filename, tts_url, api_key, say_vc_instructions, voice="ash")
        if success:
            await play_audio(interaction, filename)
            try: os.remove(filename)
            except Exception: pass
        else:
            await interaction.response.send_message("Erreur lors de la génération de l'audio TTS.", ephemeral=True)
    else:
        await interaction.response.send_message("Vous devez être dans un voice channel.", ephemeral=True)

@bot.tree.command(description="Fait lire du texte en vocal (gros accent africain noir francophone)")
@app_commands.describe(message="Texte à lire")
async def say_vc_noir(interaction: discord.Interaction, message: str):
    if interaction.user.voice and interaction.user.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config["tts_url"]
        api_key = config["api_key"]
        instructions = "Parle avec un très gros accent africain noir francophone stéréotypé. Comme un humoriste."
        async with interaction.channel.typing():
            success = joke_to_tts(message, filename, tts_url, api_key, instructions, voice="alloy")
        if success:
            await play_audio(interaction, filename)
            try: os.remove(filename)
            except Exception: pass
        else:
            await interaction.response.send_message("Erreur lors de la génération de l'audio TTS.", ephemeral=True)
    else:
        await interaction.response.send_message("Vous devez être dans un voice channel.", ephemeral=True)

@bot.tree.command(description="Modifie les instructions TTS pour /say_vc (tout le monde)")
@app_commands.describe(instructions="Nouvelles instructions")
async def say_vc_instructions_cmd(interaction: discord.Interaction, instructions: str):
    global say_vc_instructions, sayvc_reset_task
    say_vc_instructions = instructions
    await interaction.response.send_message(f"Nouvelles instructions pour /say_vc :\n```{instructions}```\n(Retour à la valeur par défaut dans 24h)", ephemeral=True)
    logging.info(f"say_vc_instructions updated by {interaction.user}: {instructions}")
    if sayvc_reset_task is not None and not sayvc_reset_task.done():
        sayvc_reset_task.cancel()
    sayvc_reset_task = asyncio.create_task(reset_sayvc_prompt_after_delay())

@bot.tree.command(description="Pose une question à GPT-4o Azure et lis la réponse en vocal")
@app_commands.describe(query="Ce que tu demandes à GPT")
async def gpt(interaction: discord.Interaction, query: str):
    global gpt_system_prompt
    azure_gpt_url = config["azure_gpt_url"]
    azure_api_key = config["api_key"]
    tts_url = config["tts_url"]
    await interaction.response.defer(thinking=True)
    reply = azure_gpt_chat(query, azure_gpt_url, azure_api_key, gpt_system_prompt)

    # Formatting answer as an embed "box", splits into multiple fields if needed
    embed = discord.Embed(
        title="Réponse GPT-4o",
        color=0x00bcff,
        description=f"**Q :** {query}"
    )
    maxlen = 1024
    chunks = [reply[i:i+maxlen] for i in range(0, len(reply), maxlen)]
    for idx, chunk in enumerate(chunks[:25]):
        name = "Réponse" if idx == 0 else f"(suite {idx})"
        embed.add_field(name=name, value=chunk, inline=False)
    if len(chunks) > 25:
        embed.add_field(
            name="Info",
            value="(réponse tronquée, trop longue pour Discord !)",
            inline=False
        )
    await interaction.followup.send(embed=embed)

    tts_message = reply[:500] if reply else ""
    if interaction.user.voice and interaction.user.voice.channel and reply:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        instructions = "Lis la réponse comme un assistant vocal naturel avec un ton informatif."
        success = joke_to_tts(tts_message, filename, tts_url, azure_api_key, instructions, voice="ash")
        if success:
            await play_audio(interaction, filename)
            try: os.remove(filename)
            except Exception: pass

@bot.tree.command(description="Modifie le system prompt pour /gpt (tout le monde)")
@app_commands.describe(prompt="Nouveau prompt système GPT")
async def gpt_prompt(interaction: discord.Interaction, prompt: str):
    global gpt_system_prompt, gpt_prompt_reset_task
    gpt_system_prompt = prompt
    await interaction.response.send_message(f"Nouveau prompt système pour /gpt :\n```{prompt}```\n(Retour à la valeur par défaut dans 24h)", ephemeral=True)
    logging.info(f"gpt system prompt updated by {interaction.user}: {prompt}")
    if gpt_prompt_reset_task is not None and not gpt_prompt_reset_task.done():
        gpt_prompt_reset_task.cancel()
    gpt_prompt_reset_task = asyncio.create_task(reset_gpt_prompt_after_delay())

@bot.tree.command(description="Aide sur les commandes du bot")
async def help(interaction: discord.Interaction):
    embed = discord.Embed(title="Commandes disponibles :", color=0x00bcff)
    embed.add_field(name="/help", value="Affiche ce message", inline=False)
    embed.add_field(name="/joke", value="Joue une blague Reddit en vocal", inline=False)
    embed.add_field(name="/jokeqc", value="Joue une blague québécoise locale", inline=False)
    embed.add_field(name="/penis", value="Joue un son spécial", inline=False)
    embed.add_field(name="/ping", value="Pong !", inline=False)
    embed.add_field(name="/leave", value="Forcer le bot à quitter le vocal.", inline=False)
    embed.add_field(name="/say_tc <texte>", value="Affiche le texte dans le channel", inline=False)
    embed.add_field(name="/say_vc <texte>", value="TTS accent québécois (instructions configurables)", inline=False)
    embed.add_field(name="/say_vc_instructions <texte>", value="Change instructions TTS de /say_vc", inline=False)
    embed.add_field(name="/say_vc_noir <texte>", value="TTS accent africain noir francophone", inline=False)
    embed.add_field(name="/gpt <question>", value="Question à GPT-4o (Azure), vocal et texte", inline=False)
    embed.add_field(name="/gpt_prompt <texte>", value="Change le prompt système pour /gpt", inline=False)
    embed.set_footer(text="Tous droits réservés à Jean")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Erreur dans la commande : {error}", ephemeral=True)
        logging.error(f"Unhandled app command error: {error}")

if __name__ == "__main__":
    print("Starting bot... Jokes will fetch in background.")
    logging.info("Bot starting up. Jokes will fetch in background.")
    bot.run(config["token"])