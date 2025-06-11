
import discord
from discord.ext import commands
import asyncio
import os
from threading import Thread
from flask import Flask

# Botのintents設定
intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# チケットカテゴリとロールの設定
TICKET_CATEGORY_NAME = "チケット"
SUPPORT_ROLE_NAME = "サポート"

@bot.event
async def on_ready():
    print(f'{bot.user} がログインしました！')
    try:
        synced = await bot.tree.sync()
        print(f'{len(synced)} 個のスラッシュコマンドを同期しました')
    except Exception as e:
        print(f'コマンドの同期に失敗しました: {e}')

# チケット作成ボタンのView
class TicketCreateView(discord.ui.View):
    def __init__(self, category_name=None):
        super().__init__(timeout=None)
        self.category_name = category_name or TICKET_CATEGORY_NAME

    @discord.ui.button(label='🎫 チケットを作成', style=discord.ButtonStyle.primary, custom_id='create_ticket')
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        
        # チケットカテゴリを取得または作成
        category = discord.utils.get(guild.categories, name=self.category_name)
        if not category:
            category = await guild.create_category(self.category_name)
        
        # サポートロールを取得
        support_role = discord.utils.get(guild.roles, name=SUPPORT_ROLE_NAME)
        
        # 既存のチケットをチェック
        existing_channel = discord.utils.get(category.channels, name=f'ticket-{user.display_name}')
        if existing_channel:
            await interaction.response.send_message(
                f'既にチケット {existing_channel.mention} が作成されています。',
                ephemeral=True
            )
            return
        
        # チケットチャンネルの権限設定
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
        
        # チケットチャンネルを作成
        channel = await category.create_text_channel(
            name=f'ticket-{user.display_name}',
            overwrites=overwrites
        )
        
        # チケット管理ボタンを追加
        ticket_view = TicketManageView()
        
        embed = discord.Embed(
            title="🎫 新しいチケット",
            description=f"{user.mention} さんのチケットが作成されました。\n\nお困りのことをこちらに記載してください。",
            color=0x00ff00
        )
        embed.add_field(name="作成者", value=user.mention, inline=True)
        embed.add_field(name="作成日時", value=discord.utils.format_dt(discord.utils.utcnow()), inline=True)
        
        await channel.send(embed=embed, view=ticket_view)
        
        await interaction.response.send_message(
            f'チケット {channel.mention} が作成されました！',
            ephemeral=True
        )

# チケット管理ボタンのView
class TicketManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='🔒 チケットを閉じる', style=discord.ButtonStyle.danger, custom_id='close_ticket')
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        
        # チケットチャンネルかどうかを確認
        if not channel.name.startswith('ticket-'):
            await interaction.response.send_message('このコマンドはチケットチャンネルでのみ使用できます。', ephemeral=True)
            return
        
        embed = discord.Embed(
            title="⚠️ チケットを閉じる確認",
            description="本当にこのチケットを閉じますか？\n10秒後に自動的にキャンセルされます。",
            color=0xff0000
        )
        
        confirm_view = TicketCloseConfirmView()
        await interaction.response.send_message(embed=embed, view=confirm_view)

# チケット閉じる確認のView
class TicketCloseConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=10)

    @discord.ui.button(label='✅ 確認', style=discord.ButtonStyle.success, custom_id='confirm_close')
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        
        embed = discord.Embed(
            title="🔒 チケットが閉じられました",
            description="5秒後にチャンネルが削除されます。",
            color=0xff0000
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        await asyncio.sleep(5)
        await channel.delete()

    @discord.ui.button(label='❌ キャンセル', style=discord.ButtonStyle.secondary, custom_id='cancel_close')
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="キャンセルされました",
            description="チケットは開いたままです。",
            color=0x808080
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        embed = discord.Embed(
            title="タイムアウト",
            description="操作がキャンセルされました。",
            color=0x808080
        )
        # メッセージが存在する場合のみ編集
        try:
            await self.message.edit(embed=embed, view=None)
        except:
            pass

# チケットパネルを作成するスラッシュコマンド
@bot.tree.command(name='ticket_panel', description='チケット作成パネルを送信します')
async def ticket_panel(interaction: discord.Interaction, category: str = None):
    # 管理者権限をチェック
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('このコマンドを実行する権限がありません。', ephemeral=True)
        return
    
    category_name = category or TICKET_CATEGORY_NAME
    
    embed = discord.Embed(
        title="🎫 チケットシステム",
        description="サポートが必要な場合は、下のボタンをクリックしてチケットを作成してください。\n\n**注意事項:**\n• 1人につき1つのチケットまで作成できます\n• 不要になったチケットは必ず閉じてください",
        color=0x0099ff
    )
    embed.add_field(name="カテゴリ", value=category_name, inline=True)
    embed.set_footer(text="チケットbotへようこそ")
    
    view = TicketCreateView(category_name)
    await interaction.response.send_message(embed=embed, view=view)

# チケット情報を表示するスラッシュコマンド
@bot.tree.command(name='ticket_info', description='現在のチケット情報を表示します')
async def ticket_info(interaction: discord.Interaction, category: str = None):
    guild = interaction.guild
    category_name = category or TICKET_CATEGORY_NAME
    category_obj = discord.utils.get(guild.categories, name=category_name)
    
    if not category_obj:
        await interaction.response.send_message(f'チケットカテゴリ "{category_name}" が見つかりません。', ephemeral=True)
        return
    
    ticket_channels = [ch for ch in category_obj.channels if ch.name.startswith('ticket-')]
    
    embed = discord.Embed(
        title="📊 チケット情報",
        color=0x0099ff
    )
    embed.add_field(name="アクティブなチケット数", value=len(ticket_channels), inline=True)
    embed.add_field(name="カテゴリ", value=category_obj.name, inline=True)
    
    if ticket_channels:
        ticket_list = "\n".join([f"• {ch.mention}" for ch in ticket_channels[:10]])
        if len(ticket_channels) > 10:
            ticket_list += f"\n... および他 {len(ticket_channels) - 10} 個"
        embed.add_field(name="アクティブなチケット", value=ticket_list, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Renderでのヘルスチェック用のWebサーバー
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Discord Bot is running!"

@app.route('/health')
def health():
    return "OK"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

# Botを起動
if __name__ == "__main__":
    # 環境変数からBOTトークンを取得
    token = os.getenv('DISCORD_TOKEN')
    
    if not token:
        print("エラー: BOTトークンが設定されていません。")
        print("環境変数で DISCORD_TOKEN を設定してください。")
    else:
        # FlaskをバックグラウンドでRenderのため起動
        flask_thread = Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Discord botを起動
        bot.run(token)
