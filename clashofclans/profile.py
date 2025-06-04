import discord
from collections import defaultdict
from redbot.core import commands, Config, checks
import math
import datetime
import aiohttp
from io import BytesIO
from PIL import Image
import asyncio
import colorsys

# Move this helper to the class scope so it can be used in _build_log_embed
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
            pixels = [p for p in pixels if p[3] > 0]
            if not pixels:
                return None
            def color_richness(p):
                r, g, b, a = p
                h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                return v * 0.7 + s * 0.3
            brightest = max(pixels, key=color_richness)
            return discord.Color.from_rgb(brightest[0], brightest[1], brightest[2])
    except Exception:
        return None

class ClashProfile(commands.Cog):
    """Clash of Clans profile commands."""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        # User config: tag, verified, last_profile (for logging)
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_user = {"tag": None, "verified": False, "last_profile": None}
        self.config.register_user(**default_user)
        # Guild config: log_channel, clan_tag, role settings, nickname sync
        default_guild = {
            "log_channel": None,
            "clan_tag": None,
            "roles": {
                "member": None,
                "elder": None,
                "coleader": None,
                "leader": None
            },
            "nickname_sync": False  # Add nickname sync config
        }
        self.config.register_guild(**default_guild)
        self._log_task = self.bot.loop.create_task(self._log_loop())

    def cog_unload(self):
        if hasattr(self, "_log_task"):
            self._log_task.cancel()

    async def get_dev_api_key(self):
        tokens = await self.bot.get_shared_api_tokens("clashofclans")
        return tokens.get("api_key")

    async def verify_coc_account(self, tag: str, user_apikey: str, dev_api_key: str) -> bool:
        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/players/%23{tag}/verifytoken"
        headers = {
            "Authorization": f"Bearer {dev_api_key}",
            "Accept": "application/json"
        }
        payload = {"token": user_apikey}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return data.get("status") == "ok"

    async def fetch_player_data(self, tag: str, dev_api_key: str):
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

    async def fetch_clan_data(self, tag: str, dev_api_key: str):
        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/clans/%23{tag}"
        headers = {
            "Authorization": f"Bearer {dev_api_key}",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def fetch_clan_warlog(self, tag: str, dev_api_key: str, limit: int = 10):
        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/clans/%23{tag}/warlog?limit={limit}"
        headers = {
            "Authorization": f"Bearer {dev_api_key}",
            "Accept": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()

    async def fetch_clan_current_war(self, tag: str, dev_api_key: str):
        tag = tag.replace("#", "").upper()
        url = f"https://api.clashofclans.com/v1/clans/%23{tag}/currentwar"
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
        """Use Discord to interact with your Clash of Clans account."""

    @clash.group(name="clan")
    async def clash_clan(self, ctx):
        """Clan commands."""

    @clash_clan.command(name="autokick")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_clan_autokick(self, ctx, enable: bool = None):
        """
        Enable or disable autokicking users whose linked clan tag does not match the server's clan tag.

        Usage:
        `[p]clash clan autokick true` - Enable autokick
        `[p]clash clan autokick false` - Disable autokick
        `[p]clash clan autokick` - Show current status
        """
        if enable is None:
            current = await self.config.guild(ctx.guild).autokick()
            await ctx.send(f"Autokick is currently **{'enabled' if current else 'disabled'}** for this server.")
            return
        await self.config.guild(ctx.guild).autokick.set(enable)
        await ctx.send(f"Autokick has been **{'enabled' if enable else 'disabled'}** for this server.")

    @clash_clan.command(name="nicknamesync")
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_clan_nicknamesync(self, ctx, enable: bool = None):
        """
        Enable or disable nickname sync for this server.

        When enabled, users' Discord nicknames will be updated to match their in-game names.
        """
        if enable is None:
            current = await self.config.guild(ctx.guild).nickname_sync()
            await ctx.send(f"Nickname sync is currently **{'enabled' if current else 'disabled'}** for this server.")
            return
        await self.config.guild(ctx.guild).nickname_sync.set(enable)
        await ctx.send(f"Nickname sync has been **{'enabled' if enable else 'disabled'}** for this server.")

    async def autokick_task(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                for guild in self.bot.guilds:
                    autokick = await self.config.guild(guild).autokick()
                    clan_tag = await self.config.guild(guild).clan_tag()
                    if not autokick or not clan_tag:
                        continue
                    # Get all members with linked and verified accounts
                    for member in guild.members:
                        if member.bot:
                            continue
                        user_tag = await self.config.user(member).tag()
                        verified = await self.config.user(member).verified()
                        if not user_tag or not verified:
                            continue
                        dev_api_key = await self.get_dev_api_key()
                        if not dev_api_key:
                            continue
                        player = await self.fetch_player_data(user_tag, dev_api_key)
                        if not player:
                            continue
                        player_clan = player.get("clan", {}).get("tag")
                        if not player_clan:
                            # Not in a clan, skip
                            continue
                        # Compare tags (case-insensitive, always uppercase, always with #)
                        if player_clan.upper().replace("#", "") != clan_tag.upper().replace("#", ""):
                            try:
                                await guild.kick(member, reason="Clash of Clans autokick: clan tag mismatch")
                                # Optionally, DM the user
                                try:
                                    await member.send(
                                        f"You have been kicked from **{guild.name}** because your linked Clash of Clans account is not in the required clan ({clan_tag})."
                                    )
                                except Exception:
                                    pass
                            except Exception:
                                pass
            except Exception as e:
                import traceback
                traceback.print_exc()
            await asyncio.sleep(900)  # 15 minutes

    @clash_clan.command(name="pastwar")
    async def clash_clan_warlog(self, ctx, user: discord.User = None):
        """
        View the clan's war log
        """
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash player link` first.")
            return

        player = await self.fetch_player_data(user_tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        clan = player.get("clan")
        if not clan or not clan.get("tag"):
            await ctx.send("This player is not in a clan.")
            return

        clan_tag = clan.get("tag")
        clan_name = clan.get("name", "Unknown")
        clan_badge = clan.get("badgeUrls", {}).get("medium")

        # Fetch warlog
        warlog_data = await self.fetch_clan_warlog(clan_tag, dev_api_key, limit=10)
        if not warlog_data:
            await ctx.send("Could not fetch clan warlog. The clan may have a private warlog or there was an error.")
            return

        if warlog_data.get("reason") == "accessDenied":
            await ctx.send("This clan's warlog is private and cannot be accessed.")
            return

        warlogs = warlog_data.get("items", [])
        if not warlogs:
            await ctx.send("No warlog entries found for this clan.")
            return

        # Pagination
        PAGE_SIZE = 5
        total_pages = max(1, math.ceil(len(warlogs) / PAGE_SIZE))
        page = 0

        def format_number(val):
            try:
                if isinstance(val, int):
                    return f"{val:,}"
                if isinstance(val, float):
                    return f"{val:,.1f}"
                if isinstance(val, str) and val.isdigit():
                    return f"{int(val):,}"
            except Exception:
                pass
            return val

        def explain_result(result, clan1, clan2):
            # result: "win", "lose", "draw", etc.
            # clan1 is always the home clan (the one whose warlog this is)
            # clan2 is the opponent
            if not result:
                return "-# **Result unknown.**"
            result = result.lower()
            if result == "win":
                return f"-# **{clan1.get('name', 'Your clan')} won against {clan2.get('name', 'the opponent')}!**"
            elif result == "lose":
                return f"-# **{clan1.get('name', 'Your clan')} lost to {clan2.get('name', 'the opponent')}.**"
            elif result == "draw":
                return f"-# **{clan1.get('name', 'Your clan')} drew with {clan2.get('name', 'the opponent')}.**"
            else:
                return f"-# **Result: {result.capitalize()}**"

        def make_embed(page_num):
            embed = discord.Embed(
                title=f"Warlog for {clan_name} ({clan_tag})",
                color=discord.Color.orange()
            )
            if clan_badge:
                embed.set_thumbnail(url=clan_badge)
            start = page_num * PAGE_SIZE
            end = start + PAGE_SIZE
            page_wars = warlogs[start:end]

            for war in page_wars:
                result = war.get("result", "unknown")
                end_time = war.get("endTime")
                # Parse end time to Discord timestamp if possible
                end_time_str = ""
                if end_time:
                    try:
                        ts = end_time.split(".")[0]
                        dt = datetime.datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc)
                        unix = int(dt.timestamp())
                        end_time_str = f"<t:{unix}:R>"
                    except Exception:
                        end_time_str = end_time
                clan1 = war.get("clan", {})
                clan2 = war.get("opponent", {})
                clan1_name = clan1.get("name", "Unknown")
                clan2_name = clan2.get("name", "Unknown")
                clan1_stars = clan1.get("stars", "?")
                clan2_stars = clan2.get("stars", "?")
                clan1_destr = clan1.get("destructionPercentage", 0)
                clan2_destr = clan2.get("destructionPercentage", 0)
                team_size = war.get("teamSize", "?")
                attacks_per_member = war.get("attacksPerMember", "?")
                war_type = war.get("type", "War")

                # Compose a more lingual, readable summary
                summary_lines = [
                    explain_result(result, clan1, clan2),
                    f"-# **War type:** {war_type}",
                    f"-# **Team size:** {team_size} (each member: {attacks_per_member} attacks)",
                    f"-# **{clan1_name}**: {format_number(clan1_stars)} stars, {format_number(clan1_destr)}% destruction",
                    f"-# **{clan2_name}**: {format_number(clan2_stars)} stars, {format_number(clan2_destr)}% destruction",
                    f"-# **Ended:** {end_time_str}"
                ]
                # Add a little more explanation for close/draw
                if str(clan1_stars) == str(clan2_stars):
                    if abs(float(clan1_destr) - float(clan2_destr)) < 0.01:
                        summary_lines.append("-# **This war was a perfect tie!**")
                    else:
                        if float(clan1_destr) > float(clan2_destr):
                            summary_lines.append(f"-# **{clan1_name} won on destruction percentage.**")
                        elif float(clan2_destr) > float(clan1_destr):
                            summary_lines.append(f"-# **{clan2_name} won on destruction percentage.**")
                field_title = f"{clan1_name} vs {clan2_name}"
                field_value = "\n".join(summary_lines)
                embed.add_field(name=field_title, value=field_value, inline=False)
            embed.set_footer(text=f"Page {page_num+1}/{total_pages} • {len(warlogs)} wars")
            return embed

        LEFT_EMOJI = "⬅️"
        CLOSE_EMOJI = "❌"
        RIGHT_EMOJI = "➡️"
        EMOJIS = [LEFT_EMOJI, CLOSE_EMOJI, RIGHT_EMOJI]

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
                try:
                    await message.remove_reaction(LEFT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == RIGHT_EMOJI:
                if page < total_pages - 1:
                    page += 1
                    await message.edit(embed=make_embed(page))
                try:
                    await message.remove_reaction(RIGHT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == CLOSE_EMOJI:
                try:
                    await message.delete()
                except Exception:
                    pass
                break

    @clash_clan.command(name="currentwar")
    async def clash_clan_currentwar(self, ctx, user: discord.User = None):
        """
        Show the current clan war active
        """
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        target_user = user or ctx.author
        user_tag = await self.config.user(target_user).tag()
        verified = await self.config.user(target_user).verified()
        if not user_tag or not verified:
            if user:
                await ctx.send(f"{user.mention} has not linked and verified their Clash of Clans account.")
            else:
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash player link` first.")
            return

        player = await self.fetch_player_data(user_tag, dev_api_key)
        if not player:
            await ctx.send("Could not fetch player data. Please check the tag and try again.")
            return

        clan = player.get("clan")
        if not clan or not clan.get("tag"):
            await ctx.send("This player is not in a clan.")
            return

        clan_tag = clan.get("tag")
        clan_name = clan.get("name", "Unknown")
        clan_badge = clan.get("badgeUrls", {}).get("medium")

        # Fetch current war
        war_data = await self.fetch_clan_current_war(clan_tag, dev_api_key)
        if not war_data:
            await ctx.send("Could not fetch current war. The clan may not be in a war or there was an error.")
            return

        state = war_data.get("state", "notInWar")
        if state == "notInWar":
            await ctx.send("This clan is not currently in a war.")
            return
        if war_data.get("reason") == "accessDenied":
            await ctx.send("This clan's current war is private and cannot be accessed.")
            return

        # Parse war times
        prep_start_time = war_data.get("preparationStartTime")
        start_time = war_data.get("startTime")
        end_time = war_data.get("endTime")
        def parse_coc_time(ts):
            if not ts:
                return None
            ts = ts.split(".")[0]
            try:
                return datetime.datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc)
            except Exception:
                return None

        prep_start_dt = parse_coc_time(prep_start_time)
        start_dt = parse_coc_time(start_time)
        end_dt = parse_coc_time(end_time)

        def discord_ts(dt, fmt="R"):
            if not dt:
                return "Unknown"
            return f"<t:{int(dt.timestamp())}:{fmt}>"

        # War type
        war_type = war_data.get("warType", "War")
        team_size = war_data.get("teamSize", "?")
        attacks_per_member = war_data.get("attacksPerMember", "?")

        # Clan and opponent info
        clan1 = war_data.get("clan", {})
        clan2 = war_data.get("opponent", {})
        clan1_name = clan1.get("name", "Unknown")
        clan2_name = clan2.get("name", "Unknown")
        clan1_tag = clan1.get("tag", "")
        clan2_tag = clan2.get("tag", "")
        clan1_stars = clan1.get("stars", "?")
        clan2_stars = clan2.get("stars", "?")
        clan1_destr = clan1.get("destructionPercentage", 0)
        clan2_destr = clan2.get("destructionPercentage", 0)
        clan1_badge = clan1.get("badgeUrls", {}).get("medium")
        clan2_badge = clan2.get("badgeUrls", {}).get("medium")

        # War state
        state_map = {
            "preparation": "Preparation",
            "inWar": "In War",
            "warEnded": "War Ended",
            "notInWar": "Not in War"
        }
        state_str = state_map.get(state, state)

        # Compose embed
        embed = discord.Embed(
            title=f"Current War: {clan1_name} vs {clan2_name}",
            color=0xff4545 if state == "inWar" else discord.Color.orange()
        )
        if clan1_badge:
            embed.set_thumbnail(url=clan1_badge)
        embed.add_field(
            name="War State",
            value=f"-# **{state_str}**",
            inline=True
        )
        embed.add_field(
            name="War Type",
            value=f"-# **{war_type}**",
            inline=True
        )
        embed.add_field(
            name="Team Size",
            value=f"-# **{team_size}** (each member: {attacks_per_member} attacks)",
            inline=True
        )
        if prep_start_dt:
            embed.add_field(
                name="Preparation Start",
                value=f"-# {discord_ts(prep_start_dt, 'F')} ({discord_ts(prep_start_dt, 'R')})",
                inline=True
            )
        if start_dt:
            embed.add_field(
                name="War Start",
                value=f"-# {discord_ts(start_dt, 'F')} ({discord_ts(start_dt, 'R')})",
                inline=True
            )
        if end_dt:
            embed.add_field(
                name="War End",
                value=f"-# {discord_ts(end_dt, 'F')} ({discord_ts(end_dt, 'R')})",
                inline=True
            )

        # Stars and destruction
        embed.add_field(
            name=f"{clan1_name} ({clan1_tag})",
            value=f"-# **{clan1_stars} stars**\n-# **{clan1_destr}% destruction**",
            inline=True
        )
        embed.add_field(
            name=f"{clan2_name} ({clan2_tag})",
            value=f"-# **{clan2_stars} stars**\n-# **{clan2_destr}% destruction**",
            inline=True
        )

        # Optionally, show a summary of attacks left
        if state in ("inWar", "warEnded"):
            clan1_attacks = clan1.get("attacks", 0)
            clan2_attacks = clan2.get("attacks", 0)
            embed.add_field(
                name="Attacks Used",
                value=f"-# **{clan1_name}: {clan1_attacks}**\n-# **{clan2_name}: {clan2_attacks}**",
                inline=False
            )

        # Optionally, show a few top performers (stars, destruction)
        # Only if warEnded or inWar
        if state in ("inWar", "warEnded"):
            def get_top_members(members, key, top=3):
                # key: "stars" or "destructionPercentage"
                if not members:
                    return []
                return sorted(members, key=lambda m: m.get(key, 0), reverse=True)[:top]

            clan1_members = war_data.get("clan", {}).get("members", [])
            clan2_members = war_data.get("opponent", {}).get("members", [])
            if clan1_members:
                top_stars = get_top_members(clan1_members, "stars")
                if top_stars:
                    lines = []
                    for m in top_stars:
                        lines.append(f"-# {m.get('name', 'Unknown')}: {m.get('stars', 0)}⭐, {m.get('destructionPercentage', 0)}%")
                    embed.add_field(
                        name=f"Top {clan1_name} Members",
                        value="\n".join(lines),
                        inline=False
                    )
            if clan2_members:
                top_stars = get_top_members(clan2_members, "stars")
                if top_stars:
                    lines = []
                    for m in top_stars:
                        lines.append(f"-# {m.get('name', 'Unknown')}: {m.get('stars', 0)}⭐, {m.get('destructionPercentage', 0)}%")
                    embed.add_field(
                        name=f"Top {clan2_name} Members",
                        value="\n".join(lines),
                        inline=False
                    )

        await ctx.send(embed=embed)

    # Register the autokick task on cog load
    async def cog_load(self):
        if not hasattr(self, "_autokick_task_started"):
            self._autokick_task_started = True
            self.bot.loop.create_task(self.autokick_task())

    @clash.group(name="logs")
    @commands.guild_only()
    async def clash_logs(self, ctx):
        """
        Configure activity logging
        
        The bot can automatically log clan member activity to a channel of your choice. Alerts will be sent when...

        -# A clan member levels up
        -# A clan member wins an attack
        -# A clan member wins a defense
        -# A clan member gains or loses trophies
        -# A clan member unlocks or improves an achievement
        -# A clan member is donated troops or spells
        -# A clan member donates troops or spells to another player
        -# A clan member contributes Capital Gold
        -# A clan member upgrades a troop
        -# A clan member upgrades a spell
        -# A clan member upgrades a hero
        -# A clan member upgrades a hero's equipment
        -# A clan member upgrades their town hall
        -# A clan member upgrades their builder hall
        -# A clan member changes their in-game name
        -# A clan member changes their Clan War status

        """

    @clash_logs.command(name="channel")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_logs_setchannel(self, ctx, channel: discord.TextChannel):
        """Set activity channel"""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ Logging channel set to {channel.mention}.")

    @clash_logs.command(name="clantag")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_logs_setclan(self, ctx, tag: str):
        """Set server's clan tag"""
        if not tag.startswith("#"):
            await ctx.send("Please provide a valid clan tag starting with # (e.g. #ABC123).")
            return
        await self.config.guild(ctx.guild).clan_tag.set(tag.upper())
        await ctx.send(f"✅ Clan tag for this server set to {tag.upper()}.")

    @clash_logs.command(name="settings")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_logs_show(self, ctx):
        """Show current settings."""
        log_channel_id = await self.config.guild(ctx.guild).log_channel()
        clan_tag = await self.config.guild(ctx.guild).clan_tag()
        log_channel = ctx.guild.get_channel(log_channel_id) if log_channel_id else None
        await ctx.send(
            f"Logging channel: {log_channel.mention if log_channel else 'Not set'}\n"
            f"Clan tag: {clan_tag or 'Not set'}"
        )

    # --- ROLES COMMAND GROUP ---
    @clash.group(name="roles")
    @commands.guild_only()
    async def clash_roles(self, ctx):
        """Role assignment and configuration"""

    @clash_roles.command(name="member")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_roles_setmember(self, ctx, role: discord.Role = None):
        """Specify clan member role"""
        await self.config.guild(ctx.guild).roles.member.set(role.id if role else None)
        if role:
            await ctx.send(f"✅ Clan member role set to {role.mention}.")
        else:
            await ctx.send("✅ Clan member role cleared.")

    @clash_roles.command(name="elder")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_roles_setelder(self, ctx, role: discord.Role = None):
        """Specify clan elder role"""
        await self.config.guild(ctx.guild).roles.elder.set(role.id if role else None)
        if role:
            await ctx.send(f"✅ Clan elder role set to {role.mention}.")
        else:
            await ctx.send("✅ Clan elder role cleared.")

    @clash_roles.command(name="coleader")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_roles_setcoleader(self, ctx, role: discord.Role = None):
        """Specify clan co-leader role"""
        await self.config.guild(ctx.guild).roles.coleader.set(role.id if role else None)
        if role:
            await ctx.send(f"✅ Clan co-leader role set to {role.mention}.")
        else:
            await ctx.send("✅ Clan co-leader role cleared.")

    @clash_roles.command(name="leader")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_roles_setleader(self, ctx, role: discord.Role = None):
        """Specify clan leader role"""
        await self.config.guild(ctx.guild).roles.leader.set(role.id if role else None)
        if role:
            await ctx.send(f"✅ Clan leader role set to {role.mention}.")
        else:
            await ctx.send("✅ Clan leader role cleared.")

    @clash_roles.command(name="show")
    @checks.admin_or_permissions(manage_guild=True)
    async def clash_roles_show(self, ctx):
        """Show current role assignment settings."""
        roles_cfg = await self.config.guild(ctx.guild).roles()
        def get_role_mention(role_id):
            if not role_id:
                return "Not set"
            role = ctx.guild.get_role(role_id)
            return role.mention if role else f"ID:{role_id} (not found)"
        await ctx.send(
            f"Member: {get_role_mention(roles_cfg.get('member'))}\n"
            f"Elder: {get_role_mention(roles_cfg.get('elder'))}\n"
            f"Co-Leader: {get_role_mention(roles_cfg.get('coleader'))}\n"
            f"Leader: {get_role_mention(roles_cfg.get('leader'))}"
        )

    @clash.group(name="player")
    async def clash_player(self, ctx):
        """Link accounts and view player information"""

    @clash_player.command(name="link")
    async def clash_player_link(self, ctx, tag: str, apikey: str):
        """
        Link your Clash of Clans account
        
        **<tag>** - The tag of the account you want to link, found under your screen name on your in-game profile. Looks like a hashtag followed by 8 numbers and letters (e.g. #ABC123).

        **<apikey>** - The key belonging to the account you want to link. You can find it in the in-game settings under Settings > More settings > API.

        It's safe to send your game apikey publicly, as they are designed to be one-time use tokens and will rotate as soon as they're used. Once you run the command, the key won't work for anyone else.
        """
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
            # Fetch the user's profile for personalization
            player = await self.fetch_player_data(tag.upper(), dev_api_key)
            if player:
                player_name = player.get("name", "Unknown")
                player_tag = player.get("tag", tag.upper())
                league_icon = None
                if player.get("league"):
                    league_icon = player["league"].get("iconUrls", {}).get("medium")
                elif player.get("clan"):
                    league_icon = player["clan"].get("badgeUrls", {}).get("medium")
                embed = discord.Embed(
                    title="Authentication successful, you're all set!",
                    description=f"Welcome back, **{player_name}**\nYour tag `{player_tag}` has been linked to this Discord account.\nYour roles will automatically sync shortly, please be patient.",
                    color=0x2bbd8e
                )
                if league_icon:
                    embed.set_thumbnail(url=league_icon)
            else:
                embed = discord.Embed(
                    title="Authentication successful, you're all set!",
                    description=f"Your Clash of Clans profile has been set and verified for tag **{tag.upper()}**!",
                    color=0x2bbd8e
                )
            await ctx.send(embed=embed)
        else:
            await self.config.user(ctx.author).tag.set(None)
            await self.config.user(ctx.author).verified.set(False)
            embed = discord.Embed(
                title="We couldn't verify you own this account",
                description=(
                    "Please ensure your tag and key are correct, then try again."
                ),
                color=0xff4545
            )
            await ctx.send(embed=embed)

    @clash_player.command(name="about")
    async def clash_player_about(self, ctx, user: discord.User = None):
        """View player information"""

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

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

        # Fetch current season info from /goldpass/seasons/current
        season_start = None
        season_end = None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.clashofclans.com/v1/goldpass/seasons/current",
                    headers={
                        "Authorization": f"Bearer {dev_api_key}",
                        "Accept": "application/json"
                    }
                ) as resp:
                    if resp.status == 200:
                        season_data = await resp.json()
                        # Example: "20250601T080100.000Z"
                        def parse_coc_time(ts):
                            # Remove milliseconds if present
                            ts = ts.split(".")[0]
                            # Format: YYYYMMDDT HHMMSS Z
                            return datetime.datetime.strptime(ts, "%Y%m%dT%H%M%S").replace(tzinfo=datetime.timezone.utc)
                        season_start = parse_coc_time(season_data.get("startTime"))
                        season_end = parse_coc_time(season_data.get("endTime"))
        except Exception:
            season_start = None
            season_end = None

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

        # Clan wars participation
        war_pref = player.get("warPreference", "N/A")
        if war_pref == "in":
            war_status = "⚔️ Participating"
        elif war_pref == "out":
            war_status = "🚫 Not participating"
        else:
            war_status = "Clan war status unknown"
        embed.add_field(
            name="Clan wars",
            value=f"-# **{war_status}**",
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

        # Build the season explainer with dynamic timestamps if available
        if season_start and season_end:
            # Discord dynamic timestamp: <t:unix:format>
            # <t:unix:R> = relative, <t:unix:D> = date, <t:unix:F> = full
            start_unix = int(season_start.timestamp())
            end_unix = int(season_end.timestamp())
            season_explainer = (
                f"-# **An in-game season lasts for the entire calendar month. This season will run from <t:{start_unix}:D> to <t:{end_unix}:D>. It started <t:{start_unix}:R> and ends <t:{end_unix}:R>.**"
            )
        else:
            season_explainer = "-# **A season lasts for the entire calendar month, starting on its first day and ending on its last.**"

        embed.add_field(name="This season", value=season_explainer, inline=False)
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

        embed.add_field(name="Lifetime stats", value="-# **Your in-game statistics from the creation time of your account.**", inline=False)
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
        embed.add_field(
            name="Clan capital",
            value=f"-# **{EMOJI_CAPITAL} {format_number(player.get('clanCapitalContributions', 'N/A'))} Capital Gold donated**",
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

    @clash_player.command(name="achievements")
    async def clash_player_achievements(self, ctx, user: discord.User = None):
        """View player achievements"""

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

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
                star_emojis = "⭐" * stars if stars > 0 else "✩"
                value_lines.append(f"-# {star_emojis}")
                if value >= target and target > 0:
                    value_lines.append(f"-# :white_check_mark: Complete")
                elif target > 0:
                    value_lines.append(f"-# {value}/**{target}**")
                else:
                    value_lines.append(f"-# {value}")
                embed.add_field(
                    name=name,
                    value="\n".join(value_lines),
                    inline=True
                )
            total_pages = math.ceil(len(achievements) / PAGE_SIZE)
            embed.set_footer(text=f"Page {page+1}/{total_pages} • {len(achievements)} achievements total")
            return embed

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
                try:
                    await message.remove_reaction(LEFT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == RIGHT_EMOJI:
                if page < total_pages - 1:
                    page += 1
                    await message.edit(embed=make_embed(page))
                try:
                    await message.remove_reaction(RIGHT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == CLOSE_EMOJI:
                try:
                    await message.delete()
                except Exception:
                    pass
                break

    @clash_player.command(name="troops")
    async def clash_player_troops(self, ctx, user: discord.User = None):
        """View player troops and levels"""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

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

        # No longer group by village, just use the troops list directly
        troop_entries = troops

        PAGE_SIZE = 9
        total_pages = max(1, math.ceil(len(troop_entries) / PAGE_SIZE))
        page = 0

        LEFT_EMOJI = "⬅️"
        CLOSE_EMOJI = "❌"
        RIGHT_EMOJI = "➡️"
        EMOJIS = [LEFT_EMOJI, CLOSE_EMOJI, RIGHT_EMOJI]

        def make_embed(page_num):
            embed = discord.Embed(
                title=f"Troops for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
                color=discord.Color.blue()
            )
            start = page_num * PAGE_SIZE
            end = start + PAGE_SIZE
            page_entries = troop_entries[start:end]

            for troop in page_entries:
                troop_name = troop.get("name", "Unknown")
                troop_level = troop.get("level", 0)
                troop_max = troop.get("maxLevel", 0)
                value = f"-# **Currently level {troop_level}/{troop_max}**"
                if len(value) > 1024:
                    value = value[:1021] + "..."
                field_name = f"{troop_name}"
                embed.add_field(
                    name=field_name,
                    value=value,
                    inline=True
                )
            embed.set_footer(text=f"Page {page_num+1}/{total_pages} • {len(troop_entries)} troops")
            return embed

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
                try:
                    await message.remove_reaction(LEFT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == RIGHT_EMOJI:
                if page < total_pages - 1:
                    page += 1
                    await message.edit(embed=make_embed(page))
                try:
                    await message.remove_reaction(RIGHT_EMOJI, user_)
                except Exception:
                    pass
            elif str(reaction.emoji) == CLOSE_EMOJI:
                try:
                    await message.delete()
                except Exception:
                    pass
                break

    @clash_player.command(name="heroes")
    async def clash_player_heroes(self, ctx, user: discord.User = None):
        """
        View player heroes and levels
        """

        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

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

        equipped_names = set()
        for hero in heroes:
            for eq in hero.get("equipment", []):
                if eq.get("name"):
                    equipped_names.add(eq["name"])

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
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed_heroes.add_field(
                name=f"{hero_name}",
                value=value,
                inline=True
            )

        await ctx.send(embed=embed_heroes)

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
                eq_lines = []
                for eq in unequipped:
                    eq_lines.append(
                        f"- {eq.get('name', 'Unknown')}\n-# Level {eq.get('level', 0)}/{eq.get('maxLevel', 0)}"
                    )
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

    @clash_player.command(name="spells")
    async def clash_player_spells(self, ctx, user: discord.User = None):
        """View player spells and levels"""
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

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

        embed_spells = discord.Embed(
            title=f"Spells for {player.get('name', 'Unknown')} ({player.get('tag', tag)})",
            color=discord.Color.teal()
        )

        for spell in spells:
            spell_name = spell.get("name", "Unknown")
            spell_level = spell.get("level", 0)
            spell_max = spell.get("maxLevel", 0)
            value = f"-# Level {spell_level}/{spell_max}"
            if len(value) > 1024:
                value = value[:1021] + "..."
            embed_spells.add_field(
                name=f"{spell_name}",
                value=value,
                inline=True
            )

        await ctx.send(embed=embed_spells)

    # --- LOGGING BACKGROUND TASK ---

    async def _log_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self._check_and_log_updates()
            except Exception as e:
                # You may want to log this exception
                pass
            await asyncio.sleep(300)  # 7 minutes

    async def _check_and_log_updates(self):
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            return

        # For each guild with logging enabled
        for guild in self.bot.guilds:
            try:
                log_channel_id = await self.config.guild(guild).log_channel()
                clan_tag = await self.config.guild(guild).clan_tag()
                roles_cfg = await self.config.guild(guild).roles()
                nickname_sync = await self.config.guild(guild).nickname_sync()
                if not log_channel_id or not clan_tag:
                    continue
                log_channel = guild.get_channel(log_channel_id)
                if not log_channel:
                    continue

                # Build a mapping of user_tag -> member for all linked, verified users in this guild
                tag_to_member = {}
                member_profiles = {}
                for member in guild.members:
                    if member.bot:
                        continue
                    user_tag = await self.config.user(member).tag()
                    verified = await self.config.user(member).verified()
                    if not user_tag or not verified:
                        continue
                    tag_to_member[user_tag.upper()] = member
                    # Preload last profile for donation correlation
                    last_profile = await self.config.user(member).last_profile()
                    member_profiles[user_tag.upper()] = {
                        "member": member,
                        "last_profile": last_profile,
                        "current_profile": None,  # will be filled after fetch
                    }

                # Fetch current player data for all linked users
                for user_tag, info in member_profiles.items():
                    player = await self.fetch_player_data(user_tag, dev_api_key)
                    if not player:
                        continue
                    # Check if player is in the correct clan
                    player_clan = player.get("clan", {}).get("tag", "")
                    if not player_clan or player_clan.upper() != clan_tag.upper():
                        continue
                    info["current_profile"] = player

                # Now process each member for role sync, nickname sync, and logging
                for user_tag, info in member_profiles.items():
                    member = info["member"]
                    player = info["current_profile"]
                    if not player:
                        continue

                    # --- ROLE ASSIGNMENT LOGIC ---
                    player_role = player.get("role", "").lower()
                    role_map = {
                        "member": "member",
                        "admin": "elder",
                        "coleader": "coleader",
                        "leader": "leader"
                    }
                    role_key = role_map.get(player_role, None)
                    all_role_ids = set(filter(None, [
                        roles_cfg.get("member"),
                        roles_cfg.get("elder"),
                        roles_cfg.get("coleader"),
                        roles_cfg.get("leader"),
                    ]))
                    correct_role_obj = None
                    if role_key and roles_cfg.get(role_key):
                        correct_role_obj = guild.get_role(roles_cfg[role_key])

                    roles_to_remove = []
                    for rid in all_role_ids:
                        role_obj = guild.get_role(rid)
                        if role_obj and role_obj in member.roles:
                            if correct_role_obj is None or role_obj.id != correct_role_obj.id:
                                roles_to_remove.append(role_obj)
                    for r in roles_to_remove:
                        try:
                            await member.remove_roles(r, reason="Clash of Clans role sync")
                        except Exception:
                            pass
                    if correct_role_obj and correct_role_obj not in member.roles:
                        try:
                            await member.add_roles(correct_role_obj, reason="Clash of Clans role sync")
                        except Exception:
                            pass

                    # --- NICKNAME SYNC LOGIC ---
                    if nickname_sync:
                        try:
                            coc_name = player.get("name", None)
                            if coc_name:
                                # Only change if different and bot has permission
                                # Discord max nickname length is 32
                                new_nick = coc_name[:32]
                                # Only change if different
                                if member.nick != new_nick:
                                    # Don't try to change if member is the guild owner
                                    if member != guild.owner:
                                        await member.edit(nick=new_nick, reason="Clash of Clans nickname sync")
                        except Exception:
                            pass

                    last_profile = info["last_profile"]
                    changes = self._detect_profile_changes(last_profile, player, member_profiles)
                    # --- Role promotion/demotion logging ---
                    if last_profile is not None:
                        old_role = (last_profile.get("role") or "").lower()
                        new_role = (player.get("role") or "").lower()
                        if old_role != new_role and old_role in role_map and new_role in role_map:
                            old_disp = old_role.capitalize()
                            new_disp = new_role.capitalize()
                            role_hierarchy = ["member", "admin", "coleader", "leader"]
                            try:
                                old_idx = role_hierarchy.index(old_role)
                                new_idx = role_hierarchy.index(new_role)
                                if new_idx > old_idx:
                                    changes.insert(0, f"### ⬆️ Was promoted\n-# **{old_disp}** → **{new_disp}**")
                                elif new_idx < old_idx:
                                    changes.insert(0, f"### ⬇️ Was demoted\n-# **{old_disp}** → **{new_disp}**")
                                else:
                                    changes.insert(0, f"### 🔄 Role changed\n-# **{old_disp}** → **{new_disp}**")
                            except Exception:
                                changes.insert(0, f"### 🔄 Role changed**\n-# **{old_disp}** → **{new_disp}**")

                    if changes:
                        embed = await self._build_log_embed(member, player, changes)
                        try:
                            await log_channel.send(embed=embed)
                        except Exception:
                            pass
                        await self.config.user(member).last_profile.set(player)
                    elif last_profile is None:
                        await self.config.user(member).last_profile.set(player)
                    await asyncio.sleep(1.2)
            except Exception:
                continue

    def _detect_profile_changes(self, old, new, member_profiles=None):
        """
        Return a list of change strings if anything interesting changed, including achievements, spells, troops, hero equipment, and heroes.
        If member_profiles is provided, attempt to correlate troop donations to other linked users.
        """
        if not old:
            return []
        changes = []
        # Attack wins
        if old.get("attackWins") != new.get("attackWins"):
            diff = (new.get("attackWins") or 0) - (old.get("attackWins") or 0)
            if diff > 0:
                changes.append(f"🏆 Won {diff} attack{'s' if diff > 1 else ''}|**{new.get('attackWins')} successful attacks this season**")
        # Defense wins
        if old.get("defenseWins") != new.get("defenseWins"):
            diff = (new.get("defenseWins") or 0) - (old.get("defenseWins") or 0)
            if diff > 0:
                changes.append(f"🛡️ Won {diff} defense{'s' if diff > 1 else ''}|**{new.get('defenseWins')} successful defenses this season**")
        # League change
        old_league = old.get("league", {}).get("name") if old.get("league") else None
        new_league = new.get("league", {}).get("name") if new.get("league") else None
        if old_league != new_league:
            if old_league and new_league:
                changes.append(f"🏅 Changed leagues|**{old_league} → {new_league}**")
            elif new_league:
                changes.append(f"🏅 Entered league|**{new_league}**")
            elif old_league:
                changes.append(f"🏅 Left league|**{old_league}**")
        # Trophies
        if old.get("trophies") != new.get("trophies"):
            diff = (new.get("trophies") or 0) - (old.get("trophies") or 0)
            if diff > 0:
                changes.append(f"📈 Gained {diff} trophies|**{new.get('trophies')} trophies now**")
            elif diff < 0:
                changes.append(f"📉 Lost {abs(diff)} trophies|**{new.get('trophies')} trophies now**")
        # Donations
        if old.get("donations") != new.get("donations"):
            diff = (new.get("donations") or 0) - (old.get("donations") or 0)
            if diff > 0:
                # Try to correlate which linked user received the donations
                donation_details = ""
                if member_profiles is not None:
                    # For each other member, see if their donationsReceived increased by a matching amount
                    # Build a list of (member, diff) for those who received troops
                    receivers = []
                    for tag, info in member_profiles.items():
                        if not info["last_profile"] or not info["current_profile"]:
                            continue
                        if info["current_profile"].get("tag", "").upper() == new.get("tag", "").upper():
                            continue  # skip self
                        old_recv = info["last_profile"].get("donationsReceived", 0)
                        new_recv = info["current_profile"].get("donationsReceived", 0)
                        recv_diff = (new_recv or 0) - (old_recv or 0)
                        if recv_diff > 0:
                            receivers.append((info["member"], recv_diff))
                    # Try to match the total diff
                    total_received = sum(r[1] for r in receivers)
                    if receivers and total_received > 0:
                        # If the total received matches the donation diff, show the breakdown
                        if total_received == diff:
                            donation_details = "\n".join(
                                f"**Sent to {receiver.display_name}**|**{recv_diff} troop{'s' if recv_diff > 1 else ''}**"
                                for receiver, recv_diff in receivers
                            )
                        else:
                            # If not all donations can be matched, show only the receivers that can be matched up to the diff
                            sorted_receivers = sorted(receivers, key=lambda x: -x[1])
                            running_total = 0
                            partial_lines = []
                            for receiver, recv_diff in sorted_receivers:
                                if running_total + recv_diff > diff:
                                    partial = diff - running_total
                                    if partial > 0:
                                        partial_lines.append(
                                            f"At least sent to {receiver.display_name}|**{partial} troop{'s' if partial > 1 else ''}**"
                                        )
                                    break
                                else:
                                    partial_lines.append(
                                        f"At least sent to {receiver.display_name}|**{recv_diff} troop{'s' if recv_diff > 1 else ''}**"
                                    )
                                    running_total += recv_diff
                                    if running_total >= diff:
                                        break
                            donation_details = "\n".join(partial_lines)
                            donation_details += f"\nOther Recipients|Could not determine all recipients, total sent: {diff}"
                if not donation_details:
                    donation_details = f"Total donations sent|**{new.get('donations')} donations sent this season**"
                changes.append(f"📤 Donated {diff} troop{'s' if diff > 1 else ''}|{donation_details}")
        # Donations received
        if old.get("donationsReceived") != new.get("donationsReceived"):
            diff = (new.get("donationsReceived") or 0) - (old.get("donationsReceived") or 0)
            if diff > 0:
                # Try to correlate which linked user sent the troops
                received_details = ""
                if member_profiles is not None:
                    # For each other member, see if their donations increased by a matching amount
                    senders = []
                    for tag, info in member_profiles.items():
                        if not info["last_profile"] or not info["current_profile"]:
                            continue
                        if info["current_profile"].get("tag", "").upper() == new.get("tag", "").upper():
                            continue  # skip self
                        old_sent = info["last_profile"].get("donations", 0)
                        new_sent = info["current_profile"].get("donations", 0)
                        sent_diff = (new_sent or 0) - (old_sent or 0)
                        if sent_diff > 0:
                            senders.append((info["member"], sent_diff))
                    total_sent = sum(s[1] for s in senders)
                    if senders and total_sent > 0:
                        if total_sent == diff:
                            received_details = "\n".join(
                                f"Received from {sender.display_name}|**{sent_diff} troop{'s' if sent_diff > 1 else ''}**"
                                for sender, sent_diff in senders
                            )
                        else:
                            # Only show senders up to the diff, to avoid confusion
                            sorted_senders = sorted(senders, key=lambda x: -x[1])
                            running_total = 0
                            partial_lines = []
                            for sender, sent_diff in sorted_senders:
                                if running_total + sent_diff > diff:
                                    partial = diff - running_total
                                    if partial > 0:
                                        partial_lines.append(
                                            f"At least from {sender.display_name}|**{partial} troop{'s' if partial > 1 else ''}**"
                                        )
                                    break
                                else:
                                    partial_lines.append(
                                        f"At least from {sender.display_name}|**{sent_diff} troop{'s' if sent_diff > 1 else ''}**"
                                    )
                                    running_total += sent_diff
                                    if running_total >= diff:
                                        break
                            received_details = "\n".join(partial_lines)
                            received_details += f"\nOther Senders|Could not determine all senders, total received: {diff}"
                if not received_details:
                    received_details = f"Total donations received|**{new.get('donationsReceived')} donations received this season**"
                # Always use \n as a divider for received_details if it contains a pipe but not a newline
                if "|" in received_details and "\n" not in received_details:
                    received_details = received_details.replace("|", "\n", 1)
                changes.append(f"📥 Received {diff} troop{'s' if diff > 1 else ''}|{received_details}")
        # War stars
        if old.get("warStars") != new.get("warStars"):
            diff = (new.get("warStars") or 0) - (old.get("warStars") or 0)
            if diff > 0:
                changes.append(f"⭐ Gained {diff} war star{'s' if diff > 1 else ''}|**{new.get('warStars')} war stars now**")
        # Clan capital contributions
        if old.get("clanCapitalContributions") != new.get("clanCapitalContributions"):
            diff = (new.get("clanCapitalContributions") or 0) - (old.get("clanCapitalContributions") or 0)
            if diff > 0:
                changes.append(f"🏛️ Contributed {diff} Capital Gold to clan|**{new.get('clanCapitalContributions')} Capital Gold donated this season**")
        # Town Hall level
        if old.get("townHallLevel") != new.get("townHallLevel"):
            changes.append(f"🏰 Town Hall upgraded|**{old.get('townHallLevel')}** → **{new.get('townHallLevel')}**")
        # Builder Hall level
        if old.get("builderHallLevel") != new.get("builderHallLevel"):
            changes.append(f"🏚️ Builder Hall upgraded|**{old.get('builderHallLevel')}** → **{new.get('builderHallLevel')}**")
        # Name change
        if old.get("name") != new.get("name"):
            changes.append(f"📝 Changed name|**{old.get('name')}** → **{new.get('name')}**")
        # War Preference (opted in/out of Clan Wars)
        if old.get("warPreference") != new.get("warPreference"):
            old_pref = old.get("warPreference")
            new_pref = new.get("warPreference")
            pref_map = {"in": "Participating", "out": "Not participating"}
            old_disp = pref_map.get(old_pref, old_pref or "Unknown")
            new_disp = pref_map.get(new_pref, new_pref or "Unknown")
            changes.append(f"⚔️ Clan War election changed|**{old_disp} → {new_disp}**")

        # --- Achievement completion/upgrade/progress events ---
        old_achs = {a["name"]: a for a in old.get("achievements", []) if "name" in a}
        new_achs = {a["name"]: a for a in new.get("achievements", []) if "name" in a}
        for ach_name, new_ach in new_achs.items():
            old_ach = old_achs.get(ach_name)
            if not old_ach:
                if new_ach.get("stars", 0) > 0:
                    # Show progress in the value
                    progress = f"{new_ach.get('value', 0)}/{new_ach.get('target', 0)}"
                    changes.append(f"🎖️ New achievement unlocked|**{ach_name}**\n**{new_ach.get('stars', 0)}⭐ {progress}**")
                continue
            old_stars = old_ach.get("stars", 0)
            new_stars = new_ach.get("stars", 0)
            old_value = old_ach.get("value", 0)
            new_value = new_ach.get("value", 0)
            target = new_ach.get("target", 0)
            # Achievement upgraded (stars increased)
            if new_stars > old_stars:
                progress = f"{new_ach.get('value', 0)}/{new_ach.get('target', 0)}"
                changes.append(
                    f"🎖️ Achievement upgraded|**{ach_name}**\nLv{old_stars} → Lv{new_stars}\n({progress})"
                )
            # Achievement completed (value reached target, but stars did not increase)
            if new_value >= target and old_value < target and new_stars == old_stars:
                progress = f"{old_value} → {new_value}/{target}"
                changes.append(
                    f"🎉 Achievement completed|**{ach_name}** ({new_stars}⭐)\n{progress}"
                )
            # Achievement progress (value increased, but not completed or upgraded)
            if (
                new_value > old_value
                and (new_value < target or new_stars == old_stars)
                and new_stars == old_stars
            ):
                progress = f"{old_value} → {new_value}/{target}"
                changes.append(
                    f"⏳ Achievement progress|**{ach_name}**\n{progress}"
                )

        # --- Spells, Troops, Heroes, Hero Equipment upgrades ---
        def log_upgrade(old_list, new_list, key_name, emoji):
            old_map = {item["name"]: item for item in old_list if "name" in item}
            new_map = {item["name"]: item for item in new_list if "name" in item}
            for name, new_item in new_map.items():
                old_item = old_map.get(name)
                if not old_item:
                    continue
                old_level = old_item.get("level", 0)
                new_level = new_item.get("level", 0)
                if new_level > old_level:
                    msg = f"{emoji} {key_name} upgraded|**{name}**\n{old_level} → {new_level}"
                    changes.append(msg)

        log_upgrade(
            old.get("spells", []),
            new.get("spells", []),
            "Spell",
            "🧪"
        )
        log_upgrade(
            old.get("troops", []),
            new.get("troops", []),
            "Troop",
            "⚔️"
        )
        log_upgrade(
            old.get("heroes", []),
            new.get("heroes", []),
            "Hero",
            "🦸"
        )
        log_upgrade(
            old.get("heroEquipment", []),
            new.get("heroEquipment", []),
            "Hero equipment",
            "🛡️",
        )

        return changes

    async def _build_log_embed(self, member, player, changes):
        color = 0x4b4b4b
        author_icon_url = None

        if player.get("league"):
            league_icon = player["league"].get("iconUrls", {}).get("medium")
            if league_icon:
                author_icon_url = league_icon
        elif player.get("clan"):
            clan_icon = player["clan"].get("badgeUrls", {}).get("medium")
            if clan_icon:
                author_icon_url = clan_icon

        if author_icon_url:
            color_from_img = await get_brightest_color_from_url(author_icon_url)
            if color_from_img:
                color = color_from_img

        tag_line = f"{player.get('tag', '')}"
        embed = discord.Embed(
            color=color
        )
        embed.set_author(
            name=f"{player.get('name', 'Unknown')}",
            icon_url=author_icon_url if author_icon_url else discord.Embed.Empty
        )
        footer_text = f"{member} | {member.id}"
        if tag_line.strip():
            footer_text = f"{tag_line} | {footer_text}"
        embed.set_footer(text=footer_text)

        # Add each change as a field
        for change in changes:
            # If the change contains a pipe, treat as "title|value"
            if "|" in change:
                for line in change.split("\n"):
                    if "|" in line:
                        title, value = line.split("|", 1)
                        # If the value itself still contains a pipe and no newline, replace the first pipe with a newline
                        if "|" in value and "\n" not in value:
                            value = value.replace("|", "\n", 1)
                        embed.add_field(name=title.strip(), value=f"-# {value.strip()}", inline=True)
            else:
                # fallback: add as a generic field
                embed.add_field(name="Change", value=change, inline=False)
        return embed
