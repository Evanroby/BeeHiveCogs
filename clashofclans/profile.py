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

    @commands.group(name="clash")
    async def clash(self, ctx):
        """Clash of Clans commands."""

    @clash.group(name="profile")
    async def clash_profile(self, ctx):
        """Clash of Clans profile commands."""

    @clash_profile.command(name="link")
    async def clash_profile_link(self, ctx, tag: str, apikey: str):
        """Link your Clash of Clans account"""
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

    @clash_profile.command(name="info")
    async def clash_profile_info(self, ctx, user: discord.User = None):
        """Get general information about a Clash of Clans player. Omit argument for yourself, or mention another user."""

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

        # Determine which user to check
        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
            return
        tag = user_tag

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        # Default color
        embed_color = 0x4b4b4b

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
            role_label = " Clan Elder"
        elif player_role == "coleader":
            role_label = " Clan Co-Leader"
        elif player_role == "leader":
            role_label = " Clan Leader"

        # Emoji definitions for values
        EMOJI_TOWNHALL = "🏰"
        EMOJI_BUILDERHALL = "🏚️"
        EMOJI_LEVEL = "🎖️"
        EMOJI_CLAN = "🛡️"
        EMOJI_TROPHY = "🏆"
        EMOJI_RECORD = "📈"
        EMOJI_BUILDER_RECORD = "🥇"
        EMOJI_ATTACK = "⚔️"
        EMOJI_DEFENSE = "🛡️"
        EMOJI_DONATE = "📤"
        EMOJI_RECEIVE = "📥"
        EMOJI_WARSTAR = "⭐"
        EMOJI_CAPITAL = "🏛️"
        EMOJI_GOLD = "🪙"
        EMOJI_ELIXIR = "💧"
        EMOJI_DARK = "🌑"
        EMOJI_LABEL = "🏷️"

        embed = discord.Embed(
            title=f"{player.get('name', 'Unknown')}",
            description=f"{role_label}\n-# {player.get('tag', tag)}",
            color=embed_color
        )

        # If the user is in a clan, set the embed author to the clan name/tag and icon
        if player.get("clan"):
            clan = player["clan"]
            clan_name = clan.get("name", "N/A")
            clan_tag = clan.get("tag", "N/A")
            clan_icon = clan.get("badgeUrls", {}).get("medium")
            embed.set_author(
                name=f"{clan_name} ({clan_tag})",
                icon_url=clan_icon if clan_icon else discord.Embed.Empty
            )

        # Account Level
        embed.add_field(
            name="Account level",
            value=f"-# **{EMOJI_LEVEL} {player.get('expLevel', 'N/A')}**",
            inline=True
        )

        # Town Hall & Builder Hall (combined)
        townhall_level = player.get('townHallLevel', 'N/A')
        builderhall_level = player.get('builderHallLevel')
        townhall_field = f"-# **{EMOJI_TOWNHALL} {townhall_level}**"
        if builderhall_level:
            townhall_field += f"\n-# **{EMOJI_BUILDERHALL} {builderhall_level}**"
        embed.add_field(
            name="Town halls",
            value=townhall_field,
            inline=True
        )

        # Clan
        if player.get("clan"):
            clan = player["clan"]
            embed.add_field(
                name="Clan",
                value=f"-# **{EMOJI_CLAN} {clan.get('name', 'N/A')} ({clan.get('tag', 'N/A')})**",
                inline=True
            )

        # Current trophies (main village) & Builder Base trophies (combined)
        trophies = player.get('trophies', 'N/A')
        builder_base_trophies = player.get('builderBaseTrophies')
        trophies_field = f"-# **{EMOJI_TROPHY} {trophies}**"
        if builder_base_trophies:
            trophies_field += f"\n-# **{EMOJI_BUILDERHALL} {builder_base_trophies}**"
        embed.add_field(
            name="Current trophies",
            value=trophies_field,
            inline=True
        )

        # Trophy record (main village) & Builder Base record (combined)
        best_trophies = player.get('bestTrophies', 'N/A')
        best_builder_base_trophies = player.get('bestBuilderBaseTrophies')
        record_field = f"-# **{EMOJI_RECORD} {best_trophies}**"
        if best_builder_base_trophies:
            record_field += f"\n-# **{EMOJI_BUILDER_RECORD} {best_builder_base_trophies}**"
        embed.add_field(
            name="Trophy record",
            value=record_field,
            inline=True
        )

        # Leagues
        league_lines = []
        if player.get("league"):
            league = player["league"]
            league_name = league.get("name", "N/A")
            league_lines.append(f"-# **🏆 {league_name}**")
        if player.get("builderBaseLeague"):
            builder_league = player["builderBaseLeague"]
            builder_league_name = builder_league.get("name", "N/A")
            league_lines.append(f"-# **🛠️ {builder_league_name}**")
        if league_lines:
            embed.add_field(
                name="Current leagues",
                value="\n".join(league_lines),
                inline=True
            )

        # Lifetime stats from achievements
        achievements = player.get("achievements", [])
        lifetime_attack_wins = "N/A"
        lifetime_defense_wins = "N/A"
        for ach in achievements:
            if ach.get("name", "").lower() == "conqueror":
                lifetime_attack_wins = ach.get("value", "N/A")
            elif ach.get("name", "").lower() == "unbreakable":
                lifetime_defense_wins = ach.get("value", "N/A")

        embed.add_field(name="This season", value="A season lasts for the entire calendar month, starting on its first day and ending on its last", inline=False)
        embed.add_field(
            name="Attacks won",
            value=f"-# **{EMOJI_ATTACK} {player.get('attackWins', 'N/A')}**",
            inline=True
        )
        embed.add_field(
            name="Successful defenses",
            value=f"-# **{EMOJI_DEFENSE} {player.get('defenseWins', 'N/A')}**",
            inline=True
        )
        embed.add_field(
            name="Troops donated",
            value=f"-# **{EMOJI_DONATE} {player.get('donations', 'N/A')}**",
            inline=True
        )
        embed.add_field(
            name="Troops received",
            value=f"-# **{EMOJI_RECEIVE} {player.get('donationsReceived', 'N/A')}** ",
            inline=True
        )

        # Parse lifetime gold and elixir stolen from achievements
        lifetime_gold_stolen = "N/A"
        lifetime_elixir_stolen = "N/A"
        lifetime_dark_elixir_stolen = "N/A"
        for ach in achievements:
            if ach.get("name", "").lower() == "gold grab":
                lifetime_gold_stolen = ach.get("value", "N/A")
            elif ach.get("name", "").lower() == "elixir escapade":
                lifetime_elixir_stolen = ach.get("value", "N/A")
            elif ach.get("name", "").lower() == "heroic heist":
                lifetime_dark_elixir_stolen = ach.get("value", "N/A")

        embed.add_field(name="Lifetime stats", value="", inline=False)
        def format_number(val):
            try:
                if isinstance(val, int):
                    return f"{val:,}"
                if isinstance(val, str) and val.isdigit():
                    return f"{int(val):,}"
            except Exception:
                pass
            return val

        embed.add_field(
            name="Attacks won",
            value=f"-# **{EMOJI_ATTACK} {format_number(lifetime_attack_wins)}**",
            inline=True
        )
        embed.add_field(
            name="Successful defenses",
            value=f"-# **{EMOJI_DEFENSE} {format_number(lifetime_defense_wins)}**",
            inline=True
        )
        embed.add_field(
            name="War stars collected",
            value=f"-# **{EMOJI_WARSTAR} {format_number(player.get('warStars', 'N/A'))}**",
            inline=True
        )
        embed.add_field(
            name="Clan capital contributions",
            value=f"-# **{EMOJI_CAPITAL} {format_number(player.get('clanCapitalContributions', 'N/A'))}**",
            inline=True
        )
        embed.add_field(
            name="Gold stolen",
            value=f"-# **{EMOJI_GOLD} {format_number(lifetime_gold_stolen)}**",
            inline=True
        )
        embed.add_field(
            name="Elixir stolen",
            value=f"-# **{EMOJI_ELIXIR} {format_number(lifetime_elixir_stolen)}**",
            inline=True
        )
        embed.add_field(
            name="Dark Elixir stolen",
            value=f"-# **{EMOJI_DARK} {format_number(lifetime_dark_elixir_stolen)}**",
            inline=True
        )

        # Show user labels if available
        labels = player.get("labels", [])
        if labels:
            label_strs = [f"-# **{EMOJI_LABEL} {label.get('name', 'Unknown')}**" for label in labels]
            embed.add_field(
                name="Public labels",
                value="- " + "\n- ".join(label_strs),
                inline=False
            )

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

    @clash_profile.command(name="achievements")
    async def clash_profile_achievements(self, ctx, user: discord.User = None):
        """Get a paginated, scrollable list of achievements for a Clash of Clans player. Omit argument for yourself, or mention another user."""

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        # Determine which user to check
        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
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
                name = ach.get("name", "Unknown")
                info = ach.get("info", "")
                stars = ach.get("stars", 0)
                value = ach.get("value", 0)
                target = ach.get("target", 0)
                value_lines = []
                if info:
                    value_lines.append(info)
                # Replace the "level" number (stars) with star emojis
                star_emojis = "⭐" * stars if stars > 0 else "✩"
                value_lines.append(f"-# {star_emojis}")
                if value >= target:
                    value_lines.append(f"-# :white_check_mark: Complete")
                else:
                    value_lines.append(f"-# {value}/**{target}**")
                embed.add_field(
                    name=name,
                    value="\n".join(value_lines),
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

        def check(reaction, user_):
            return (
                user_.id == ctx.author.id
                and reaction.message.id == message.id
                and str(reaction.emoji) in EMOJIS
            )

        import asyncio

        while True:
            try:
                reaction, user_ = await ctx.bot.wait_for("reaction_add", timeout=120.0, check=check)
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
                await message.remove_reaction(LEFT_EMOJI, user_)
            elif str(reaction.emoji) == RIGHT_EMOJI:
                if page < total_pages - 1:
                    page += 1
                    await message.edit(embed=make_embed(page))
                await message.remove_reaction(RIGHT_EMOJI, user_)
            elif str(reaction.emoji) == CLOSE_EMOJI:
                try:
                    await message.delete()
                except Exception:
                    pass
                break

    @clash_profile.command(name="troops")
    async def clash_profile_troops(self, ctx, user: discord.User = None):
        """Get a list of troops and their levels for a Clash of Clans player. Omit argument for yourself, or mention another user."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        # Determine which user to check
        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
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

    @clash_profile.command(name="heroes")
    async def clash_profile_heroes(self, ctx, user: discord.User = None):
        """See player heroes and equipped/unequipped hero equipment in a detailed format."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        # Determine which user to check
        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
            return
        tag = user_tag

        player = await self.fetch_player_data(tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        heroes = player.get("heroes", [])
        hero_equipment = player.get("heroEquipment", [])

        if not heroes:
            await ctx.send("No heroes found for this player.")
            return

        # Gather all equipped equipment (by name) for easy lookup
        equipped_names = set()
        for hero in heroes:
            for eq in hero.get("equipment", []):
                if eq.get("name"):
                    equipped_names.add(eq["name"])

        # Prepare embed for heroes and their equipped equipment
        embed_heroes = discord.Embed(
            title=f"Heroes for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.purple()
        )

        for hero in heroes:
            hero_name = hero.get("name", "Unknown")
            hero_level = hero.get("level", 0)
            hero_max = hero.get("maxLevel", 0)
            eq = hero.get("equipment", [])
            if eq:
                eq_lines = []
                for e in eq:
                    eq_lines.append(
                        f"- {e.get('name', 'Unknown')}\n-# Level {e.get('level', 0)}/{e.get('maxLevel', 0)}"
                    )
                eq_str = "\n".join(eq_lines)
            else:
                eq_str = "None"
            value = f"-# Level {hero_level}/{hero_max}\n{eq_str}"
            # Discord embed field value max length is 1024, so truncate if needed
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed_heroes.add_field(
                name=f"{hero_name}",
                value=value,
                inline=True
            )

        await ctx.send(embed=embed_heroes)

        # Prepare embed for unequipped hero equipment
        if hero_equipment:
            unequipped = [
                eq for eq in hero_equipment
                if eq.get("name") and eq["name"] not in equipped_names
            ]
            if unequipped:
                embed_unequipped = discord.Embed(
                    title=f"Spare equipment for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
                    color=discord.Color.purple()
                )
                # Style each unequipped equipment like equipped: name, then -# Level x/y
                eq_lines = []
                for eq in unequipped:
                    eq_lines.append(
                        f"- {eq.get('name', 'Unknown')}\n-# Level {eq.get('level', 0)}/{eq.get('maxLevel', 0)}"
                    )
                # Discord embed field value max length is 1024, so chunk if needed
                for i in range(0, len(eq_lines), 10):
                    chunk = eq_lines[i:i+10]
                    value = "\n".join(chunk)
                    if len(value) > 1024:
                        value = value[:1021] + "..."
                    embed_unequipped.add_field(
                        name=f"",
                        value=value,
                        inline=True
                    )
                await ctx.send(embed=embed_unequipped)
            else:
                embed_unequipped = discord.Embed(
                    title=f"Spare equipment for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
                    description="All hero equipment is currently equipped.",
                    color=discord.Color.purple()
                )
                await ctx.send(embed=embed_unequipped)
        else:
            embed_unequipped = discord.Embed(
                title=f"Spare equipment for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
                description="No hero equipment found for this player.",
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed_unequipped)

    @clash_profile.command(name="spells")
    async def clash_profile_spells(self, ctx, user: discord.User = None):
        """Get a list of spells and their levels for a Clash of Clans player. Omit argument for yourself, or mention another user."""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        # Determine which user to check
        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
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

        # Prepare embed for spells, formatting like heroes (one field per spell, with level/maxLevel)
        embed_spells = discord.Embed(
            title=f"Spells for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.teal()
        )

        for spell in spells:
            spell_name = spell.get("name", "Unknown")
            spell_level = spell.get("level", 0)
            spell_max = spell.get("maxLevel", 0)
            value = f"-# Level {spell_level}/{spell_max}"
            # Discord embed field value max length is 1024, so truncate if needed
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed_spells.add_field(
                name=f"{spell_name}",
                value=value,
                inline=True
            )

        await ctx.send(embed=embed_spells)

