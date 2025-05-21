import discord
from discord.ext import commands
import os
import random
import json
import asyncio
import requests
import tempfile
import logging

# Load configuration
with open("config.json", "r") as f:
    config = json.load(f)

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.voice_states = True

# Audio files directory
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

# --- External Joke Fetching Logic ---
REDDIT_SUBREDDITS = ["darkjokes", "jokes", "dadjokes"]
REDDIT_MAX_LENGTH = 300
REDDIT_HEADERS = {"User-Agent": "Mozilla/5.0"}

reddit_jokes_cache = []
reddit_shown_indices = set()

def fetch_all_jokes(url, headers, max_posts=1000):
    all_posts = []
    after = None
    while len(all_posts) < max_posts:
        paged_url = url + (f"&after={after}" if after else "")
        response = requests.get(paged_url, headers=headers)
        if response.status_code != 200:
            logging.warning(f"Failed to fetch jokes from Reddit: {paged_url} (status {response.status_code})")
            break
        data = response.json()
        posts = data["data"]["children"]
        if not posts:
            break
        all_posts.extend(posts)
        after = data["data"].get("after")
        if not after or len(posts) < 100:
            break
    logging.info(f"Fetched {len(all_posts)} posts from Reddit ({url})")
    return all_posts[:max_posts]

def get_reddit_jokes():
    logging.info("Loading jokes from Reddit...")
    all_posts = []
    for subreddit in REDDIT_SUBREDDITS:
        base_url = f"https://www.reddit.com/r/{subreddit}/top.json?t=year&limit=1000"
        posts = fetch_all_jokes(base_url, REDDIT_HEADERS, max_posts=1000)
        all_posts.extend(posts)
    seen = set()
    unique_posts = []
    for post in all_posts:
        title = post["data"]["title"]
        selftext = post["data"]["selftext"]
        joke_text = f"{title}. {selftext}".strip()
        if 0 < len(joke_text) <= REDDIT_MAX_LENGTH:
            key = joke_text.lower()
            if key not in seen:
                seen.add(key)
                unique_posts.append(post)
    logging.info(f"Loaded {len(unique_posts)} unique jokes from Reddit")
    return unique_posts

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
    response = requests.post(tts_url, headers=tts_headers, json=data)
    if response.status_code == 200:
        with open(filename, "wb") as f:
            f.write(response.content)
        logging.info(f"TTS audio generated and saved to {filename}")
        return True
    else:
        logging.error(f"TTS request failed: {response.status_code} {response.text}")
        return False

# Initialize bot
bot = commands.Bot(command_prefix=config["prefix"], intents=intents, help_command=None)

async def play_audio(ctx, file):
    """Helper to play an audio file (given path) in the user's voice channel."""
    if ctx.author.voice and ctx.author.voice.channel:
        file_path = file  # Already an absolute/relative path
        try:
            logging.info(f"Attempting to join voice channel: {ctx.author.voice.channel} for user: {ctx.author} in guild: {ctx.guild.name}")
            vc = await ctx.author.voice.channel.connect()
            logging.info(f"Playing audio file: {file_path}")
            vc.play(discord.FFmpegPCMAudio(file_path))
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            logging.info(f"Audio finished, disconnected from voice channel: {ctx.author.voice.channel}")
            # If playing a local file (jokeqc), show an embed with name
            if file_path.startswith(AUDIO_DIR):
                embed = discord.Embed(title="Joke De Jean", color=0x00bcff)
                embed.set_footer(text="Tout droit réservés à Jean")
                embed.add_field(name="Blague : ", value=os.path.basename(file_path).replace('.mp3', ''))
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

@bot.command()
async def ping(ctx):
    """Replies with Pong!"""
    await ctx.send("Pong !")
    logging.info(f"Ping command triggered by {ctx.author} in guild {ctx.guild.name}")
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: ping")

@bot.command()
async def jokeqc(ctx):
    """Joue une blague québécoise locale dans le salon vocal."""
    logging.info(f"JokeQC command triggered by {ctx.author} in guild {ctx.guild.name}")
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: jokeqc")
    file = random.choice(files)
    await play_audio(ctx, os.path.join(AUDIO_DIR, file))

