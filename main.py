import os
import io
import asyncio
import time
from datetime import timedelta

import discord
from discord.ext import commands, tasks

# ───────────── CONFIG (Railway Variables) ─────────────
TOKEN = os.getenv("DISCORD_TOKEN")
CATEGORY_ID = int(os.getenv("ESPORT_CATEGORY_ID", "0"))        # category for tickets
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))           # staff who review
ESPORT_ROLE_ID = int(os.getenv("ESPORT_ROLE_ID", "0"))         # role given on Accept (optional)
LOG_CHANNEL_ID = int(os.getenv("ESPORT_LOG_CHANNEL_ID", "0"))  # transcripts + logs (optional)
GUILD_ID = int(os.getenv("GUILD_ID", "0"))                     # only used to clear old slash commands (optional)

COLOR = 0x9B59FF
COOLDOWN_SECONDS = 60       # anti-spam between ticket opens
INACTIVE_HOURS = 24         # auto close if nobody writes
BANNER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esport_banner.gif")

cooldowns = {}
clip_seen = set()


# ───────────── HELPERS ─────────────
def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == STAFF_ROLE_ID for r in member.roles)


def ticket_owner_id(channel) -> int | None:
    topic = getattr(channel, "topic", None)
    if topic and topic.startswith("esport:"):
        try:
            return int(topic.split(":")[1])
        except ValueError:
            return None
    return None


async def staff_only(interaction: discord.Interaction) -> bool:
    if is_staff(interaction.user):
        return True
    await interaction.response.send_message("❌ Staff only.", ephemeral=True)
    return False


async def make_transcript(channel: discord.TextChannel) -> discord.File:
    lines = []
    async for m in channel.history(limit=None, oldest_first=True):
        ts = m.created_at.strftime("%Y-%m-%d %H:%M")
        extra = " ".join(a.url for a in m.attachments)
        lines.append(f"[{ts}] {m.author}: {m.content} {extra}".strip())
    data = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(data, filename=f"{channel.name}.txt")


async def send_log(guild: discord.Guild, embed: discord.Embed, file: discord.File | None = None):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(embed=embed, file=file)
        except Exception as e:
            print("log error:", e)


async def close_ticket(channel: discord.TextChannel, reason: str):
    owner_id = ticket_owner_id(channel)
    try:
        file = await make_transcript(channel)
        embed = discord.Embed(
            title="📁 Esport Ticket Closed",
            description=f"**Channel:** #{channel.name}\n**Applicant:** <@{owner_id}>\n**Reason:** {reason}",
            color=COLOR,
        )
        await send_log(channel.guild, embed, file)
    except Exception as e:
        print("transcript error:", e)
    clip_seen.discard(channel.id)
    await channel.delete()


# ───────────── TICKET BUTTONS ─────────────
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary,
                       emoji="🙋", custom_id="esport_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await staff_only(interaction):
            return
        await interaction.response.defer()
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"[:80]
        await interaction.message.edit(view=self)
        await interaction.channel.send(f"🙋 {interaction.user.mention} will review this application.")

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success,
                       emoji="✅", custom_id="esport_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await staff_only(interaction):
            return
        await interaction.response.defer()
        owner_id = ticket_owner_id(interaction.channel)
        member = interaction.guild.get_member(owner_id) if owner_id else None
        role = interaction.guild.get_role(ESPORT_ROLE_ID)
        if member and role:
            try:
                await member.add_roles(role, reason="Esport application accepted")
            except Exception as e:
                print("role error:", e)
        for child in self.children:
            if child.custom_id in ("esport_accept", "esport_deny"):
                child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.channel.send(embed=discord.Embed(
            title="✅ APPLICATION ACCEPTED",
            description=f"<@{owner_id}> welcome to the **Esport Team**! 🏆\nAccepted by {interaction.user.mention}",
            color=0x2ECC71))
        if member:
            try:
                await member.send(f"✅ Your Esport application in **{interaction.guild.name}** was **accepted**! 🏆")
            except Exception:
                pass
        await send_log(interaction.guild, discord.Embed(
            title="✅ Esport Accepted",
            description=f"<@{owner_id}> accepted by {interaction.user.mention}", color=0x2ECC71))

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger,
                       emoji="⛔", custom_id="esport_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await staff_only(interaction):
            return
        await interaction.response.defer()
        owner_id = ticket_owner_id(interaction.channel)
        member = interaction.guild.get_member(owner_id) if owner_id else None
        for child in self.children:
            if child.custom_id in ("esport_accept", "esport_deny"):
                child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.channel.send(embed=discord.Embed(
            title="⛔ APPLICATION DENIED",
            description=f"<@{owner_id}> your application was not accepted this time.\nDenied by {interaction.user.mention}",
            color=0xE74C3C))
        if member:
            try:
                await member.send(f"⛔ Your Esport application in **{interaction.guild.name}** was **denied**. You can try again later.")
            except Exception:
                pass
        await send_log(interaction.guild, discord.Embed(
            title="⛔ Esport Denied",
            description=f"<@{owner_id}> denied by {interaction.user.mention}", color=0xE74C3C))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary,
                       emoji="🔒", custom_id="esport_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        owner_id = ticket_owner_id(interaction.channel)
        if not (interaction.user.id == owner_id or is_staff(interaction.user)):
            return await interaction.response.send_message("❌ You can't close this ticket.", ephemeral=True)
        await interaction.response.send_message("🔒 Closing in 5 seconds... transcript is being saved.")
        await asyncio.sleep(5)
        await close_ticket(interaction.channel, f"Closed by {interaction.user}")


