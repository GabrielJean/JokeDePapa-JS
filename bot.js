const { Client, GatewayIntentBits, Partials, EmbedBuilder } = require('discord.js');
const { joinVoiceChannel, createAudioPlayer, createAudioResource, AudioPlayerStatus, entersState, VoiceConnectionStatus } = require('@discordjs/voice');
const prompt = require('prompt');
const config = require("./config.json");
const fs = require('fs');
const path = require('path');

const files = fs.readdirSync('./Audio');

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildVoiceStates,
  ],
  partials: [Partials.Channel],
});

client.once('ready', () => {
  console.log(`Logged in as ${client.user.tag}!`);
  client.user.setPresence({ activities: [{ name: 'Type !help' }] });
});

client.on('messageCreate', async (message) => {
  if (message.author.bot) return;
  if (!message.guild) return;

  if (message.content === 'ping') {
    await message.reply('Pong !');
    console.log(
      "User " +
        message.member.user.tag +
        " from : " +
        message.guild.name +
        ", triggered : ping"
    );
    return;
  }

  if (!message.content.startsWith(config.prefix)) return;

  const args = message.content.slice(config.prefix.length).trim().split(/ +/g);
  const command = args.shift().toLowerCase();

  if (command === 'joke') {
    console.log(
      "User " +
        message.member.user.tag +
        " from : " +
        message.guild.name +
        ", triggered : " +
        command
    );
    if (message.member.voice.channel) {
      const file = files[Math.floor(Math.random() * files.length)];
      const filePath = path.join(__dirname, 'Audio', file);
      try {
        const connection = joinVoiceChannel({
          channelId: message.member.voice.channel.id,
          guildId: message.guild.id,
          adapterCreator: message.guild.voiceAdapterCreator,
        });

        await entersState(connection, VoiceConnectionStatus.Ready, 30_000);

        const player = createAudioPlayer();
        const resource = createAudioResource(filePath);

        connection.subscribe(player);
        player.play(resource);

        player.once(AudioPlayerStatus.Idle, () => {
          connection.destroy();
        });

        const embed = new EmbedBuilder()
          .setTitle('Joke De Jean')
          .setColor(0x00bcff)
          .setFooter({ text: 'Tout droit réservés à Jean' })
          .addFields({ name: 'Blague : ', value: file.replace('.flac', '') })
        await message.channel.send({ embeds: [embed] });
      } catch (err) {
        await message.reply('Erreur lors de la lecture de la blague.');
        console.log(err);
      }
    } else {
      await message.reply('Vous devez être dans un voice channel pour faire cela');
    }
    return;
  }

  if (command === 'leave') {
    if (message.member.voice.channel) {
      try {
        // Find and destroy the connection for this guild
        const connection = require('@discordjs/voice').getVoiceConnection(message.guild.id);
        if (connection) connection.destroy();
      } catch (err) {
        console.log(err);
      }
    }
    return;
  }

  if (command === 'say') {
    console.log(
      "User " +
        message.member.user.tag +
        " from : " +
        message.guild.name +
        ", triggered : " +
        command
    );
    if (args.length === 0) return;
    const sayMessage = args.join(" ");
    try {
      await message.delete();
    } catch (err) {}
    await message.channel.send(sayMessage);
    return;
  }

  if (command === 'help') {
    const embed = new EmbedBuilder()
      .setTitle('Commandes :')
      .setColor(0x00bcff)
      .addFields(
        { name: '!help', value: 'Affiche ce message' },
        { name: '!joke', value: 'Joue une blague' },
        { name: '!ping', value: 'Pong !' },
        { name: '!say', value: 'Le bot affiche un message' }
      )
    await message.channel.send({ embeds: [embed] });
    return;
  }
});

client.login(config.token);