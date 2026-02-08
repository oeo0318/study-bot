import discord
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

bot = discord.Bot(intents = discord.Intents.all())

@bot.event
async def on_ready():
    print(f"{bot.user} is online")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    elif message.content == "hi":
        await message.channel.send("hi")

@bot.event
async def on_member_join(member):
    channelID = 1469151683111293096
    welcomeChannel = bot.get_channel(channelID)
    await welcomeChannel.send(f"{member.mention} 滾出去，誰讓你進來的")

bot.run(os.getenv('DISCORD_TOKEN'))