# ───────────── PANEL BUTTON ─────────────
class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Esport Team", style=discord.ButtonStyle.secondary,
                       emoji="🎮", custom_id="esport_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, user = interaction.guild, interaction.user

        left = COOLDOWN_SECONDS - (time.time() - cooldowns.get(user.id, 0))
        if left > 0:
            return await interaction.response.send_message(
                f"⏳ Please wait {int(left)}s before trying again.", ephemeral=True)

        if ESPORT_ROLE_ID and any(r.id == ESPORT_ROLE_ID for r in user.roles):
            return await interaction.response.send_message("✅ You are already in the Esport Team.", ephemeral=True)

        category = guild.get_channel(CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message("❌ Esport category is not set up. Tell an admin.", ephemeral=True)

        existing = discord.utils.find(lambda c: c.topic == f"esport:{user.id}", category.text_channels)
        if existing:
            return await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}", ephemeral=True)

        if len(category.channels) >= 50:
            return await interaction.response.send_message(
                "📛 Applications are full right now. Please try again in a bit.", ephemeral=True)

        cooldowns[user.id] = time.time()
        await interaction.response.defer(ephemeral=True)

        staff = guild.get_role(STAFF_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                              embed_links=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                  manage_channels=True, read_message_history=True),
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                            attach_files=True, read_message_history=True)

        channel = await guild.create_text_channel(
            name=f"esport-{user.name}", category=category,
            topic=f"esport:{user.id}", overwrites=overwrites)

        embed = discord.Embed(
            title="🎮 ESPORT TEAM APPLICATION",
            description=(
                f"Welcome {user.mention}!\n\n"
                "Please send the following in this ticket:\n\n"
                "**1️⃣ What do you play?**\n"
                "**2️⃣ Send a clip** of your gameplay 🎥\n\n"
                "Staff will review your application soon."
            ),
            color=COLOR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="ELT Esport • Good luck!")
        ping = staff.mention if staff else ""
        await channel.send(content=f"{user.mention} {ping}", embed=embed, view=TicketView())
        await interaction.followup.send(f"✅ Your ticket is ready: {channel.mention}", ephemeral=True)


# ───────────── BOT ─────────────
class EsportBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(JoinView())
        self.add_view(TicketView())
        # Prefix-only bot: push an EMPTY slash tree once so the old /esportpanel disappears.
        # (You can delete this block after the first successful start.)
        try:
            await self.tree.sync()
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        except Exception as e:
            print("slash clear error:", e)
        auto_close.start()


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = EsportBot(command_prefix="!", intents=intents)


async def post_panel(channel: discord.abc.Messageable):
    embed = discord.Embed(
        title="🏆 JOIN THE ESPORT TEAM",
        description=(
            "Do you want to compete and represent the server?\n\n"
            "🎮 Click the button below to open a ticket\n"
            "📝 Tell us **what you play**\n"
            "🎥 Send us **a clip** of your gameplay\n\n"
            "We will check your application and get back to you."
        ),
        color=COLOR,
    )
    embed.set_footer(text="ELT Esport • Apply now")
    if os.path.exists(BANNER_PATH):
        embed.set_image(url="attachment://esport_banner.gif")
        await channel.send(embed=embed, view=JoinView(),
                           file=discord.File(BANNER_PATH, filename="esport_banner.gif"))
    else:
        await channel.send(embed=embed, view=JoinView())


@bot.command()
@commands.has_permissions(administrator=True)
async def esportpanel(ctx):
    await post_panel(ctx.channel)
    try:
        await ctx.message.delete()
    except Exception:
        pass


# ───────────── CLIP DETECTION ─────────────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not isinstance(message.channel, discord.TextChannel):
        return await bot.process_commands(message)

    owner_id = ticket_owner_id(message.channel)
    if owner_id == message.author.id and message.channel.id not in clip_seen:
        if message.attachments or "http" in message.content:
            clip_seen.add(message.channel.id)
            try:
                await message.add_reaction("✅")
            except Exception:
                pass
            staff = message.guild.get_role(STAFF_ROLE_ID)
            await message.channel.send(
                content=staff.mention if staff else None,
                embed=discord.Embed(
                    title="🎥 Clip received",
                    description="Staff can now review this application.",
                    color=COLOR))
    await bot.process_commands(message)


# ───────────── AUTO CLOSE INACTIVE ─────────────
@tasks.loop(minutes=30)
async def auto_close():
    for guild in bot.guilds:
        category = guild.get_channel(CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            continue
        for ch in list(category.text_channels):
            if ticket_owner_id(ch) is None:
                continue
            last = discord.utils.snowflake_time(ch.last_message_id) if ch.last_message_id else ch.created_at
            if discord.utils.utcnow() - last > timedelta(hours=INACTIVE_HOURS):
                try:
                    await close_ticket(ch, f"Inactive for {INACTIVE_HOURS}h")
                except Exception as e:
                    print("auto close error:", e)


@auto_close.before_loop
async def before_auto_close():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
