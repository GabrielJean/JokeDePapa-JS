import discord
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

# Load configuration
with open("config.json", "r") as f:
    config = json.load(f)

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.voice_states = True

AUDIO_DIR = "./Audio"
files = [f for f in os.listdir(AUDIO_DIR) if os.path.isfile(os.path.join(AUDIO_DIR, f)) and f.endswith('.mp3')]

# Setup logging
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

def joke_to_tts(joke_text, filename, tts_url, api_key):
    tts_headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "input": joke_text,
        "model": "gpt-4o-mini-tts",
        "voice": "ash",
        "response_format": "mp3",
        "speed": 1.0,
        "instructions": "Read this joke with a comic tone, as if you are a stand-up comedian."
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

bot = commands.Bot(command_prefix=config["prefix"], intents=intents, help_command=None)

async def play_audio(ctx, file):
    if not os.path.exists(file):
        await ctx.send("Erreur : le fichier audio est introuvable.")
        logging.warning(f"File {file} not found.")
        return

    if ctx.author.voice and ctx.author.voice.channel:
        vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        try:
            if not vc or not vc.is_connected():
                vc = await ctx.author.voice.channel.connect()
            elif vc.channel != ctx.author.voice.channel:
                await vc.move_to(ctx.author.voice.channel)
            logging.info(f"Playing audio file: {file}")
            vc.play(discord.FFmpegPCMAudio(file))
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            logging.info(f"Audio finished, disconnected from voice channel: {ctx.author.voice.channel}")
            if file.startswith(AUDIO_DIR):
                embed = discord.Embed(title="Joke De Jean", color=0x00bcff)
                embed.set_footer(text="Tout droit réservés à Jean")
                embed.add_field(name="Blague : ", value=os.path.basename(file).replace('.mp3', ''))
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("Erreur lors de la lecture de la blague.")
            logging.error(f"Error playing audio: {e}")
    else:
        await ctx.send("Vous devez être dans un voice channel pour faire cela")
        logging.warning(f"User {ctx.author} tried to play audio without being in a voice channel.")

@bot.event
async def on_ready():
    logging.info(f"Bot logged in as {bot.user}!")
    print(f"Logged in as {bot.user}!")
    await bot.change_presence(activity=discord.Game(name="Type !help"))
    preload_jokes_task.start()

@tasks.loop(count=1)
async def preload_jokes_task():
    global reddit_jokes_by_sub
    await asyncio.sleep(2)
    logging.info("Preloading Reddit jokes in background...")
    reddit_jokes_by_sub = await get_reddit_jokes_async()
    logging.info(f"Fetched jokes from Reddit (background).")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong !")
    logging.info(f"Ping command triggered by {ctx.author} in guild {ctx.guild.name}")

@bot.command()
async def jokeqc(ctx):
    logging.info(f"JokeQC command triggered by {ctx.author} in guild {ctx.guild.name}")
    file = random.choice(files)
    await play_audio(ctx, os.path.join(AUDIO_DIR, file))

@bot.command(name="joke")
async def joke(ctx):
    global reddit_jokes_by_sub
    if not reddit_jokes_by_sub:
        await ctx.send("Aucune blague disponible. Essaye encore dans quelques secondes (chargement Reddit).")
        logging.warning("No suitable jokes found in cache.")
        return

    # Pick a subreddit at random
    subreddits = list(reddit_jokes_by_sub.keys())
    chosen_sub = random.choice(subreddits)
    posts = reddit_jokes_by_sub[chosen_sub]

    # Top-weighted bias - always from full list
    bias_factor = 0.02
    weights = [math.exp(-bias_factor * i) for i in range(len(posts))]
    total = sum(weights)
    weights = [w/total for w in weights]
    idx = random.choices(range(len(posts)), weights=weights, k=1)[0]

    post = posts[idx]
    title = post["data"]["title"]
    selftext = post["data"]["selftext"]
    joke_text = f"{title}. {selftext}".strip()
    logging.info(f"Joke command triggered by {ctx.author} in guild {ctx.guild.name} - Subreddit: {chosen_sub} - Index: {idx}")

    if ctx.author.voice and ctx.author.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config.get("tts_url")
        api_key = config.get("api_key")
        success = joke_to_tts(joke_text, filename, tts_url, api_key)
        if success:
            try:
                await play_audio(ctx, filename)
                embed = discord.Embed(title=f"Voici ta blague ! ({chosen_sub})", color=0x00bcff)
                embed.add_field(name="Titre :", value=title, inline=False)
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send("Erreur lors de la lecture de la blague.")
                logging.error(f"Error playing joke audio: {e}")
            finally:
                try:
                    os.remove(filename)
                    logging.info(f"Temporary TTS file {filename} removed.")
                except Exception as e:
                    logging.warning(f"Could not remove temporary file {filename} ({e})")
        else:
            await ctx.send("Erreur lors de la génération de l'audio TTS.")
    else:
        await ctx.send("Vous devez être dans un voice channel pour entendre la blague.")
        logging.warning(f"User {ctx.author} tried to play a joke without being in a voice channel.")

