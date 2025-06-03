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
        # Guild config: log_channel, clan_tag, role settings, autokick_enabled
        default_guild = {
            "log_channel": None,
            "clan_tag": None,
            "roles": {
                "member": None,
                "elder": None,
                "coleader": None,
                "leader": None
            },
            "autokick_enabled": False
        }
        self.config.register_guild(**default_guild)
        self._log_task = self.bot.loop.create_task(self._log_loop())
        self._autokick_task = self.bot.loop.create_task(self._autokick_loop())

    def cog_unload(self):
        if hasattr(self, "_log_task"):
            self._log_task.cancel()
        if hasattr(self, "_autokick_task"):
            self._autokick_task.cancel()

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

    # --- AUTOKICK COMMAND ---
    @clash_clan.command(name="autokick")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def clash_clan_autokick(self, ctx, *, reason: str = None):
        """
        Kick all users from the server who have a linked and verified Clash of Clans account
        but whose in-game clan tag does not match the server's configured clan tag.

        Optionally provide a reason for the kick.
        """
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            await ctx.send("Developer API key is not set up. Please contact the bot owner.")
            return

        clan_tag = await self.config.guild(ctx.guild).clan_tag()
        if not clan_tag:
            await ctx.send("This server does not have a clan tag set. Use `clash logs clantag #TAG` first.")
            return

        # Confirm action
        await ctx.send(
            f"⚠️ This will kick all users with a linked and verified Clash of Clans account whose clan tag does not match **{clan_tag}**.\n"
            f"Type `yes` to confirm, or anything else to cancel."
        )
        try:
            confirm_msg = await ctx.bot.wait_for(
                "message",
                timeout=30.0,
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel
            )
        except asyncio.TimeoutError:
            await ctx.send("Autokick cancelled due to timeout.")
            return

        if confirm_msg.content.strip().lower() != "yes":
            await ctx.send("Autokick cancelled.")
            return

        kicked = []
        failed = []
        checked = 0

        await ctx.send("⏳ Checking members and kicking as needed. This may take a while for large servers...")

        for member in ctx.guild.members:
            if member.bot:
                continue
            try:
                user_tag = await self.config.user(member).tag()
                verified = await self.config.user(member).verified()
                if not user_tag or not verified:
                    continue
                player = await self.fetch_player_data(user_tag, dev_api_key)
                checked += 1
                if not player:
                    continue
                player_clan = player.get("clan", {}).get("tag", "")
                if not player_clan or player_clan.upper() == clan_tag.upper():
                    continue  # In correct clan, do not kick
                # Try to kick
                try:
                    await member.kick(reason=reason or f"Clash of Clans autokick: not in clan {clan_tag}")
                    kicked.append((member, player_clan))
                except Exception:
                    failed.append((member, player_clan))
                await asyncio.sleep(1.2)  # avoid rate limits
            except Exception:
                continue

        msg = (
            f"Autokick complete.\n"
            f"Checked {checked} linked/verified members.\n"
            f"Kicked: {len(kicked)}\n"
            f"Failed: {len(failed)}"
        )
        if kicked:
            msg += "\n\n**Kicked users:**\n"
            msg += "\n".join(
                f"- {m.mention} (CoC clan: {c or 'None'})" for m, c in kicked
            )
        if failed:
            msg += "\n\n**Failed to kick:**\n"
            msg += "\n".join(
                f"- {m.mention} (CoC clan: {c or 'None'})" for m, c in failed
            )
        await ctx.send(msg)

    @clash_clan.command(name="autokicktoggle")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def clash_clan_autokicktoggle(self, ctx):
        """
        Toggle automatic autokick: when enabled, the bot will check and remove users not in the configured clan every 30 minutes.
        """
        enabled = await self.config.guild(ctx.guild).autokick_enabled()
        await self.config.guild(ctx.guild).autokick_enabled.set(not enabled)
        if not enabled:
            await ctx.send("✅ Automatic autokick is now **enabled**. The bot will check and remove users not in the configured clan every 30 minutes.")
        else:
            await ctx.send("❌ Automatic autokick is now **disabled**.")

    @clash_clan.command(name="autokickstatus")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def clash_clan_autokickstatus(self, ctx):
        """
        Show whether automatic autokick is enabled for this server.
        """
        enabled = await self.config.guild(ctx.guild).autokick_enabled()
        await ctx.send(f"Automatic autokick is currently **{'enabled' if enabled else 'disabled'}** for this server.")

    async def _autokick_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self._autokick_check_all_guilds()
            except Exception:
                pass
            await asyncio.sleep(1800)  # 30 minutes

    async def _autokick_check_all_guilds(self):
        dev_api_key = await self.get_dev_api_key()
        if not dev_api_key:
            return

        for guild in self.bot.guilds:
            try:
                autokick_enabled = await self.config.guild(guild).autokick_enabled()
                clan_tag = await self.config.guild(guild).clan_tag()
                if not autokick_enabled or not clan_tag:
                    continue

                # Optionally, you could log to a channel or DM admins if you want
                kicked = []
                failed = []
                checked = 0

                for member in guild.members:
                    if member.bot:
                        continue
                    try:
                        user_tag = await self.config.user(member).tag()
                        verified = await self.config.user(member).verified()
                        if not user_tag or not verified:
                            continue
                        player = await self.fetch_player_data(user_tag, dev_api_key)
                        checked += 1
                        if not player:
                            continue
                        player_clan = player.get("clan", {}).get("tag", "")
                        if not player_clan or player_clan.upper() == clan_tag.upper():
                            continue  # In correct clan, do not kick
                        # Try to kick
                        try:
                            await member.kick(reason=f"Clash of Clans autokick: not in clan {clan_tag}")
                            kicked.append((member, player_clan))
                        except Exception:
                            failed.append((member, player_clan))
                        await asyncio.sleep(1.2)  # avoid rate limits
                    except Exception:
                        continue

                # Optionally, send a summary to the log channel if set
                log_channel_id = await self.config.guild(guild).log_channel()
                log_channel = guild.get_channel(log_channel_id) if log_channel_id else None
                if log_channel and (kicked or failed):
                    msg = (
                        f"Checked {checked} linked players.\n"
                        f"Kicked: {len(kicked)}\n"
                        f"Failed: {len(failed)}"
                    )
                    if kicked:
                        msg += "\n\n**Kicked users:**\n"
                        msg += "\n".join(
                            f"- {m.mention} (CoC clan: {c or 'None'})" for m, c in kicked
                        )
                    if failed:
                        msg += "\n\n**Failed to kick:**\n"
                        msg += "\n".join(
                            f"- {m.mention} (CoC clan: {c or 'None'})" for m, c in failed
                        )
                    try:
                        await log_channel.send(msg)
                    except Exception:
                        pass

            except Exception:
                continue

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
                await ctx.send("You have not linked and verified your Clash of Clans account. Use `clash profile link` first.")
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

    # ... rest of the code unchanged ...



