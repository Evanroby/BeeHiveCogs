# This file can be used to initialize the cog and add it to the bot.

from .profile import ClashProfile

async def setup(bot):
    await bot.add_cog(ClashProfile(bot))
