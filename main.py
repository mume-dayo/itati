import discord
from discord.ext import commands
from discord import app_commands
import os
from typing import Optional
from flask import Flask, render_template_string
import threading
import asyncio
# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ エラー: BOT_TOKENが設定されていません。")
    print("Secretsでkey=BOT_TOKEN, value=あなたのボットトークンを設定してください。")
    exit(1)

print(f"🔑 BOT_TOKEN取得済み: {BOT_TOKEN[:20]}..." if BOT_TOKEN else "❌ BOT_TOKEN未設定")

# In-memory data storage
support_data = {
    "categories": [],
    "welcome_config": {
        "title": "サポートへようこそ",
        "message": "お困りのことがございましたら、お気軽にお声がけください。"
    }
}

class TicketModal(discord.ui.Modal, title="ウェルカムメッセージ設定"):
    """Modal for setting welcome message configuration"""
    
    def __init__(self, save_callback):
        super().__init__()
        self.save_callback = save_callback
    
    title_input = discord.ui.TextInput(
        label="タイトル",
        placeholder="ウェルカムメッセージのタイトルを入力",
        required=True,
        max_length=100
    )
    
    message_input = discord.ui.TextInput(
        label="メッセージ内容",
        placeholder="ウェルカムメッセージの内容を入力",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await self.save_callback(interaction, self.title_input.value, self.message_input.value)

class SupportSelect(discord.ui.Select):
    """Dropdown select for support categories"""
    
    def __init__(self, categories, staff_role):
        self.categories = categories
        self.staff_role = staff_role
        
        options = []
        for category in categories:
            # 絵文字の処理を改善
            emoji = category.get("emoji", "🎫")
            try:
                # カスタム絵文字の場合の処理
                if emoji.startswith("<") and emoji.endswith(">"):
                    emoji = None  # カスタム絵文字はSelectOptionでは使用できない
                
                options.append(discord.SelectOption(
                    label=category["name"],
                    value=category["id"], 
                    description=category["description"][:100],  # 説明文の長さ制限
                    emoji=emoji
                ))
            except Exception as e:
                print(f"絵文字エラー: {e}")
                # 絵文字でエラーが発生した場合はデフォルト絵文字を使用
                options.append(discord.SelectOption(
                    label=category["name"],
                    value=category["id"],
                    description=category["description"][:100],
                    emoji="🎫"
                ))
        
        super().__init__(
            placeholder="サポートの種類を選択してください",
            options=options,
            custom_id="support_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        category_info = next((cat for cat in self.categories if cat["id"] == selected_id), None)
        
        if not category_info:
            await interaction.response.send_message("エラー: カテゴリが見つかりません。", ephemeral=True)
            return
        
        # Get category channel
        category_channel = interaction.guild.get_channel(category_info["channel_id"])
        if not category_channel:
            await interaction.response.send_message("エラー: 指定されたカテゴリチャンネルが見つかりません。", ephemeral=True)
            return
        
        # Create ticket channel
        channel_name = f"ticket-{interaction.user.name}".lower()
        
        # Set permissions
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            self.staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        
        # Create the channel
        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category_channel,
            overwrites=overwrites
        )
        
        # Send welcome message
        embed = discord.Embed(
            title=f"🎫 {category_info['name']}",
            description=support_data["welcome_config"]["message"],
            color=discord.Color.blue()
        )
        embed.add_field(name="ユーザー", value=interaction.user.mention, inline=True)
        embed.add_field(name="スタッフ", value=self.staff_role.mention, inline=True)
        
        # Send messages
        await ticket_channel.send(f"{interaction.user.mention} {self.staff_role.mention}")
        await ticket_channel.send(embed=embed)
        await ticket_channel.send(view=CloseTicketView())
        
        # Reset dropdown
        view = SupportView(self.categories, self.staff_role)
        await interaction.message.edit(view=view)
        
        await interaction.response.send_message(
            f"サポートチケット {ticket_channel.mention} を作成しました。",
            ephemeral=True
        )

class CloseTicketView(discord.ui.View):
    """View with close ticket button"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="🔒 チケットを閉じる", style=discord.ButtonStyle.danger)
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="チケットを閉じますか？",
            description="この操作は取り消せません。",
            color=discord.Color.red()
        )
        
        confirm_view = discord.ui.View()
        
        async def confirm_close(confirm_interaction):
            await ticket_channel.delete()
        
        async def cancel_close(cancel_interaction):
            await cancel_interaction.response.send_message("キャンセルされました。", ephemeral=True)
        
        confirm_button = discord.ui.Button(label="確認", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="キャンセル", style=discord.ButtonStyle.secondary)
        
        confirm_button.callback = confirm_close
        cancel_button.callback = cancel_close
        
        confirm_view.add_item(confirm_button)
        confirm_view.add_item(cancel_button)
        
        ticket_channel = interaction.channel
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)

class SupportView(discord.ui.View):
    """Main support view with dropdown"""
    
    def __init__(self, categories, staff_role):
        super().__init__(timeout=None)
        if categories:
            self.add_item(SupportSelect(categories, staff_role))

class ManageSelect(discord.ui.Select):
    """Select for managing support categories"""
    
    def __init__(self):
        categories = support_data["categories"]
        options = [
            discord.SelectOption(
                label=cat["name"],
                value=cat["id"],
                description="削除する"
            ) for cat in categories
        ]
        
        super().__init__(
            placeholder="削除するカテゴリを選択",
            options=options,
            custom_id="manage_select"
        )
    
    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        support_data["categories"] = [
            cat for cat in support_data["categories"] 
            if cat["id"] != selected_id
        ]
        
        category_name = next((cat["name"] for cat in support_data["categories"] if cat["id"] == selected_id), "不明")
        await interaction.response.send_message(f"カテゴリ「{category_name}」を削除しました。", ephemeral=True)

class SupportBot(commands.Cog):
    """Main bot cog for support functionality"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="ticket_add", description="新しいサポートカテゴリを追加")
    async def add_support_category(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        category: discord.CategoryChannel,
        emoji: str = "🎫"
    ):
        """Add a new support category"""
        category_id = str(len(support_data["categories"]) + 1)
        
        # 絵文字のバリデーション
        if len(emoji) > 2 and not (emoji.startswith("<") and emoji.endswith(">")):
            emoji = "🎫"  # 無効な絵文字の場合はデフォルトに
        
        # 説明文の長さ制限
        if len(description) > 100:
            description = description[:97] + "..."
        
        new_category = {
            "id": category_id,
            "name": name,
            "description": description,
            "channel_id": category.id,
            "emoji": emoji
        }
        
        support_data["categories"].append(new_category)
        
        await interaction.response.send_message(
            f"✅ サポートカテゴリ「{name}」を追加しました。",
            ephemeral=True
        )
    
    @app_commands.command(name="ticket_panel", description="サポートパネルを設置")
    async def create_support_panel(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        staff_role: discord.Role,
        image: Optional[discord.Attachment] = None
    ):
        """Create support panel with dropdown"""
        if not support_data["categories"]:
            await interaction.response.send_message(
                "❌ まずサポートカテゴリを追加してください。",
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
        
        if image:
            embed.set_image(url=image.url)
        
        view = SupportView(support_data["categories"], staff_role)
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ サポートパネルを設置しました。", ephemeral=True)
    
    @app_commands.command(name="ticket_manage", description="サポート設定を管理")
    async def manage_support(self, interaction: discord.Interaction):
        """Manage support settings"""
        if not support_data["categories"]:
            await interaction.response.send_message("❌ 管理するカテゴリがありません。", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="サポート管理",
            description="操作を選択してください",
            color=discord.Color.orange()
        )
        
        view = discord.ui.View()
        
        # Delete category dropdown
        if support_data["categories"]:
            view.add_item(ManageSelect())
        
        # Welcome message button
        welcome_button = discord.ui.Button(label="ウェルカムメッセージ設定", style=discord.ButtonStyle.primary)
        
        async def welcome_callback(button_interaction):
            modal = TicketModal(self.save_welcome_message)
            await button_interaction.response.send_modal(modal)
        
        welcome_button.callback = welcome_callback
        view.add_item(welcome_button)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    
    async def save_welcome_message(self, interaction, title, message):
        """Save welcome message configuration"""
        support_data["welcome_config"]["title"] = title
        support_data["welcome_config"]["message"] = message
        
        await interaction.response.send_message("✅ ウェルカムメッセージを保存しました。", ephemeral=True)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"🤖 {bot.user} がオンラインになりました！")
    try:
        synced = await bot.tree.sync()
        print(f"📝 {len(synced)}個のコマンドを同期しました")
    except Exception as e:
        print(f"❌ コマンド同期エラー: {e}")

# Flask web server
app = Flask(__name__)

@app.route("/")
def home():
    status = "オンライン" if bot.is_ready() else "オフライン"
    bot_name = bot.user.name if bot.user else "Unknown"
    
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
    <title>Discord Support Bot</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            padding: 50px;
            margin: 0;
            min-height: 100vh;
        }
        .container {
            max-width: 500px;
            margin: 0 auto;
            background: rgba(255,255,255,0.1);
            padding: 30px;
            border-radius: 20px;
            backdrop-filter: blur(10px);
        }
        h1 { font-size: 2.5em; margin-bottom: 20px; }
        .status {
            font-size: 1.3em;
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            font-weight: bold;
        }
        .online { background: rgba(40,167,69,0.8); }
        .offline { background: rgba(220,53,69,0.8); }
        .info {
            background: rgba(255,255,255,0.1);
            padding: 20px;
            border-radius: 10px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎫 Discord Support Bot</h1>
        <div class="status {{ 'online' if status == 'オンライン' else 'offline' }}">
            ステータス: {{ status }}
        </div>
        <div class="info">
            <p><strong>Bot名:</strong> {{ bot_name }}</p>
            <p><strong>機能:</strong> サポートチケット管理</p>
        </div>
    </div>
</body>
</html>
    """, status=status, bot_name=bot_name)

def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

async def main():
    # Start web server in background
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Add cog and start bot
    await bot.add_cog(SupportBot(bot))
    
    try:
        await bot.start(BOT_TOKEN)
    except KeyboardInterrupt:
        print("🛑 ボットを停止しています...")
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
