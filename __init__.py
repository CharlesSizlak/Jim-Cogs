from .poke import PokeCog

def setup(bot):
    cog = PokeCog()
    cog.bot = bot
    bot.loop.create_task(cog.initialize())
    bot.add_cog(cog)
