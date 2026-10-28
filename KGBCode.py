
#!/usr/bin/env python3

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import os
import json
import random
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = ZoneInfo("Europe/Sofia")

GUILD_ID = 1472693125133897818
GUILD = discord.Object(id=GUILD_ID)

ADMIN_IDS = {816204223775113236}

DATA_FILE = "Comrades.json"
MESSAGE_LIMIT = 1900

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from your .env file.")


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

def load_comrades():
    if not os.path.exists(DATA_FILE):
        return []

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            print("Warning: Comrades.json must contain a JSON list.")
            return []

        # Migrate old records to the current reminder format.
        for comrade in data:
            comrade.setdefault("reminded_1w_year", None)
            comrade.setdefault("reminded_1d_year", None)

        return data

    except (json.JSONDecodeError, OSError) as e:
        print(f"Error loading {DATA_FILE}: {e}")
        return []


def save_comrades():
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(comrades_list, file, indent=4, ensure_ascii=False)


comrades_list = load_comrades()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def calculate_age(birthday: datetime) -> int:
    """Calculate current age from the birthday."""
    today = datetime.now(TIMEZONE).date()
    birth_date = birthday.date()

    return (
        today.year
        - birth_date.year
        - (
            (today.month, today.day)
            < (birth_date.month, birth_date.day)
        )
    )

def parse_birthday(birthday: str):
    """Parse DD-MM-YYYY and reject today or future dates."""
    try:
        birth = datetime.strptime(
            birthday, "%d-%m-%Y"
        ).replace(tzinfo=TIMEZONE)
    except ValueError:
        return None

    if birth.date() >= datetime.now(TIMEZONE).date():
        return None

    return birth

def birthday_in_year(birthday: datetime, year: int) -> date:
    """
    Return the birthday occurrence in a given year.
    February 29 birthdays are celebrated on February 28
    in non-leap years.
    """
    month = birthday.month
    day = birthday.day

    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        raise

def next_birthday(birthday: datetime, now: datetime) -> datetime:
    """Find the next birthday occurrence in the configured timezone."""
    occurrence = birthday_in_year(birthday, now.year)
    due = datetime(
        occurrence.year,
        occurrence.month,
        occurrence.day,
        tzinfo=TIMEZONE,
    )

    if due <= now:
        occurrence = birthday_in_year(birthday, now.year + 1)
        due = datetime(
            occurrence.year,
            occurrence.month,
            occurrence.day,
            tzinfo=TIMEZONE,
        )

    return due

