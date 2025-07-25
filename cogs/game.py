import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import random

class Game(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.get_db_connection = bot.get_db_connection

    # --- 메시지 리스너 (모든 메시지 처리의 시작점) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        pass # 이 코그에서는 특별히 on_message 필터링이 없으므로 pass

    # --- 슬래시 커맨드 ---
    @app_commands.command(name="주사위", description="주사위를 굴립니다.")
    @app_commands.describe(면="주사위의 면 개수 (기본 6면)")
    @app_commands.guild_only() 
    async def roll_dice_slash(self, interaction: discord.Interaction, 면: int = 6): # 이름 변경하여 메시지 기반과 구분
        await self._roll_dice(interaction.user, 면, interaction=interaction)

    @app_commands.command(name="가위바위보", description="봇과 가위바위보를 합니다.")
    @app_commands.describe(선택="가위, 바위, 보 중 하나를 선택하세요.")
    @app_commands.guild_only()
    async def rps_slash(self, interaction: discord.Interaction, 선택: str): # 이름 변경하여 메시지 기반과 구분
        await self._play_rps(interaction.user, 선택, interaction=interaction)

    # --- 메시지 기반 명령어 ---
    @commands.command(name="주사위", help="주사위를 굴립니다. (예: 저스트 주사위 6)")
    async def msg_roll_dice(self, ctx: commands.Context, 면: int = 6):
        if not ctx.guild:
            await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.")
            return
        # is_command_enabled로 비활성화 여부 확인 (moderation 코그에서 제어)
        if not self.bot.is_command_enabled(ctx.guild.id, "주사위"):
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}주사위`는 현재 이 서버에서 비활성화되어 있습니다.")
             return
        await self._roll_dice(ctx.author, 면, ctx=ctx)

    @commands.command(name="가위바위보", help="봇과 가위바위보를 합니다. (예: 저스트 가위바위보 바위)")
    async def msg_rps(self, ctx: commands.Context, *, 선택: str): # 선택에 공백이 있을 수 있으므로 *args 사용
        if not ctx.guild:
            await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.")
            return
        if not self.bot.is_command_enabled(ctx.guild.id, "가위바위보"):
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}가위바위보`는 현재 이 서버에서 비활성화되어 있습니다.")
             return
        await self._play_rps(ctx.author, 선택, ctx=ctx)

    # 내부 함수: 주사위 굴리기 로직 (슬래시 커맨드와 메시지 기반 명령어 모두에서 사용)
    async def _roll_dice(self, user: discord.User, 면: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        if interaction:
            send_response = interaction.response.send_message
            #followup_send = interaction.followup.send # 이 함수는 여기선 안 쓰지만 예시로 남김
            ephemeral = True # 슬래시 커맨드는 대부분 ephemeral
        elif ctx:
            send_response = ctx.send
            #followup_send = ctx.send
            ephemeral = False # 메시지 기반은 ephemeral 없음
        else: # interaction도 ctx도 없으면
            print("Error: _roll_dice called with insufficient context.")
            return

        if 면 <= 1:
            await send_response("❌ 주사위 면은 2개 이상이어야 합니다!", ephemeral=ephemeral)
            return
        result = random.randint(1, 면)

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO game_stats (game_type, user_id, username, sides, result, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("주사위", str(user.id), user.display_name, 면, str(result),
                datetime.datetime.now(datetime.UTC).isoformat()))
        conn.commit()
        conn.close()

        await send_response(f"🎲 {user.display_name}님이 { 면}면 주사위를 굴려 **{result}**가 나왔습니다!", ephemeral=ephemeral)

    # 내부 함수: 가위바위보 로직 (슬래시 커맨드와 메시지 기반 명령어 모두에서 사용)
    async def _play_rps(self, user: discord.User, 선택: str, interaction: discord.Interaction = None, ctx: commands.Context = None):
        if interaction:
            send_response = interaction.response.send_message
            #followup_send = interaction.followup.send
            ephemeral = True # 슬래시 커맨드는 대부분 ephemeral
        elif ctx:
            send_response = ctx.send
            #followup_send = ctx.send
            ephemeral = False # 메시지 기반은 ephemeral 없음
        else:
            print("Error: _play_rps called with insufficient context.")
            return

        choices = ["가위", "바위", "보"]
        bot_choice = random.choice(choices)

        user_choice_normalized = 선택.strip().lower()

        if user_choice_normalized not in choices:
            await send_response("❌ '가위', '바위', '보' 중에 하나를 선택해주세요!", ephemeral=ephemeral)
            return

        result_message = f"🤔 {user.display_name}님은 **{user_choice_normalized}**, 저는 **{bot_choice}**를 냈습니다!\n"
        game_result = ""

        if user_choice_normalized == bot_choice:
            result_message += "🤝 비겼습니다! 다시 한 번 시도해 보세요!"
            game_result = "무승부"
        elif (user_choice_normalized == "가위" and bot_choice == "보") or \
             (user_choice_normalized == "바위" and bot_choice == "가위") or \
             (user_choice_normalized == "보" and bot_choice == "바위"):
            result_message += "🎉 이겼습니다! 축하합니다!"
            game_result = "승리"
        else:
            result_message += "😭 제가 이겼습니다! 다음엔 꼭 이겨보세요!"
            game_result = "패배"

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO game_stats (game_type, user_id, username, user_choice, bot_choice, result, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("가위바위보", str(user.id), user.display_name, user_choice_normalized, bot_choice, game_result, datetime.datetime.now(datetime.UTC).isoformat()))
        conn.commit()
        conn.close()

        await send_response(result_message, ephemeral=ephemeral)

async def setup(bot):
    await bot.add_cog(Game(bot))
    # 각 명령어는 bot.add_cog() 호출 시 @app_commands.command 데코레이터에 의해 자동으로 등록됩니다.