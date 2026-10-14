import os
import asyncio
import discord
from discord.ext import commands

TOKEN = os.getenv("TOKEN")
CATEGORY_ID = int(os.getenv("ESPORT_CATEGORY_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
COLOR = 0x9B59FF

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger,
                       emoji="🔒", custom_id="esport_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff = interaction.guild.get_role(STAFF_ROLE_ID)
        is_owner = interaction.channel.topic == f"esport:{interaction.user.id}"
        is_staff = staff in interaction.user.roles if staff else False
        if not (is_owner or is_staff or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("You can't close this ticket.", ephemeral=True)
        await interaction.response.send_message("🔒 Closing this ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()


class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Esport Team", style=discord.ButtonStyle.primary,
                       emoji="🎮", custom_id="esport_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        existing = discord.utils.find(lambda c: c.topic == f"esport:{user.id}", guild.text_channels)
        if existing:
            return await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}", ephemeral=True)

        staff = guild.get_role(STAFF_ROLE_ID)
        category = guild.get_channel(CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                              attach_files=True, embed_links=True,
                                              read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                  manage_channels=True),
        }
        if staff:
            overwrites[staff] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                            attach_files=True, read_message_history=True)

        channel = await guild.create_text_channel(
            name=f"esport-{user.name}",
            category=category,
            topic=f"esport:{user.id}",
            overwrites=overwrites,
        )

        embed = discord.Embed(
            title="🎮 ESPORT TEAM APPLICATION",
            description=(
                f"Welcome {user.mention}!\n\n"
                "Please send the following in this ticket:\n\n"
                "**1️⃣ What do you play?**\n"
                "**2️⃣ Send a clip** of your gameplay 🎥\n\n"
                "Our staff will review your application soon."
            ),
            color=COLOR,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="ELT Esport • Good luck!")

        ping = staff.mention if staff else ""
        await channel.send(content=f"{user.mention} {ping}", embed=embed, view=CloseView())
        await interaction.response.send_message(f"✅ Your ticket is ready: {channel.mention}", ephemeral=True)


@bot.command()
@commands.has_permissions(administrator=True)
async def esportpanel(ctx):
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
    await ctx.send(embed=embed, view=JoinView())
    await ctx.message.delete()


@bot.event
async def on_ready():
    bot.add_view(JoinView())
    bot.add_view(CloseView())
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