def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split text into Discord-safe message chunks."""
    chunks = []

    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)

        if split_at <= 0:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    if text:
        chunks.append(text)

    return chunks

@bot.event
async def on_ready():
    await bot.change_presence(status=discord.Status.online)
    print(f"Logged in as {bot.user}")

    if not reminder_checker.is_running():
        reminder_checker.start()

@bot.tree.command(
    name="add_comrade",
    description="Add a person",
)
@app_commands.describe(
    name="The name of the person",
    information="Additional information about the person",
    sex="Sex: Male/Female or anything else",
    birthday="Birthday: DD-MM-YYYY",
)
async def add_person(
    interaction: discord.Interaction,
    name: str,
    information: str,
    sex: str,
    birthday: str,
):
    birth = parse_birthday(birthday)

    if birth is None:
        await interaction.response.send_message(
            "❌ Invalid birthday or date is not in the past.\n"
            "Use DD-MM-YYYY, for example `01-02-2000`.",
            ephemeral=True,
        )
        return

    existing_ids = {
        comrade["id"]
        for comrade in comrades_list
        if "id" in comrade
    }

    while True:
        random_id = random.randint(1_000_000, 9_999_999)
        if random_id not in existing_ids:
            break

    age = calculate_age(birth)

    comrade = {
        "id": random_id,
        "name": name,
        "age": age,
        "information": information,
        "sex": sex,
        "birthday": birth.isoformat(),
        "ip": None,
        "reminded_1w_year": None,
        "reminded_1d_year": None,
    }

    comrades_list.append(comrade)
    save_comrades()

    await interaction.response.send_message(
        f"✅ **Person added!**\n\n"
        f"**ID:** {random_id}\n"
        f"**Name:** {name}\n"
        f"**Age:** {age}\n"
        f"**Information:** {information}\n"
        f"**Sex:** {sex}\n"
        f"**Birthday:** {birth.strftime('%d/%m/%Y')}",
        allowed_mentions=discord.AllowedMentions.none(),
    )

@bot.tree.command(
    name="set_ip",
    description="Set the IP address of a comrade (admin only)",
)
@app_commands.describe(
    comrade_id="The ID of the comrade",
    ip="The IP address to assign",
)
async def set_ip(
    interaction: discord.Interaction,
    comrade_id: int,
    ip: str,
):
    if not is_admin(interaction.user.id):
        await interaction.response.send_message(
            "❌ Only admins can set IP addresses.",
            ephemeral=True,
        )
        return

    for comrade in comrades_list:
        if comrade.get("id") == comrade_id:
            comrade["ip"] = ip
            save_comrades()

            await interaction.response.send_message(
                f"✅ IP for **{comrade['name']}** set to `{ip}`.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

    await interaction.response.send_message(
        f"❌ No comrade found with ID `{comrade_id}`.",
        ephemeral=True,
    )

@bot.tree.command(
    name="list_comrades",
    description="Show all comrades",
)
async def list_comrades(interaction: discord.Interaction):
    if not comrades_list:
        await interaction.response.send_message(
            "No comrades yet.",
            ephemeral=True,
        )
        return

    show_ip = is_admin(interaction.user.id)
    lines = []

    for comrade in comrades_list:
        birthday = datetime.fromisoformat(comrade["birthday"])
        age = calculate_age(birthday)

        line = (
            f"**ID:** {comrade.get('id', 'Unknown')}\n"
            f"**Name:** {comrade['name']}\n"
            f"**Age:** {age}\n"
            f"**Information:** {comrade['information']}\n"
            f"**Sex:** {comrade['sex']}\n"
            f"**Birthday:** {birthday.strftime('%d/%m/%Y')}"
        )

        if show_ip:
            line += f"\n**IP:** {comrade.get('ip') or '—'}"

        lines.append(line)

    full_text = "\n\n".join(lines)
    chunks = split_message(full_text)

    await interaction.response.send_message(
        chunks[0],
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    for chunk in chunks[1:]:
        await interaction.followup.send(
            chunk,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

@bot.tree.command(
    name="edit_comrade",
    description="Edit an existing comrade",
)
@app_commands.describe(
    comrade_id="The ID of the comrade to edit",
    name="The new name",
    information="Additional information",
    sex="Sex",
    birthday="Birthday: DD-MM-YYYY",
)
async def edit_comrade(
    interaction: discord.Interaction,
    comrade_id: int,
    name: str,
    information: str,
    sex: str,
    birthday: str,
):
    comrade = next(
        (
            c for c in comrades_list
            if c.get("id") == comrade_id
        ),
        None,
    )

    if comrade is None:
        await interaction.response.send_message(
            f"❌ No comrade found with ID `{comrade_id}`.",
            ephemeral=True,
        )
        return

    birth = parse_birthday(birthday)

    if birth is None:
        await interaction.response.send_message(
            "❌ Invalid birthday or date is not in the past.\n"
            "Use DD-MM-YYYY, for example `01-02-2000`.",
            ephemeral=True,
        )
        return

    old_birthday = datetime.fromisoformat(comrade["birthday"])

    birthday_changed = (
        old_birthday.date() != birth.date()
    )

    comrade.update({
        "name": name,
        "age": calculate_age(birth),
        "information": information,
        "sex": sex,
        "birthday": birth.isoformat(),
    })

    if birthday_changed:
        comrade["reminded_1w_year"] = None
        comrade["reminded_1d_year"] = None

    comrade.setdefault("reminded_1w_year", None)
    comrade.setdefault("reminded_1d_year", None)

    save_comrades()

    await interaction.response.send_message(
        f"✅ **Comrade edited!**\n\n"
        f"**ID:** {comrade_id}\n"
        f"**Name:** {name}\n"
        f"**Age:** {calculate_age(birth)}\n"
        f"**Information:** {information}\n"
        f"**Sex:** {sex}\n"
        f"**Birthday:** {birth.strftime('%d/%m/%Y')}",
        ephemeral=True,
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
        try:
            birthday = datetime.fromisoformat(
                comrade["birthday"]
            )

            comrade.setdefault("reminded_1w_year", None)
            comrade.setdefault("reminded_1d_year", None)

            due = next_birthday(birthday, now)
            due_year = due.year

            reminder_1d = due - timedelta(days=1)
            reminder_1w = due - timedelta(days=7)

            if (
                now >= reminder_1d
                and comrade["reminded_1d_year"] != due_year
            ):
                try:
                    await send_reminder(
                        channel, comrade, due, "1 day"
                    )
                except discord.HTTPException as e:
                    print(
                        f"Failed to send one-day reminder for "
                        f"{comrade.get('name', 'Unknown')}: {e}"
                    )
                    continue

                comrade["reminded_1d_year"] = due_year

                comrade["reminded_1w_year"] = due_year
                changed = True
                continue

            if (
                now >= reminder_1w
                and comrade["reminded_1w_year"] != due_year
            ):
                try:
                    await send_reminder(
                        channel, comrade, due, "1 week"
                    )
                except discord.HTTPException as e:
                    print(
                        f"Failed to send one-week reminder for "
                        f"{comrade.get('name', 'Unknown')}: {e}"
                    )
                    continue

                comrade["reminded_1w_year"] = due_year
                changed = True

        except (KeyError, ValueError, TypeError) as e:
            print(
                f"Skipping invalid comrade record "
                f"{comrade.get('id', 'Unknown')}: {e}"
            )
            continue

    if changed:
        try:
            save_comrades()
        except OSError as e:
            print(f"Failed to save reminder state: {e}")


@reminder_checker.before_loop
async def before_reminder_checker():
    await bot.wait_until_ready()


async def send_reminder(
    channel: discord.TextChannel,
    comrade: dict,
    due: datetime,
    time_remaining: str,
):
    age = calculate_age(
        datetime.fromisoformat(comrade["birthday"])
    )

    birthday_age = age + 1

    message = (
        f"**Comrade Birthday Reminder**\n\n"
        f"@everyone\n\n"
        f"**Name:** {comrade['name']}\n"
        f"**Age turning:** {birthday_age}\n"
        f"**Birthday:** {due.strftime('%d/%m/%Y')}\n"
        f"**Birthday in {time_remaining}.**"
    )

    await channel.send(
        message,
        allowed_mentions=discord.AllowedMentions(
            everyone=True
        ),
    )

if __name__ == "__main__":
    bot.run(TOKEN)
