import discord
from discord.ext import commands

import aiohttp

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

    async def fetch_player_data(self, tag: str, dev_api_key: str):
        """
        Fetches player data from the Clash of Clans API.
        """
        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/players/%23{tag}"
        headers = {
            "Authorization": f"Bearer {dev_api_key}",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    @commands.group(name="clashprofile", invoke_without_command=True)
    async def clashprofile(self, ctx):
        """Clash of Clans profile commands."""
        await ctx.send("Available subcommands: link, info, achievements, troops, heroes, spells, labels")

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

    @clashprofile.command(name="info")
    async def clashprofile_info(self, ctx, tag: str = None):
        """Get general information about a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        embed = discord.Embed(
            title=f"{player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.green()
        )
        embed.add_field(name="Town Hall Level", value=player.get("townHallLevel", "N/A"))
        embed.add_field(name="Experience Level", value=player.get("expLevel", "N/A"))
        embed.add_field(name="Trophies", value=player.get("trophies", "N/A"))
        embed.add_field(name="Best Trophies", value=player.get("bestTrophies", "N/A"))
        embed.add_field(name="War Stars", value=player.get("warStars", "N/A"))
        embed.add_field(name="Attack Wins", value=player.get("attackWins", "N/A"))
        embed.add_field(name="Defense Wins", value=player.get("defenseWins", "N/A"))
        embed.add_field(name="Donations", value=player.get("donations", "N/A"))
        embed.add_field(name="Donations Received", value=player.get("donationsReceived", "N/A"))
        embed.add_field(name="Clan Capital Contributions", value=player.get("clanCapitalContributions", "N/A"))
        if player.get("clan"):
            clan = player["clan"]
            embed.add_field(name="Clan", value=f"{clan.get('name', 'N/A')} ({clan.get('tag', 'N/A')})", inline=False)
            badge_url = clan.get("badgeUrls", {}).get("medium")
            if badge_url:
                embed.set_thumbnail(url=badge_url)
        if player.get("league"):
            league = player["league"]
            embed.add_field(name="League", value=league.get("name", "N/A"))
            league_icon = league.get("iconUrls", {}).get("medium")
            if league_icon:
                embed.set_image(url=league_icon)
        embed.set_footer(text="Clash of Clans Player Info")
        await ctx.send(embed=embed)

    @clashprofile.command(name="achievements")
    async def clashprofile_achievements(self, ctx, tag: str = None):
        """Get a list of achievements for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        achievements = player.get("achievements", [])
        if not achievements:
            await ctx.send("No achievements found for this player.")
            return

        embed = discord.Embed(
            title=f"Achievements for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.gold()
        )
        for ach in achievements[:20]:  # Show up to 20 achievements
            stars = "⭐" * ach.get("stars", 0)
            embed.add_field(
                name=f"{ach.get('name', 'Unknown')} {stars}",
                value=f"{ach.get('info', '')}\nProgress: {ach.get('value', 0)}/{ach.get('target', 0)}\n{ach.get('completionInfo', '') or ''}",
                inline=False
            )
        if len(achievements) > 20:
            embed.set_footer(text=f"Showing first 20 of {len(achievements)} achievements.")
        await ctx.send(embed=embed)

    @clashprofile.command(name="troops")
    async def clashprofile_troops(self, ctx, tag: str = None):
        """Get a list of troops and their levels for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        troops = player.get("troops", [])
        if not troops:
            await ctx.send("No troops found for this player.")
            return

        embed = discord.Embed(
            title=f"Troops for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.blue()
        )
        troop_lines = []
        for troop in troops:
            troop_lines.append(f"{troop.get('name', 'Unknown')}: {troop.get('level', 0)}/{troop.get('maxLevel', 0)} ({troop.get('village', '')})")
        # Discord embed field value max length is 1024
        for i in range(0, len(troop_lines), 20):
            embed.add_field(
                name=f"Troops {i+1}-{min(i+20, len(troop_lines))}",
                value="\n".join(troop_lines[i:i+20]),
                inline=False
            )
        await ctx.send(embed=embed)

    @clashprofile.command(name="heroes")
    async def clashprofile_heroes(self, ctx, tag: str = None):
        """Get a list of heroes and their levels for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        heroes = player.get("heroes", [])
        if not heroes:
            await ctx.send("No heroes found for this player.")
            return

        embed = discord.Embed(
            title=f"Heroes for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.purple()
        )
        for hero in heroes:
            eq = hero.get("equipment", [])
            eq_str = ", ".join(f"{e.get('name', '')} (Lv{e.get('level', 0)})" for e in eq) if eq else "None"
            embed.add_field(
                name=f"{hero.get('name', 'Unknown')}: {hero.get('level', 0)}/{hero.get('maxLevel', 0)}",
                value=f"Equipment: {eq_str}",
                inline=False
            )
        await ctx.send(embed=embed)

    @clashprofile.command(name="spells")
    async def clashprofile_spells(self, ctx, tag: str = None):
        """Get a list of spells and their levels for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        spells = player.get("spells", [])
        if not spells:
            await ctx.send("No spells found for this player.")
            return

        embed = discord.Embed(
            title=f"Spells for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.teal()
        )
        spell_lines = []
        for spell in spells:
            spell_lines.append(f"{spell.get('name', 'Unknown')}: {spell.get('level', 0)}/{spell.get('maxLevel', 0)}")
        for i in range(0, len(spell_lines), 20):
            embed.add_field(
                name=f"Spells {i+1}-{min(i+20, len(spell_lines))}",
                value="\n".join(spell_lines[i:i+20]),
                inline=False
            )
        await ctx.send(embed=embed)

    @clashprofile.command(name="labels")
    async def clashprofile_labels(self, ctx, tag: str = None):
        """Get a list of labels for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_data = self.user_tags.get(ctx.author.id)
            if not user_data or not user_data.get("verified"):
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_data["tag"]

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        labels = player.get("labels", [])
        if not labels:
            await ctx.send("No labels found for this player.")
            return

        embed = discord.Embed(
            title=f"Labels for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.orange()
        )
        for label in labels:
            icon = label.get("iconUrls", {}).get("small")
            embed.add_field(
                name=label.get("name", "Unknown"),
                value=f"ID: {label.get('id', 'N/A')}",
                inline=True
            )
            if icon:
                embed.set_thumbnail(url=icon)
        await ctx.send(embed=embed)