@bot.command(name="joke")
async def joke(ctx):
    """Joue une blague dans le salon vocal."""
    global reddit_jokes_cache, reddit_shown_indices
    if not reddit_jokes_cache:
        await ctx.send("Aucune blague disponible.")
        logging.warning("No suitable jokes found in cache.")
        return
    unseen_indices = [i for i in range(len(reddit_jokes_cache)) if i not in reddit_shown_indices]
    if not unseen_indices:
        await ctx.send("Toutes les blagues ont été racontées. Relance le bot pour renouveler!")
        logging.info("All jokes have been shown. Resetting shown indices.")
        reddit_shown_indices = set()
        return
    idx = random.choice(unseen_indices)
    reddit_shown_indices.add(idx)
    post = reddit_jokes_cache[idx]
    title = post["data"]["title"]
    selftext = post["data"]["selftext"]
    joke = f"{title}. {selftext}".strip()
    logging.info(f"Joke command triggered by {ctx.author} in guild {ctx.guild.name} - Joke index: {idx}")
    if ctx.author.voice and ctx.author.voice.channel:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmpfile:
            filename = tmpfile.name
        tts_url = config.get("tts_url")
        api_key = config.get("api_key")
        success = joke_to_tts(joke, filename, tts_url, api_key)
        if success:
            try:
                await play_audio(ctx, filename)
                embed = discord.Embed(title="Voici ta blague !", color=0x00bcff)
                embed.add_field(name="Titre :", value=title, inline=False)
                await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send("Erreur lors de la lecture de la blague.")
                logging.error(f"Error playing joke audio: {e}")
            finally:
                os.remove(filename)
                logging.info(f"Temporary TTS file {filename} removed.")
        else:
            await ctx.send("Erreur lors de la génération de l'audio TTS.")
    else:
        await ctx.send("Vous devez être dans un voice channel pour entendre la blague.")
        logging.warning(f"User {ctx.author} tried to play a joke without being in a voice channel.")

@bot.command()
async def penis(ctx):
    """Plays a special sound in the user's voice channel."""
    logging.info(f"Penis command triggered by {ctx.author} in guild {ctx.guild.name}")
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: penis")
    file = "sort-pas-ton-penis.mp3"
    await play_audio(ctx, os.path.join(AUDIO_DIR, file))

@bot.command()
async def leave(ctx):
    """Disconnects the bot from the voice channel."""
    if ctx.author.voice and ctx.author.voice.channel:
        try:
            vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
            if vc:
                await vc.disconnect(force=True)
                logging.info(f"Bot disconnected from voice channel in guild {ctx.guild.name} by {ctx.author}")
        except Exception as e:
            logging.error(f"Error disconnecting from voice channel: {e}")
            print(e)

@bot.command()
async def say(ctx, *, message: str):
    """Makes the bot say a message and deletes the user's command."""
    logging.info(f"Say command triggered by {ctx.author} in guild {ctx.guild.name} with message: {message}")
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: say")
    try:
        await ctx.message.delete()
    except Exception:
        logging.warning(f"Failed to delete message for say command by {ctx.author}")
        pass
    await ctx.send(message)

@bot.command()
async def help(ctx):
    """Displays the list of commands."""
    logging.info(f"Help command triggered by {ctx.author} in guild {ctx.guild.name}")
    embed = discord.Embed(title="Commandes :", color=0x00bcff)
    embed.add_field(name="!help", value="Affiche ce message", inline=False)
    embed.add_field(name="!joke", value="Joue une blague", inline=False)
    embed.add_field(name="!jokeqc", value="Joue une blague québécoise locale", inline=False)
    embed.add_field(name="!penis", value="Joue un son spécial", inline=False)
    embed.add_field(name="!ping", value="Pong !", inline=False)
    embed.add_field(name="!say", value="Le bot affiche un message", inline=False)
    await ctx.send(embed=embed)

# ===== MAIN ENTRY POINT =====
if __name__ == "__main__":
    print("Fetching jokes, please wait...")
    reddit_jokes_cache = get_reddit_jokes()
    print(f"Fetched {len(reddit_jokes_cache)} jokes.")
    logging.info(f"Fetched {len(reddit_jokes_cache)} jokes from Reddit (startup).")
    bot.run(config["token"])