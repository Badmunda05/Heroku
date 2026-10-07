import asyncio
import importlib
import logging

from pyrogram import idle
from pyrogram.types import BotCommand

from BAD import app
from BAD.plugins import ALL_MODULES
from config import LOGGER_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],  # Output to console
)

logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pymongo").setLevel(logging.ERROR)

log = logging.getLogger("BAD-HEROKU-BOT")

BOT_COMMANDS = [
    BotCommand("start", "✧ sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ ✧"),
    BotCommand("help", "✧ ʜᴇʟᴘ ᴍᴇɴᴜ ✧"),
    BotCommand("host", "✧ ᴅᴇᴘʟᴏʏ ᴀ ɴᴇᴡ ᴀᴘᴘ ᴏɴ ʜᴇʀᴏᴋᴜ ✧"),
    BotCommand("heroku", "✧ ᴍᴀɴᴀɢᴇ ʏᴏᴜʀ ʜᴇʀᴏᴋᴜ ᴀᴘᴘs ✧"),
]

ALIVE_TEXT = "**𝖨 𝖺𝗆 𝖺𝗅𝗂𝗏𝖾 𝖡𝖺𝖻𝗒 𝖸𝗈𝗎𝗋 𝖡𝗈𝗍 𝖲𝗎𝖼𝖼𝖾𝗌𝗌𝖿𝗎𝗅 𝖣𝖾𝗉𝗅𝗈𝗒 \n Mʏ Dᴇᴠᴇʟᴏᴘᴇʀ  [↞꯭̽⎯꯭̽🇨🇦꯭꯭ ⃪ʙ̶꯭ᴀ̶ᴅ̶꯭↠_꯭آآ⎯꯭ ꯭̽🌸](https://t.me/Badmundaxd)**"


async def main():
    log.info("Starting bot...")
    await app.start()
    for all_module in ALL_MODULES:
        importlib.import_module("BAD.plugins" + all_module)

    # Set bot commands (shown in the Telegram "/" menu)
    try:
        await app.set_bot_commands(BOT_COMMANDS)
    except Exception as e:
        log.warning("Could not set bot commands: %s", e)

    # Tell the logger chat that the bot is up
    if LOGGER_ID:
        try:
            await app.send_message(LOGGER_ID, ALIVE_TEXT)
        except Exception as e:
            log.warning(
                "Could not send the start message to LOGGER_ID %s: %s", LOGGER_ID, e
            )

    log.info("Bot Started")
    await idle()
    await app.stop()


if __name__ == "__main__":
    loop = asyncio.get_event_loop_policy().get_event_loop()
    loop.run_until_complete(main())
