from pyrogram import filters

from BAD import app


@app.on_message(filters.command(["start", "help"]))
async def start(client, message):
    await message.reply_text(
        "Hello there! I am heroku control bot\n\nCheck hosted apps: /myhost, /heroku."
    )
