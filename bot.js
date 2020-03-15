const { Client, MessageEmbed } = require('discord.js');
const client = new Client();
const fs = require('fs');

client.on('ready', () => {
  console.log(`Logged in as ${client.user.tag}!`);
});

client.on('message', msg => {
  if (msg.content === 'ping') {
    msg.reply('Pong !');
  }
});

client.on('message', async message => {
    // Voice only works in guilds, if the message does not come from a guild,
    // we ignore it
    if (!message.guild) return;
  
    if (message.content === '!joke') {
      // Only try to join the sender's voice channel if they are in one themselves
      if (message.member.voice.channel) {
        var file = files[Math.floor(Math.random() * files.length)]
        const connection = await message.member.voice.channel.join();
        const dispatcher = await connection.play('./Audio/'+ file);
        dispatcher.on("finish", () => {
            message.member.voice.channel.leave();
        })
        const embed = new MessageEmbed()
        // Set the title of the field
        .setTitle('Joke De Papa')
        // Set the color of the embed
        .setColor(0x00BCFF)
        // Set the main content of the embed
        .setFooter("Tout droit réservés à Gaboom Films")
        .addField("Blague : ", file.replace(".flac", ""))
        //Set the thumbnail of the embed
        .setThumbnail("https://cdn.shoplightspeed.com/shops/612132/files/6072039/randolph-jokes-de-papa-le-jeu-de-societe.jpg");
      // Send the embed to the same channel as the message
      message.channel.send(embed);
      } else {
        message.reply('Vous devez être dans un voice channel pour faire cela');
      }
    }

    if (message.content === '!leave') {
        // Only try to join the sender's voice channel if they are in one themselves
        if (message.member.voice.channel) {
          const connection = await message.member.voice.channel.leave();
        }
      }

    if (message.content === '!help') {
        const embed = new MessageEmbed()
        // Set the title of the field
        .setTitle('Commandes :')
        // Set the color of the embed
        .setColor(0x00BCFF)
        // Set the main content of the embed
        .addField("!help", "Affiche ce message")
        .addField("!joke", "Joue une blague")
        .addField("!ping", "Pong !")
        //Set the thumbnail of the embed
        .setThumbnail("https://cdn.shoplightspeed.com/shops/612132/files/6072039/randolph-jokes-de-papa-le-jeu-de-societe.jpg");
      // Send the embed to the same channel as the message
      message.channel.send(embed);
    }
  });

var files = fs.readdirSync("./Audio");
client.login('NTMwODUzNDc2MTAwNjAzOTE0.Xm5M5A.muWr8IPBEv2kPUSTvkYcY0QYBZA');