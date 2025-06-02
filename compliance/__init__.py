from .compliance import ComplianceManager

async def setup(bot):
    await bot.add_cog(ComplianceManager(bot))