@bot.command()
async def penis(ctx):
    logging.info(f"Penis command triggered by {ctx.author} in guild {ctx.guild.name}")
    file = "sort-pas-ton-penis.mp3"
    await play_audio(ctx, os.path.join(AUDIO_DIR, file))

@bot.command()
async def leave(ctx):
    if ctx.author.voice and ctx.author.voice.channel:
        try:
            vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
            if vc:
                await vc.disconnect(force=True)
                logging.info(f"Bot disconnected from voice channel in guild {ctx.guild.name} by {ctx.author}")
        except Exception as e:
            await ctx.send("Erreur lors de la déconnexion du salon vocal.")
            logging.error(f"Error disconnecting from voice channel: {e}")

@bot.command(name="say-tc")
async def say_tc(ctx, *, message: str):
    """Bot says a message in the text channel (and deletes the user command)."""
    logging.info(f"say-tc command by {ctx.author} in guild {ctx.guild.name} with message: {message}")
    try:
        await ctx.message.delete()
    except Exception:
        logging.warning(f"Failed to delete message for say-tc by {ctx.author}")
    await ctx.send(message)

@bot.command(name="say-vc")
async def say_vc(ctx, *, message: str):
    """Reads the message with TTS in the user's voice channel."""
    logging.info(f"say-vc command by {ctx.author} in guild {ctx.guild.name} with message: {message}")
    if ctx.author.voice and ctx.author.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config.get("tts_url")
        api_key = config.get("api_key")
        success = joke_to_tts(message, filename, tts_url, api_key)
        if success:
            try:
                await play_audio(ctx, filename)
            except Exception as e:
                await ctx.send("Erreur lors de la lecture TTS.")
                logging.error(f"Error playing TTS audio: {e}")
            finally:
                try:
                    os.remove(filename)
                    logging.info(f"Temporary TTS file {filename} removed.")
                except Exception as e:
                    logging.warning(f"Could not remove temporary file {filename} ({e})")
        else:
            await ctx.send("Erreur lors de la génération de l'audio TTS.")
    else:
        await ctx.send("Vous devez être dans un voice channel pour entendre le message.")
        logging.warning(f"User {ctx.author} tried to use say-vc without being in a voice channel.")

@bot.command()
async def help(ctx):
    embed = discord.Embed(title="Commandes :", color=0x00bcff)
    embed.add_field(name="!help", value="Affiche ce message", inline=False)
    embed.add_field(name="!joke", value="Joue une blague depuis un subreddit aléatoire (top favorisées)", inline=False)
    embed.add_field(name="!jokeqc", value="Joue une blague québécoise locale", inline=False)
    embed.add_field(name="!penis", value="Joue un son spécial", inline=False)
    embed.add_field(name="!ping", value="Pong !", inline=False)
    embed.add_field(name="!say-tc <texte>", value="Le bot affiche le texte dans le channel texte", inline=False)
    embed.add_field(name="!say-vc <texte>", value="Le bot lit le texte en vocal via TTS", inline=False)
    embed.set_footer(text="Tout droit réservés à Jean")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Commande inconnue ! Tape !help pour voir la liste.")
    else:
        await ctx.send("Erreur lors de l'exécution de la commande.")
        logging.error(f"Unhandled command error: {error}")

# ===== MAIN ENTRY POINT =====
if __name__ == "__main__":
    print("Starting bot... Jokes will fetch in background.")
    logging.info("Bot starting up. Jokes will fetch in background.")
    bot.run(config["token"])