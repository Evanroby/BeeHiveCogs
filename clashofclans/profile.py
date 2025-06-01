import discord
from discord.ext import commands

class ClashProfile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # In production, use persistent config
        self.user_tags = {}  # {discord_id: {"tag": str, "verified": bool}}
        # Assume dev_api_key is stored in bot's config or attribute

    async def get_dev_api_key(self):
        tokens = await self.bot.get_shared_api_tokens("clashofclans")
        return tokens.get("api_key")

    async def verify_coc_account(self, tag: str, user_apikey: str, dev_api_key: str) -> bool:
        """
        Verifies the user's Clash of Clans account using the provided tag and user API key.
        Uses the developer API key for authorization, and checks the /players/{playerTag}/verifytoken endpoint.
        """
        import aiohttp

        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/players/%23{tag}/verifytoken"
        headers = {
            "Authorization": f"Bearer {dev_api_key}",
            "Accept": "application/json"
        }
        payload = {
            "token": user_apikey
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                # API returns {"status": "ok"} if verified, {"status": "invalid"} otherwise
                return data.get("status") == "ok"

    @commands.group(name="clashprofile", invoke_without_command=True)
    async def clashprofile(self, ctx):
        """Clash of Clans profile commands."""
        await ctx.send("Available subcommands: link")

    @clashprofile.command(name="link")
    async def clashprofile_link(self, ctx, tag: str, apikey: str):
        """Set your Clash of Clans user tag and verify account ownership."""
        if not tag.startswith("#"):
            await ctx.send("Please provide a valid player tag starting with # (e.g. #ABC123).")
            return

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        verified = await self.verify_coc_account(tag, apikey, dev_api_key)
        if verified:
            self.user_tags[ctx.author.id] = {"tag": tag.upper(), "verified": True}
            await ctx.send(f"✅ Your Clash of Clans profile has been set and verified for tag {tag.upper()}!")
        else:
            await ctx.send("❌ Verification failed. Please ensure your tag and API key are correct and try again. Remember, the API key is a one-time use token from the in-game settings.")


