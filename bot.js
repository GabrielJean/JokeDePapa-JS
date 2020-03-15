const Discord = require('discord.js');
const client = new Discord.Client();

client.on('ready', () => {
  console.log(`Logged in as ${client.user.tag}!`);
});

client.on('message', msg => {
  if (msg.content === 'ping') {
    msg.reply('pong');
  }
});

client.on('message', async message => {
    // Voice only works in guilds, if the message does not come from a guild,
    // we ignore it
    if (!message.guild) return;
  
    if (message.content === '!joke') {
      // Only try to join the sender's voice channel if they are in one themselves
      if (message.member.voice.channel) {
        const connection = await message.member.voice.channel.join();
        const dispatcher = await connection.play('./Audio/canibale.flac');
        
      } else {
        message.reply('You need to join a voice channel first!');
      }
    }

    if (message.content === '!leave') {
        // Only try to join the sender's voice channel if they are in one themselves
        if (message.member.voice.channel) {
          const connection = await message.member.voice.channel.leave();
        } else {
          message.reply('You need to join a voice channel first!');
        }
      }
  });

client.login('NTMwODUzNDc2MTAwNjAzOTE0.Xm43gw.Wa2Eyk2r814AZpdaSE0HzhzdxUw');