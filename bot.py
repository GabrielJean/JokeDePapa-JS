import discord
from discord.ext import commands
import os
import random
import json
import asyncio

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
files = [f for f in os.listdir(AUDIO_DIR) if os.path.isfile(os.path.join(AUDIO_DIR, f))]

# Initialize bot
bot = commands.Bot(command_prefix=config["prefix"], intents=intents, help_command=None)

async def play_audio(ctx, file):
    """Helper to play an audio file in the user's voice channel."""
    if ctx.author.voice and ctx.author.voice.channel:
        file_path = os.path.join(AUDIO_DIR, file)
        try:
            vc = await ctx.author.voice.channel.connect()
            vc.play(discord.FFmpegPCMAudio(file_path))
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            embed = discord.Embed(title="Joke De Jean", color=0x00bcff)
            embed.set_footer(text="Tout droit réservés à Jean")
            embed.add_field(name="Blague : ", value=file.replace('.flac', ''))
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send("Erreur lors de la lecture de la blague.")
            print(e)
    else:
        await ctx.send("Vous devez être dans un voice channel pour faire cela")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    await bot.change_presence(activity=discord.Game(name="Type !help"))

@bot.command()
async def ping(ctx):
    """Replies with Pong!"""
    await ctx.send("Pong !")
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: ping")

@bot.command()
async def joke(ctx):
    """Plays a random joke in the user's voice channel."""
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: joke")
    file = random.choice(files)
    await play_audio(ctx, file)

@bot.command()
async def penis(ctx):
    """Plays a special sound in the user's voice channel."""
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: penis")
    file = "sort-pas-ton-penis.flac"
    await play_audio(ctx, file)

@bot.command()
async def leave(ctx):
    """Disconnects the bot from the voice channel."""
    if ctx.author.voice and ctx.author.voice.channel:
        try:
            vc = discord.utils.get(bot.voice_clients, guild=ctx.guild)
            if vc:
                await vc.disconnect(force=True)
        except Exception as e:
            print(e)

@bot.command()
async def say(ctx, *, message: str):
    """Makes the bot say a message and deletes the user's command."""
    print(f"User {ctx.author} from: {ctx.guild.name}, triggered: say")
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(message)

@bot.command()
async def help(ctx):
    """Displays the list of commands."""
    embed = discord.Embed(title="Commandes :", color=0x00bcff)
    embed.add_field(name="!help", value="Affiche ce message", inline=False)
    embed.add_field(name="!joke", value="Joue une blague", inline=False)
    embed.add_field(name="!penis", value="Joue un son spécial", inline=False)
    embed.add_field(name="!ping", value="Pong !", inline=False)
    embed.add_field(name="!say", value="Le bot affiche un message", inline=False)
    await ctx.send(embed=embed)

# Start the bot
bot.run(config["token"])