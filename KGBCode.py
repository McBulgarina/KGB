#!/usr/bin/env python3
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import os
import json
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = ZoneInfo("Europe/Sofia")

GUILD_ID = 1472693125133897818
GUILD = discord.Object(id=GUILD_ID)

ADMIN_IDS = {816204223775113236}

intents = discord.Intents.default()
intents.members = True
intents.guilds = True


class HomeworkBot(commands.Bot):
    async def setup_hook(self):
        self.tree.copy_global_to(guild=GUILD)
        try:
            synced = await self.tree.sync(guild=GUILD)
            print(f"Synced {len(synced)} slash command(s) to the server")
        except Exception as e:
            print(f"Error syncing commands: {e}")


bot = HomeworkBot(command_prefix="!", intents=intents)

Comradesfile_path = "Comrades.json"


def load_comrades():
    if not os.path.exists(Comradesfile_path):
        return []
    try:
        with open(Comradesfile_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def save_comrades():
    with open(Comradesfile_path, "w", encoding="utf-8") as file:
        json.dump(comrades_list, file, indent=4, ensure_ascii=False)


comrades_list = load_comrades()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online)
    print(f"Logged in as {bot.user}")
    if not reminder_checker.is_running():
        reminder_checker.start()


@bot.tree.command(name="add_person", description="Add a person")
@app_commands.describe(
    name="The name of the person",
    age="The age of the person",
    information="Additional information about the person",
    sex="Sex: Male/Female or anything else",
    birthday="Birthday: DD-MM-YYYY",
)
async def add_person(
    interaction: discord.Interaction,
    name: str,
    age: int,
    information: str,
    sex: str,
    birthday: str,
):
    try:
        Birth = datetime.strptime(birthday, "%d-%m-%Y").replace(tzinfo=TIMEZONE)
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid date format.\n\nUse:\n`DD-MM-YYYY`\n\nExample:\n`01-02-2026`",
            ephemeral=True,
        )
        return

    now = datetime.now(TIMEZONE)
    if Birth >= now:
        await interaction.response.send_message(
            "❌ The birthday must be in the past.", ephemeral=True
        )
        return

    existing_ids = {comrade["id"] for comrade in comrades_list}
    while True:
        random_id = random.randint(1000000, 10000000)
        if random_id not in existing_ids:
            break

    comrades = {
        "id": random_id,
        "name": name,
        "age": age,
        "information": information,
        "sex": sex,
        "birthday": Birth.isoformat(),
        "ip": None,
        "reminded_1w": False,
        "reminded_1d": False,
    }

    comrades_list.append(comrades)
    save_comrades()

    await interaction.response.send_message(
        f"**Person added!**\n\n"
        f"**ID:** {random_id}\n"
        f"**Name:** {name}\n"
        f"**Age:** {age}\n"
        f"**Information:** {information}\n"
        f"**Sex:** {sex}\n"
        f"**Birthday:** {Birth.strftime('%d/%m/%Y')}",
        allowed_mentions=discord.AllowedMentions.none(),
    )


@bot.tree.command(name="set_ip", description="Set the IP address of a comrade (admin only)")
@app_commands.describe(
    comrade_id="The ID of the comrade (shown when added or in list)",
    ip="The IP address to assign",
)
async def set_ip(interaction: discord.Interaction, comrade_id: int, ip: str):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Only admins can set IP addresses.", ephemeral=True
        )
        return

    for comrade in comrades_list:
        if comrade["id"] == comrade_id:
            comrade["ip"] = ip
            save_comrades()
            await interaction.response.send_message(
                f"✅ IP for **{comrade['name']}** set to `{ip}`.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

    await interaction.response.send_message(
        f"❌ No comrade found with ID `{comrade_id}`.", ephemeral=True
    )


@bot.tree.command(name="list_comrades", description="Show all comrades")
async def list_comrades(interaction: discord.Interaction):
    if not comrades_list:
        await interaction.response.send_message("No comrades yet.", ephemeral=True)
        return

    show_ip = is_admin(interaction.user.id)
    lines = []
    for comrade in comrades_list:
        line = (
            f"**ID:** {comrade['id']}\n"
            f"**Name:** {comrade['name']}\n"
            f"**Age:** {comrade['age']}\n"
            f"**Information:** {comrade['information']}\n"
            f"**Sex:** {comrade['sex']}\n"
            f"**Birthday:** {datetime.fromisoformat(comrade['birthday']).strftime('%d/%m/%Y')}"
        )
        if show_ip:
            line += f"\n**IP:** {comrade.get('ip') or '—'}"
        lines.append(line)

    await interaction.response.send_message(
        "\n\n".join(lines),
        ephemeral=not show_ip,
        allowed_mentions=discord.AllowedMentions.none(),
    )


@tasks.loop(minutes=1)
async def reminder_checker():
    now = datetime.now(TIMEZONE)

    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return

    channel = None
    for text_channel in guild.text_channels:
        permissions = text_channel.permissions_for(guild.me)
        if permissions.send_messages:
            channel = text_channel
            break

    if channel is None:
        return

    changed = False

    for comrade in comrades_list:
        due = datetime.fromisoformat(comrade["birthday"]).replace(
            year=now.year, tzinfo=TIMEZONE
        )
        if due < now:
            due = due.replace(year=now.year + 1)

        reminder_1d = due - timedelta(days=1)
        if not comrade.get("reminded_1d", False) and now >= reminder_1d:
            await send_reminder(channel, comrade, due, "1 day")
            comrade["reminded_1d"] = True
            comrade["reminded_1w"] = True
            changed = True
            continue

        reminder_1w = due - timedelta(days=7)
        if not comrade.get("reminded_1w", False) and now >= reminder_1w:
            await send_reminder(channel, comrade, due, "1 week")
            comrade["reminded_1w"] = True
            changed = True

    if changed:
        save_comrades()


@reminder_checker.before_loop
async def before_reminder_checker():
    await bot.wait_until_ready()


async def send_reminder(channel, comrade, due, time_remaining):
    message = (
        f"**Comrade Birthday Reminder**\n\n"
        f"@everyone\n\n"
        f"**Name:** {comrade['name']}\n"
        f"**Birthday:** {due.strftime('%d/%m/%Y')}\n"
        f"**Birthday in {time_remaining}.**"
    )

    await channel.send(
        message,
        allowed_mentions=discord.AllowedMentions(roles=True, everyone=True),
    )


if __name__ == "__main__":
    bot.run(TOKEN)
