import discord
from redbot.core import commands, Config  # Use Red's commands base and Config for persistence
import math
import aiohttp
from io import BytesIO
from PIL import Image

class ClashProfile(commands.Cog):  # Inherit from Red's commands.Cog
    """Clash of Clans profile commands."""

    def __init__(self, bot):
        super().__init__()  # Ensure proper Cog initialization
        self.bot = bot
        # Use Red's Config for persistent, per-user, global storage
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_user = {"tag": None, "verified": False}
        self.config.register_user(**default_user)
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

    @commands.group(name="clashprofile")
    async def clashprofile(self, ctx):
        """Clash of Clans profile commands."""

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
            await self.config.user(ctx.author).tag.set(tag.upper())
            await self.config.user(ctx.author).verified.set(True)
            await ctx.send(f"✅ Your Clash of Clans profile has been set and verified for tag {tag.upper()}!")
        else:
            await self.config.user(ctx.author).tag.set(None)
            await self.config.user(ctx.author).verified.set(False)
            await ctx.send("❌ Verification failed. Please ensure your tag and API key are correct and try again. Remember, the API key is a one-time use token from the in-game settings.")

    @clashprofile.command(name="info")
    async def clashprofile_info(self, ctx, tag: str = None):
        """Get general information about a Clash of Clans player."""

        async def get_brightest_color_from_url(url):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return None
                        data = await resp.read()
                with Image.open(BytesIO(data)) as img:
                    img = img.convert("RGBA").resize((32, 32))
                    pixels = list(img.getdata())
                    # Remove fully transparent pixels
                    pixels = [p for p in pixels if p[3] > 0]
                    if not pixels:
                        return None
                    # Find the pixel with the highest "richness" (brightness and saturation)
                    def color_richness(p):
                        r, g, b, a = p
                        # Convert to HSV to get brightness and saturation
                        import colorsys
                        h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                        # Richness: prioritize value (brightness) and saturation
                        return v * 0.7 + s * 0.3
                    brightest = max(pixels, key=color_richness)
                    return discord.Color.from_rgb(brightest[0], brightest[1], brightest[2])
            except Exception:
                return None

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        # Default color
        embed_color = discord.Color.green()

        # Try to get the league badge color if available
        league_icon = None
        if player.get("league"):
            league = player["league"]
            league_icon = league.get("iconUrls", {}).get("medium")
            if league_icon:
                color = await get_brightest_color_from_url(league_icon)
                if color:
                    embed_color = color

        # Determine role label for tag
        role_label = ""
        player_role = player.get("role", "").lower()
        if player_role == "admin":
            role_label = " Elder"
        elif player_role == "coleader":
            role_label = " Co-Leader"

        embed = discord.Embed(
            title=f"{player.get('name', 'Unknown')}",
            description=f"{role_label}\n-# {player.get('tag', tag)}",
            color=embed_color
        )
        embed.add_field(name="Town hall", value=player.get("townHallLevel", "N/A"), inline=True)
        embed.add_field(name="Experience level", value=player.get("expLevel", "N/A"), inline=True)
        if player.get("clan"):
            clan = player["clan"]
            embed.add_field(name="Clan", value=f"{clan.get('name', 'N/A')} ({clan.get('tag', 'N/A')})", inline=True)
        embed.add_field(name="Current trophies", value=player.get("trophies", "N/A"), inline=True)
        embed.add_field(name="Trophy record", value=player.get("bestTrophies", "N/A"), inline=True)
        if player.get("league"):
            league = player["league"]
            embed.add_field(name="League", value=league.get("name", "N/A"), inline=True)
        embed.add_field(name="War stars collected", value=player.get("warStars", "N/A"), inline=True)
        embed.add_field(name="Attacks won this season", value=player.get("attackWins", "N/A"), inline=True)
        embed.add_field(name="Successful defenses this season", value=player.get("defenseWins", "N/A"), inline=True)
        embed.add_field(name="Troops donated", value=player.get("donations", "N/A"), inline=True)
        embed.add_field(name="Troops received", value=player.get("donationsReceived", "N/A"), inline=True)
        embed.add_field(name="Clan capital contributions", value=player.get("clanCapitalContributions", "N/A"), inline=True)
        # Set thumbnail to the player's division/rank badge if available, otherwise clan badge
        thumbnail_url = None
        if player.get("league"):
            league = player["league"]
            thumbnail_url = league.get("iconUrls", {}).get("medium")
        if not thumbnail_url and player.get("clan"):
            clan = player["clan"]
            thumbnail_url = clan.get("badgeUrls", {}).get("medium")
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        await ctx.send(embed=embed)

    @clashprofile.command(name="achievements")
    async def clashprofile_achievements(self, ctx, tag: str = None):
        """Get a paginated, scrollable list of achievements for a Clash of Clans player."""

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        achievements = player.get("achievements", [])
        if not achievements:
            await ctx.send("No achievements found for this player.")
            return

        PAGE_SIZE = 9

        def make_embed(page: int):
            embed = discord.Embed(
                title=f"Achievements for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
                color=discord.Color.gold()
            )
            start = page * PAGE_SIZE
            end = min(start + PAGE_SIZE, len(achievements))
            for ach in achievements[start:end]:
                stars = "⭐" * ach.get("stars", 0)
                embed.add_field(
                    name=f"{ach.get('name', 'Unknown')} {stars}",
                    value=f"{ach.get('info', '')}\nProgress: {ach.get('value', 0)}/{ach.get('target', 0)}\n{ach.get('completionInfo', '') or ''}",
                    inline=True
                )
            total_pages = math.ceil(len(achievements) / PAGE_SIZE)
            embed.set_footer(text=f"Page {page+1}/{total_pages} • {len(achievements)} achievements total")
            return embed

        # Emoji navigation
        LEFT_EMOJI = "⬅️"
        CLOSE_EMOJI = "❌"
        RIGHT_EMOJI = "➡️"
        EMOJIS = [LEFT_EMOJI, CLOSE_EMOJI, RIGHT_EMOJI]

        total_pages = math.ceil(len(achievements) / PAGE_SIZE)
        page = 0
        embed = make_embed(page)
        message = await ctx.send(embed=embed)
        for emoji in EMOJIS:
            await message.add_reaction(emoji)

        def check(reaction, user):
            return (
                user.id == ctx.author.id
                and reaction.message.id == message.id
                and str(reaction.emoji) in EMOJIS
            )

        import asyncio

        while True:
            try:
                reaction, user = await ctx.bot.wait_for("reaction_add", timeout=120.0, check=check)
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except Exception:
                    pass
                break

            if str(reaction.emoji) == LEFT_EMOJI:
                if page > 0:
                    page -= 1
                    await message.edit(embed=make_embed(page))
                await message.remove_reaction(LEFT_EMOJI, user)
            elif str(reaction.emoji) == RIGHT_EMOJI:
                if page < total_pages - 1:
                    page += 1
                    await message.edit(embed=make_embed(page))
                await message.remove_reaction(RIGHT_EMOJI, user)
            elif str(reaction.emoji) == CLOSE_EMOJI:
                try:
                    await message.delete()
                except Exception:
                    pass
                break

    @clashprofile.command(name="troops")
    async def clashprofile_troops(self, ctx, tag: str = None):
        """Get a list of troops and their levels for a Clash of Clans player."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        if tag is None:
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

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
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

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
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

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
            user_tag = await self.config.user(ctx.author).tag()
            verified = await self.config.user(ctx.author).verified()
            if not user_tag or not verified:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clashprofile link` first or provide a tag.")
                return
            tag = user_tag

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

