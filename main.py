import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from typing import Optional
from flask import Flask, render_template_string
import threading
# メモリ上で管理するデータ
config = {
    "allowed_user_ids": []
}

ticket_data = {
    "items": [],
    "open_message": {}
}

allowed_user_ids = config.get("allowed_user_ids", [])
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

def load_data():
    return ticket_data

def save_data(data):
    ticket_data.update(data)

class OpenMessageModal(discord.ui.Modal, title="オープンメッセージを設定"):
    def __init__(self, callback):
        super().__init__()
        self.callback_func = callback
        self.add_item(discord.ui.TextInput(label="タイトル", custom_id="title", required=True))
        self.add_item(discord.ui.TextInput(label="説明", custom_id="description", style=discord.TextStyle.paragraph, required=True))

    async def on_submit(self, interaction: discord.Interaction):
        title = self.children[0].value
        description = self.children[1].value
        await self.callback_func(interaction, title, description)

class TicketSelect(discord.ui.Select):
    def __init__(self, options, items, staff_role):
        self.items = items
        self.staff_role = staff_role
        super().__init__(placeholder="ご要件を選択してください", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        item = next((i for i in self.items if i["value"] == selected_value), None)
        if not item:
            await interaction.response.send_message("エラー：項目が見つかりませんでした。", ephemeral=True)
            return

        category = interaction.guild.get_channel(item["category"])
        if not category or not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("カテゴリが存在しないか無効です。", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }

        channel_name = f"🎫｜{interaction.user.name}"
        ticket_channel = await interaction.guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)

        data = load_data()
        open_msg = data.get("open_message", {})

        # メンション
        await ticket_channel.send(f"{interaction.user.mention} {self.staff_role.mention}")

        # 埋め込みメッセージ
        embed = discord.Embed(
            title="内容: " + item["label"],
            description=open_msg.get("description", "オープンメッセージが設定されていません。"),
            color=discord.Color.green()
        )
        await ticket_channel.send(embed=embed)

        # 削除ボタン
        await ticket_channel.send(view=DeleteTicketButton())

        # セレクトメニューをリセット
        new_view = TicketView(self.items, self.staff_role)
        await interaction.message.edit(view=new_view)

        await interaction.response.send_message(f"{ticket_channel.mention} チャンネルを作成しました。", ephemeral=True)

class DeleteTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="チケットを削除", style=discord.ButtonStyle.danger, custom_id="delete_ticket_btn")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.delete()

class TicketView(discord.ui.View):
    def __init__(self, items, staff_role: discord.Role):
        super().__init__(timeout=None)
        options = [
            discord.SelectOption(
                label=item["label"],
                value=item["value"],
                emoji=item["emoji"],
                description=item["description"]
            ) for item in items
        ]
        self.add_item(TicketSelect(options, items, staff_role))

class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticket_add", description="チケット項目を追加")
    async def ticket_add(self, interaction: discord.Interaction, label: str, description: str, category: discord.CategoryChannel, emoji: str):
        data = load_data()
        data["items"].append({
            "label": label,
            "value": label,
            "description": description,
            "category": category.id,
            "emoji": emoji
        })
        save_data(data)
        await interaction.response.send_message(f"項目「{label}」を追加しました。", ephemeral=True)

    @app_commands.command(name="ticket_setting", description="チケット設定（削除・オープンメッセージ）")
    async def ticket_setting(self, interaction: discord.Interaction):
        data = load_data()
        if not data["items"]:
            await interaction.response.send_message("項目が登録されていません。", ephemeral=True)
            return

        view = discord.ui.View()

        class DeleteSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=item["label"], value=item["value"]) for item in data["items"]
                ]
                super().__init__(placeholder="削除する項目を選択", options=options, custom_id="delete_ticket")

            async def callback(self, select_interaction: discord.Interaction):
                selected_value = self.values[0]
                data["items"] = [i for i in data["items"] if i["value"] != selected_value]
                save_data(data)
                await select_interaction.response.send_message(f"項目「{selected_value}」を削除しました。", ephemeral=True)

        class OpenMsgButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="オープンメッセージを設定", style=discord.ButtonStyle.primary)

            async def callback(self, button_interaction: discord.Interaction):
                await button_interaction.response.send_modal(OpenMessageModal(callback=self.set_open_message))

            async def set_open_message(self, modal_interaction, title, description):
                data["open_message"] = {"title": title, "description": description}
                save_data(data)
                await modal_interaction.response.send_message("オープンメッセージを保存しました。", ephemeral=True)

        view.add_item(DeleteSelect())
        view.add_item(OpenMsgButton())
        await interaction.response.send_message("設定を選択してください：", view=view, ephemeral=True)

    @app_commands.command(name="ticket_send", description="チケット作成パネルを送信")
    async def ticket_send(self, interaction: discord.Interaction, title: str, description: str, staff_role: discord.Role, image: Optional[discord.Attachment] = None):
        data = load_data()
        items = data.get("items", [])
        if not items:
            await interaction.response.send_message("先に `/ticket_add` で項目を追加してください。", ephemeral=True)
            return

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        if image:
            embed.set_image(url=image.url)

        view = TicketView(items, staff_role)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("チケットパネルを送信しました。", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Ticket(bot))

# Bot initialization
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

# Flask web server
app = Flask(__name__)

@app.route('/')
def home():
    bot_status = "Online" if bot.is_ready() else "Offline"
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Discord Bot Status</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
            .status { font-size: 24px; margin: 20px; }
            .online { color: green; }
            .offline { color: red; }
        </style>
    </head>
    <body>
        <h1>Discord Bot Status</h1>
        <div class="status {{ 'online' if status == 'Online' else 'offline' }}">
            Status: {{ status }}
        </div>
        <p>Bot Name: {{ bot_name }}</p>
    </body>
    </html>
    ''', status=bot_status, bot_name=bot.user.name if bot.user else "Unknown")

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    if not BOT_TOKEN:
        print("エラー: BOT_TOKENが設定されていません。config.jsonにbot_tokenを追加してください。")
        return
    
    # Flask サーバーを別スレッドで起動
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    await setup(bot)
    try:
        await bot.start(BOT_TOKEN)
    except KeyboardInterrupt:
        print("Bot is shutting down...")
    finally:
        await bot.close()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Process interrupted")
