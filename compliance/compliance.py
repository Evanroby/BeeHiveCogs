import discord
from red_commons.logging import getLogger
from redbot.core import commands, Config, checks, app_commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list

log = getLogger("red.beehive.compliance")

class ComplianceManager(commands.Cog):
    """
    Compliance Manager for Guilds

    Enforce and manage requirements for which guilds your bot is allowed to be in.
    """

    __version__ = "1.0.0"
    __author__ = "BeeHive"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xBEEBEEBEE, force_registration=True)
        default_global = {
            "allowed_guilds": [],
            "blocked_guilds": [],
            "min_member_count": 0,
            "requirements_enabled": False,
            "enforcement_interval": 3600,  # seconds
            "log_channel": None,
        }
        self.config.register_global(**default_global)
        self._enforcement_task = bot.loop.create_task(self._enforce_loop())

    def cog_unload(self):
        self._enforcement_task.cancel()

    async def _enforce_loop(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.enforce_compliance()
            except Exception as e:
                log.exception("Error during compliance enforcement: %s", e)
            interval = await self.config.enforcement_interval()
            await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(seconds=interval))

    async def enforce_compliance(self):
        enabled = await self.config.requirements_enabled()
        if not enabled:
            return
        allowed = await self.config.allowed_guilds()
        blocked = await self.config.blocked_guilds()
        min_members = await self.config.min_member_count()
        log_channel_id = await self.config.log_channel()
        log_channel = None
        if log_channel_id:
            log_channel = self.bot.get_channel(log_channel_id)
        left_guilds = []
        for guild in self.bot.guilds:
            if guild.id in blocked:
                await guild.leave()
                left_guilds.append((guild, "blocked"))
                continue
            if allowed and guild.id not in allowed:
                await guild.leave()
                left_guilds.append((guild, "not allowed"))
                continue
            if min_members and guild.member_count < min_members:
                await guild.leave()
                left_guilds.append((guild, "too small"))
        if left_guilds and log_channel:
            msg = "Compliance Enforcement: Left the following guilds:\n"
            for g, reason in left_guilds:
                msg += f"- {g.name} ({g.id}) [{reason}]\n"
            await log_channel.send(box(msg, lang="md"))

    @commands.group(name="compliance", invoke_without_command=True)
    @checks.is_owner()
    async def compliance(self, ctx):
        """Compliance manager for guilds."""
        await ctx.send_help()

    @compliance.command(name="enable")
    @checks.is_owner()
    async def compliance_enable(self, ctx):
        """Enable compliance enforcement."""
        await self.config.requirements_enabled.set(True)
        await ctx.send("✅ Compliance enforcement enabled.")

    @compliance.command(name="disable")
    @checks.is_owner()
    async def compliance_disable(self, ctx):
        """Disable compliance enforcement."""
        await self.config.requirements_enabled.set(False)
        await ctx.send("❌ Compliance enforcement disabled.")

    @compliance.command(name="addallowed")
    @checks.is_owner()
    async def compliance_add_allowed(self, ctx, guild_id: int):
        """Add a guild to the allowed list."""
        allowed = await self.config.allowed_guilds()
        if guild_id not in allowed:
            allowed.append(guild_id)
            await self.config.allowed_guilds.set(allowed)
            await ctx.send(f"✅ Guild `{guild_id}` added to allowed list.")
        else:
            await ctx.send("Guild already in allowed list.")

    @compliance.command(name="removeallowed")
    @checks.is_owner()
    async def compliance_remove_allowed(self, ctx, guild_id: int):
        """Remove a guild from the allowed list."""
        allowed = await self.config.allowed_guilds()
        if guild_id in allowed:
            allowed.remove(guild_id)
            await self.config.allowed_guilds.set(allowed)
            await ctx.send(f"✅ Guild `{guild_id}` removed from allowed list.")
        else:
            await ctx.send("Guild not in allowed list.")

    @compliance.command(name="addblocked")
    @checks.is_owner()
    async def compliance_add_blocked(self, ctx, guild_id: int):
        """Add a guild to the blocked list."""
        blocked = await self.config.blocked_guilds()
        if guild_id not in blocked:
            blocked.append(guild_id)
            await self.config.blocked_guilds.set(blocked)
            await ctx.send(f"✅ Guild `{guild_id}` added to blocked list.")
        else:
            await ctx.send("Guild already in blocked list.")

    @compliance.command(name="removeblocked")
    @checks.is_owner()
    async def compliance_remove_blocked(self, ctx, guild_id: int):
        """Remove a guild from the blocked list."""
        blocked = await self.config.blocked_guilds()
        if guild_id in blocked:
            blocked.remove(guild_id)
            await self.config.blocked_guilds.set(blocked)
            await ctx.send(f"✅ Guild `{guild_id}` removed from blocked list.")
        else:
            await ctx.send("Guild not in blocked list.")

    @compliance.command(name="minmembers")
    @checks.is_owner()
    async def compliance_min_members(self, ctx, count: int):
        """Set the minimum member count for a guild to be compliant."""
        await self.config.min_member_count.set(count)
        await ctx.send(f"✅ Minimum member count set to {count}.")

    @compliance.command(name="interval")
    @checks.is_owner()
    async def compliance_set_interval(self, ctx, seconds: int):
        """Set the enforcement interval in seconds."""
        await self.config.enforcement_interval.set(seconds)
        await ctx.send(f"✅ Enforcement interval set to {seconds} seconds.")

    @compliance.command(name="logchannel")
    @checks.is_owner()
    async def compliance_set_logchannel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel for compliance logs. Omit to clear."""
        if channel:
            await self.config.log_channel.set(channel.id)
            await ctx.send(f"✅ Log channel set to {channel.mention}.")
        else:
            await self.config.log_channel.set(None)
            await ctx.send("✅ Log channel cleared.")

    @compliance.command(name="status")
    @checks.is_owner()
    async def compliance_status(self, ctx):
        """Show current compliance settings and guilds."""
        enabled = await self.config.requirements_enabled()
        allowed = await self.config.allowed_guilds()
        blocked = await self.config.blocked_guilds()
        min_members = await self.config.min_member_count()
        interval = await self.config.enforcement_interval()
        log_channel_id = await self.config.log_channel()
        log_channel = ctx.guild.get_channel(log_channel_id) if log_channel_id else None
        msg = (
            f"**Compliance Status**\n"
            f"Enabled: `{enabled}`\n"
            f"Allowed Guilds: {box(', '.join(str(i) for i in allowed) or 'None', lang='py')}\n"
            f"Blocked Guilds: {box(', '.join(str(i) for i in blocked) or 'None', lang='py')}\n"
            f"Min Member Count: `{min_members}`\n"
            f"Enforcement Interval: `{interval}` seconds\n"
            f"Log Channel: {log_channel.mention if log_channel else 'Not set'}\n"
        )
        await ctx.send(msg)

    @compliance.command(name="listguilds")
    @checks.is_owner()
    async def compliance_list_guilds(self, ctx):
        """List all guilds the bot is currently in."""
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        lines = []
        for g in guilds:
            lines.append(f"{g.name} ({g.id}) - {g.member_count} members")
        await ctx.send(box("\n".join(lines), lang="md"))

    @compliance.command(name="enforce")
    @checks.is_owner()
    async def compliance_enforce_now(self, ctx):
        """Run compliance enforcement immediately."""
        await self.enforce_compliance()
        await ctx.send("✅ Compliance enforcement run complete.")

    @compliance.command(name="guildinfo")
    @checks.is_owner()
    async def compliance_guild_info(self, ctx, guild_id: int):
        """
        Fetch information about any server the bot is in by guild ID.
        """
        guild = self.bot.get_guild(guild_id)
        if not guild:
            await ctx.send(f"❌ I am not in a guild with ID `{guild_id}`.")
            return

        owner = guild.owner
        created_at = guild.created_at.strftime("%Y-%m-%d %H:%M:%S")
        features = ", ".join(guild.features) if guild.features else "None"
        icon_url = guild.icon.url if guild.icon else None

        embed = discord.Embed(
            title=f"{guild.name} ({guild.id})",
            color=discord.Color.blurple(),
            description=f"**Owner:** {owner} ({owner.id})\n"
                        f"**Members:** {guild.member_count}\n"
                        f"**Created:** {created_at}\n"
                        f"**Region:** {getattr(guild, 'region', 'N/A')}\n"
                        f"**Features:** {features}\n"
                        f"**Verification Level:** {guild.verification_level.name}\n"
                        f"**MFA Level:** {'Enabled' if guild.mfa_level else 'Disabled'}\n"
                        f"**Partnered:** {'Yes' if 'PARTNERED' in guild.features else 'No'}\n"
                        f"**Vanity URL:** {guild.vanity_url_code or 'None'}"
        )
        if icon_url:
            embed.set_thumbnail(url=icon_url)
        # Show up to 5 top roles (by position, excluding @everyone)
        roles = [r for r in guild.roles if r.name != "@everyone"]
        if roles:
            top_roles = sorted(roles, key=lambda r: r.position, reverse=True)[:5]
            embed.add_field(
                name="Top Roles",
                value=", ".join(r.mention for r in top_roles),
                inline=False
            )
        # Show up to 5 text channels
        text_channels = [c for c in guild.text_channels if c.permissions_for(guild.me).read_messages]
        if text_channels:
            top_channels = text_channels[:5]
            embed.add_field(
                name="Text Channels",
                value=", ".join(f"#{c.name}" for c in top_channels),
                inline=False
            )
        await ctx.send(embed=embed)

