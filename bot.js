const { Client, MessageEmbed } = require('discord.js');
const prompt = require('prompt');
const config = require("./config.json");

const client = new Client();
const fs = require('fs');

const files = fs.readdirSync('./Audio');


// async function mgmConsole() {
//   prompt.get(['command'], function (err, result) {
//     if (err) { return onErr(err); }
//     if (result.command === "kill") {
//       process.kill()
//     }
//     mgmConsole()
//   });
// }

client.on('ready', () => {
  // eslint-disable-next-line no-console
  console.log(`Logged in as ${client.user.tag}!`);
  client.user.setPresence({ activity: { name: 'type !help' }})
});

client.on('message', (msg) => {
  if (msg.content === 'ping') {
    msg.reply('Pong !');
    console.log("User " + message.member.user.tag + " from : " + message.guild.name + ", triggered : " + command )
  }
});

client.on('message', async (message) => {
  // Voice only works in guilds, if the message does not come from a guild,
  // we ignore it
  if (!message.guild) return;

  if(message.content.indexOf(config.prefix) !== 0) return;

  const args = message.content.slice(config.prefix.length).trim().split(/ +/g);
  const command = args.shift().toLowerCase();

  if (command === 'joke') {
    console.log("User " + message.member.user.tag + " from : " + message.guild.name + ", triggered : " + command )
    // Only try to join the sender's voice channel if they are in one themselves
    if (message.member.voice.channel) {
      const file = files[Math.floor(Math.random() * files.length)];
      const connection = await message.member.voice.channel.join();
      const dispatcher = await connection.play(`./Audio/${file}`);
      dispatcher.on('finish', () => {
        try {
          message.member.voice.channel.leave();
        } catch (error) {
          // eslint-disable-next-line no-console
          console.log(error);
        }
      });
      const embed = new MessageEmbed()
        // Set the title of the field
        .setTitle('Joke De Papa')
        // Set the color of the embed
        .setColor(0x00bcff)
        // Set the main content of the embed
        .setFooter('Tout droit réservés à Gaboom Films')
        .addField('Blague : ', file.replace('.flac', ''))
        // Set the thumbnail of the embed
        .setThumbnail(
          'https://cdn.shoplightspeed.com/shops/612132/files/6072039/randolph-jokes-de-papa-le-jeu-de-societe.jpg',
        );
      // Send the embed to the same channel as the message
      message.channel.send(embed);
    } else {
      message.reply('Vous devez être dans un voice channel pour faire cela');
    }
  }

  if (command === "leave") {
    // Only try to join the sender's voice channel if they are in one themselves
    if (message.member.voice.channel) {
      // eslint
      await message.member.voice.channel.leave();
    }
  }

  if(command === "say") {
    console.log("User " + message.member.user.tag + " from : " + message.guild.name + ", triggered : " + command )
    // makes the bot say something and delete the message. As an example, it's open to anyone to use. 
    // To get the "message" itself we join the `args` back into a string with spaces: 
    if (message === ""){return}
    const sayMessage = args.join(" ");
    // Then we delete the command message (sneaky, right?). The catch just ignores the error with a cute smiley thing.
    message.delete().catch(O_o=>{}); 
    // And we get the bot to say the thing: 
    message.channel.send(sayMessage);
  }

  if (command === 'help') {
    const embed = new MessageEmbed()
      // Set the title of the field
      .setTitle('Commandes :')
      // Set the color of the embed
      .setColor(0x00bcff)
      // Set the main content of the embed
      .addField('!help', 'Affiche ce message')
      .addField('!joke', 'Joue une blague')
      .addField('!ping', 'Pong !')
      .addField('!say', 'Le bot affiche un message')
      // Set the thumbnail of the embed
      .setThumbnail(
        'https://cdn.shoplightspeed.com/shops/612132/files/6072039/randolph-jokes-de-papa-le-jeu-de-societe.jpg',
      );
    // Send the embed to the same channel as the message
    message.channel.send(embed);
  }
});

// setTimeout(function () {
//   mgmConsole(); 
// }, 1000);
client.login(config.token)