import discord
from discord.ext import commands
from discord import app_commands
import datetime
import sqlite3 
import json # JSON 처리 임포트

class Bank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.get_db_connection = bot.get_db_connection
        self.get_server_config = bot.get_server_config # 서버 설정 함수 주입

    # --- 메시지 리스너 (모든 메시지 처리의 시작점) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 이 코그에서만 필요한 on_message 로직을 추가.
        # 예를 들어, 은행 관련 키워드를 감지하는 등.
        # 여기서는 특별한 필터링 로직이 없으므로, 모든 메시지를 commands 프레임워크로 전달하기 위해
        # bot.process_commands는 bot.py의 on_message에서 이미 호출되고 있으므로 여기서는 아무것도 안 합니다.
        pass

    # --- 슬래시 커맨드 ---
    @app_commands.command(name="통장개설", description="은행 통장을 개설합니다.")
    @app_commands.guild_only()
    async def open_account_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._open_account(interaction.user, interaction=interaction)

    @app_commands.command(name="잔액", description="현재 잔액을 확인합니다.")
    @app_commands.guild_only()
    async def balance_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._get_balance(interaction.user, interaction=interaction)

    # 내부 함수: 잔액 조회 로직 (슬래시 커맨드와 메시지 기반 명령어 모두에서 사용)
    async def _get_balance(self, user: discord.User, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id

        # 은행 채널 검사
        server_config = self.bot.get_server_config(guild_id)
        bank_channel_id = server_config.get('bank_channel_id')
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if bank_channel_id and str(current_channel_id) != bank_channel_id:
            bank_channel_mention = self.bot.get_channel(int(bank_channel_id)).mention if self.bot.get_channel(int(bank_channel_id)) else "설정된 은행 채널"
            response_msg = f"❌ 은행 명령어는 {bank_channel_mention}에서만 사용할 수 있습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction:
                await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx:
                await ctx.send(response_msg)
            return # 이 경우 메시지 기반 명령어는 여기서 종료 (외부에서 사용될 경우 고려)

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        account = cursor.fetchone()
        conn.close()
        response_msg = f"🏦 {user.display_name}님의 현재 잔액은 **{account['balance']} 원**입니다." # 통화단위 '원'으로 변경
        if interaction:
            await interaction.response.send_message(response_msg, ephemeral=True)
        elif ctx:
            await ctx.send(response_msg)
        return


    @app_commands.command(name="입금", description="자신에게 돈을 입금합니다.")
    @app_commands.describe(금액="입금할 금액")
    @app_commands.guild_only()
    async def deposit_slash(self, interaction: discord.Interaction, 금액: int): # 이름 변경하여 메시지 기반과 구분
        await self._deposit_money(interaction.user, 금액, interaction=interaction)

    @app_commands.command(name="출금", description="자신에게서 돈을 출금합니다.")
    @app_commands.describe(금액="출금할 금액")
    @app_commands.guild_only()
    async def withdraw_slash(self, interaction: discord.Interaction, 금액: int): # 이름 변경하여 메시지 기반과 구분
        await self._withdraw_money(interaction.user, 금액, interaction=interaction)

    @app_commands.command(name="송금", description="다른 유저에게 돈을 송금합니다.")
    @app_commands.describe(수신자="돈을 보낼 유저", 금액="송금할 금액")
    @app_commands.guild_only()
    async def transfer_slash(self, interaction: discord.Interaction, 수신자: discord.Member, 금액: int): # 이름 변경하여 메시지 기반과 구분
        await self._transfer_money(interaction.user, 수신자, 금액, interaction=interaction)

    @app_commands.command(name="대출", description="은행에서 돈을 대출받습니다. (연 이자율은 설정 가능)")
    @app_commands.describe(금액="대출받을 금액")
    @app_commands.guild_only()
    async def loan_slash(self, interaction: discord.Interaction, 금액: int): # 이름 변경하여 메시지 기반과 구분
        await self._take_loan(interaction.user, 금액, interaction=interaction)

    @app_commands.command(name="상환", description="대출금을 상환합니다.")
    @app_commands.describe(금액="상환할 금액")
    @app_commands.guild_only()
    async def repay_loan_slash(self, interaction: discord.Interaction, 금액: int): # 이름 변경하여 메시지 기반과 구분
        await self._repay_loan(interaction.user, 금액, interaction=interaction)

    @app_commands.command(name="거래내역", description="모든 은행 거래 내역을 조회합니다.")
    @app_commands.guild_only()
    async def transaction_history_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._transaction_history(interaction.user, interaction=interaction)

    # --- 메시지 기반 명령어 ---
    @commands.command(name="잔액", help="현재 잔액을 확인합니다. (예: 저스트 잔액)")
    async def msg_balance(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "잔액"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}잔액`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._get_balance(ctx.author, ctx=ctx)

    @commands.command(name="통장", help="통장을 개설합니다. (예: 저스트 통장)")
    async def msg_open_account(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "통장개설"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}통장`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._open_account(ctx.author, ctx=ctx)

    @commands.command(name="입금", help="자신에게 돈을 입금합니다. (예: 저스트 입금 1000)")
    async def msg_deposit(self, ctx: commands.Context, 금액: int):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "입금"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}입금`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._deposit_money(ctx.author, 금액, ctx=ctx)

    @commands.command(name="출금", help="자신에게서 돈을 출금합니다. (예: 저스트 출금 500)")
    async def msg_withdraw(self, ctx: commands.Context, 금액: int):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "출금"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}출금`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._withdraw_money(ctx.author, 금액, ctx=ctx)

    @commands.command(name="송금", help="다른 유저에게 돈을 송금합니다. (예: 저스트 송금 @유저 100)")
    async def msg_transfer(self, ctx: commands.Context, 수신자: discord.Member, 금액: int):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "송금"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}송금`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._transfer_money(ctx.author, 수신자, 금액, ctx=ctx)

    @commands.command(name="대출", help="은행에서 돈을 대출받습니다. (예: 저스트 대출 100000)")
    async def msg_loan(self, ctx: commands.Context, 금액: int):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "대출"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}대출`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._take_loan(ctx.author, 금액, ctx=ctx)

    @commands.command(name="상환", help="대출금을 상환합니다. (예: 저스트 상환 5000)")
    async def msg_repay_loan(self, ctx: commands.Context, 금액: int):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "상환"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}상환`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._repay_loan(ctx.author, 금액, ctx=ctx)

    @commands.command(name="거래내역", help="모든 은행 거래 내역을 조회합니다. (예: 저스트 거래내역)")
    async def msg_transaction_history(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "거래내역"): await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}거래내역`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._transaction_history(ctx.author, ctx=ctx)


    # --- 내부 함수 (슬래시 및 메시지 기반 명령어에서 공통 사용) ---
    async def _check_bank_channel(self, guild_id: int, current_channel_id: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """은행 명령어가 은행 채널에서 사용되었는지 확인합니다."""
        server_config = self.bot.get_server_config(guild_id)
        bank_channel_id = server_config.get('bank_channel_id')

        if bank_channel_id and str(current_channel_id) != bank_channel_id:
            bank_channel_mention = self.bot.get_channel(int(bank_channel_id)).mention if self.bot.get_channel(int(bank_channel_id)) else "설정된 은행 채널"
            response_msg = f"❌ 은행 명령어는 {bank_channel_mention}에서만 사용할 수 있습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return False
        return True

    async def _open_account(self, user: discord.User, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            conn.close()
            response_msg = "❌ 이미 통장이 개설되어 있습니다!"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        username = user.display_name
        cursor.execute("INSERT INTO bank_accounts (user_id, username, balance) VALUES (?, ?, ?)", (user_id, username, 0))
        conn.commit()
        conn.close()

        response_msg = "✅ 통장이 성공적으로 개설되었습니다! 이제 은행 기능을 이용할 수 있습니다."
        if interaction: await interaction.followup.send(response_msg, ephemeral=True)
        elif ctx: await ctx.send(response_msg)

    async def _deposit_money(self, user: discord.User, 금액: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        if 금액 <= 0:
            response_msg = "❌ 0원 이하의 금액은 입금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        username = user.display_name
        cursor.execute("INSERT INTO bank_accounts (user_id, username, balance) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (user_id, username, 금액, 금액))
        conn.commit()

        cursor.execute("""
            INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, 'deposit', 금액, datetime.datetime.now(datetime.UTC).isoformat(), f"{금액} 원 입금"))
        conn.commit()

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        account = cursor.fetchone()
        conn.close()
        response_msg = f"💰 {금액} 원이 입금되었습니다. 현재 잔액: **{account['balance']} 원**"
        if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
        elif ctx: await ctx.send(response_msg)

    async def _withdraw_money(self, user: discord.User, 금액: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        if 금액 <= 0:
            response_msg = "❌ 0원 이하의 금액은 출금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        account = cursor.fetchone()
        current_balance = account["balance"] if account else 0

        if current_balance < 금액:
            conn.close()
            response_msg = "💸 잔액이 부족합니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("UPDATE bank_accounts SET balance = balance - ? WHERE user_id = ?", (금액, user_id))
        conn.commit()

        cursor.execute("""
            INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, user.display_name, 'withdrawal', 금액, datetime.datetime.now(datetime.UTC).isoformat(), f"{금액} 원 출금"))
        conn.commit()

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        account = cursor.fetchone()
        conn.close()
        response_msg = f"💸 {금액} 원이 출금되었습니다. 현재 잔액: **{account['balance']} 원**"
        if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
        elif ctx: await ctx.send(response_msg)

    async def _transfer_money(self, sender: discord.User, receiver: discord.Member, 금액: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        if 금액 <= 0:
            response_msg = "❌ 0원 이하의 금액은 송금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return
        if receiver.bot:
            response_msg = "❌ 봇에게는 송금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return
        if receiver.id == sender.id:
            response_msg = "❌ 자기 자신에게는 송금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        sender_id = str(sender.id)
        receiver_id = str(receiver.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (sender_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (sender_id,))
        sender_account = cursor.fetchone()
        sender_balance = sender_account["balance"] if sender_account else 0

        if sender_balance < 금액:
            conn.close()
            response_msg = "💸 잔액이 부족해서 송금할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        try:
            # 송신자 잔액 감소
            cursor.execute("UPDATE bank_accounts SET balance = balance - ? WHERE user_id = ?", (금액, sender_id))
            # 수신자 잔액 증가 (없으면 새로 생성)
            cursor.execute("INSERT INTO bank_accounts (user_id, username, balance) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (receiver_id, receiver.display_name, 금액, 금액))
            conn.commit()

            # 거래 내역 기록 (송신자)
            cursor.execute("""
                INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, related_user_id, related_username, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sender_id, sender.display_name, 'transfer_out', 금액, datetime.datetime.now(datetime.UTC).isoformat(), receiver_id, receiver.display_name, f"{receiver.display_name}님에게 {금액} 원 송금"))
            conn.commit()
            # 거래 내역 기록 (수신자)
            cursor.execute("""
                INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, related_user_id, related_username, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (receiver_id, receiver.display_name, 'transfer_in', 금액, datetime.datetime.now(datetime.UTC).isoformat(), sender_id, sender.display_name, f"{sender.display_name}님으로부터 {금액} 원 입금"))
            conn.commit()

        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"송금 처리 중 오류 발생: {e}")
            response_msg = f"❌ 송금 처리 중 오류가 발생했습니다. 관리자에게 문의하세요: {e}"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return
        finally:
            conn.close()

        conn = self.get_db_connection() # 다시 연결해서 최신 잔액 조회
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (sender_id,))
        updated_sender_account = cursor.fetchone()
        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (receiver_id,))
        updated_receiver_account = cursor.fetchone()
        conn.close()

        response_msg = (
            f"✅ {receiver.display_name}님에게 **{금액} 원**을 송금했습니다. "
            f"내 잔액: **{updated_sender_account['balance']} 원**"
        )
        if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
        elif ctx: await ctx.send(response_msg)

        try:
            await receiver.send(f"💰 {sender.display_name}님으로부터 **{금액} 원**을 송금받았습니다. 현재 잔액: **{updated_receiver_account['balance']} 원**")
        except discord.Forbidden:
            print(f"수신자 {receiver.display_name}에게 DM을 보낼 수 없습니다.")

    async def _take_loan(self, user: discord.User, 금액: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        if 금액 <= 0:
            response_msg = "❌ 0원 이하의 금액은 대출받을 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        server_config = self.bot.get_server_config(guild_id)
        if server_config and server_config['bank_loan_enabled'] == 0:
            response_msg = "❌ 이 서버에서 은행 대출 기능이 비활성화되어 있습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            conn.close()
            return

        max_loan_amount = server_config['bank_max_loan_amount'] if server_config and server_config['bank_max_loan_amount'] is not None else 1000000 
        interest_rate = server_config['bank_loan_interest_rate'] if server_config and server_config['bank_loan_interest_rate'] is not None else 0.032

        if 금액 > max_loan_amount:
            response_msg = f"❌ 최대 대출 가능 금액은 **{max_loan_amount} 원**입니다. {금액} 원은 대출받을 수 없습니다." # 통화단위 변경
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            conn.close()
            return

        cursor.execute("SELECT id FROM loans WHERE user_id = ? AND status = 'active'", (user_id,))
        if cursor.fetchone():
            conn.close()
            response_msg = "❌ 이미 활성화된 대출이 있습니다. 기존 대출을 상환해주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        total_repay_amount = int(금액 * (1 + interest_rate)) # 이자 포함 상환 금액 (단순화: 1년 기준)

        try:
            # 1. 은행 계좌에 대출 금액 추가
            cursor.execute("UPDATE bank_accounts SET balance = balance + ? WHERE user_id = ?", (금액, user_id))

            # 2. 대출 정보 기록
            loan_doc = {
                "user_id": user_id,
                "username": user.display_name,
                "loan_amount": 금액,
                "interest_rate": interest_rate,
                "total_repay_amount": total_repay_amount,
                "paid_amount": 0,
                "status": "active",
                "loan_date": datetime.datetime.now(datetime.UTC).isoformat(), 
                "due_date": (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)).isoformat() # 1년 후 만기 (예시)
            }
            cursor.execute("""
                INSERT INTO loans (user_id, username, loan_amount, interest_rate, total_repay_amount, paid_amount, status, loan_date, due_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (loan_doc["user_id"], loan_doc["username"], loan_doc["loan_amount"], loan_doc["interest_rate"], loan_doc["total_repay_amount"], loan_doc["paid_amount"], loan_doc["status"], loan_doc["loan_date"], loan_doc["due_date"]))
            loan_id = cursor.lastrowid

            # 거래 내역 기록
            cursor.execute("""
                INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, user.display_name, 'loan_taken', 금액, datetime.datetime.now(datetime.UTC).isoformat(), f"대출 {금액} 원 받음 (총 상환 {total_repay_amount} 원)")) # 통화단위 변경
            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"대출 처리 중 오류 발생: {e}")
            response_msg = f"❌ 대출 처리 중 오류가 발생했습니다. 관리자에게 문의하세요: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return
        finally:
            conn.close()

        conn = self.get_db_connection() # 다시 연결해서 최신 잔액 조회
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        account = cursor.fetchone()
        current_balance_after_loan = account["balance"] if account else 0
        conn.close()

        response_msg = (
            f"✅ {금액} 원이 대출되었습니다! 이자({interest_rate * 100:.1f}%) 포함 총 상환 금액: **{total_repay_amount} 원**.\n" # 통화단위 변경
            f"현재 잔액: **{current_balance_after_loan} 원**" # 통화단위 변경
        )
        if interaction: await interaction.followup.send(response_msg, ephemeral=True)
        elif ctx: await ctx.send(response_msg)

    async def _repay_loan(self, user: discord.User, 금액: int, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        if 금액 <= 0:
            response_msg = "❌ 0원 이하의 금액은 상환할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("SELECT * FROM loans WHERE user_id = ? AND status = 'active'", (user_id,))
        active_loan = cursor.fetchone()

        if not active_loan:
            conn.close()
            response_msg = "❌ 현재 활성화된 대출이 없습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
        bank_account = cursor.fetchone()
        current_balance = bank_account["balance"] if bank_account else 0

        if current_balance < 금액:
            conn.close()
            response_msg = f"💸 잔액이 부족하여 상환할 수 없습니다! 현재 잔액: **{current_balance} 원**" # 통화단위 변경
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        remaining_repay = active_loan["total_repay_amount"] - active_loan["paid_amount"]

        if 금액 > remaining_repay:
            response_msg = f"❌ 상환할 금액이 남은 상환 금액({remaining_repay} 원)보다 많습니다. 정확한 금액을 입력해주세요." # 통화단위 변경
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            conn.close()
            return

        try:
            # 1. 은행 계좌에서 상환 금액 차감
            cursor.execute("UPDATE bank_accounts SET balance = balance - ? WHERE user_id = ?", (금액, user_id))

            # 2. 대출 정보 업데이트
            new_paid_amount = active_loan["paid_amount"] + 금액
            new_status = "active"
            if new_paid_amount >= active_loan["total_repay_amount"]:
                new_status = "paid"

            cursor.execute("""
                UPDATE loans SET paid_amount = ?, status = ?
                WHERE id = ?
            """, (new_paid_amount, new_status, active_loan["id"]))

            # 3. 상환 내역 기록
            cursor.execute("""
                INSERT INTO loan_payments (loan_id, user_id, payment_amount, payment_date)
                VALUES (?, ?, ?, ?)
            """, (active_loan["id"], user_id, 금액, datetime.datetime.now(datetime.UTC).isoformat())) 
            # 거래 내역 기록
            cursor.execute("""
                INSERT INTO bank_transactions (user_id, username, type, amount, timestamp, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, user.display_name, 'loan_repaid', 금액, datetime.datetime.now(datetime.UTC).isoformat(), f"대출 {금액} 원 상환")) # 통화단위 변경
            conn.commit()

        except Exception as e:
            conn.rollback()
            print(f"상환 처리 중 오류 발생: {e}")
            response_msg = f"❌ 상환 처리 중 오류가 발생했습니다. 관리자에게 문의하세요: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return
        finally:
            conn.close()

        status_message = ""
        if new_status == "paid":
            status_message = "✅ 대출금을 전액 상환했습니다! 감사합니다."
        else:
            status_message = f"✅ {금액} 원 상환 완료! 남은 상환 금액: **{remaining_repay - 금액} 원**" # 통화단위 변경

        if interaction: await interaction.followup.send(status_message, ephemeral=True)
        elif ctx: await ctx.send(status_message)

    async def _transaction_history(self, user: discord.User, interaction: discord.Interaction = None, ctx: commands.Context = None):
        guild_id = interaction.guild_id if interaction else ctx.guild.id
        current_channel_id = interaction.channel_id if interaction else ctx.channel.id

        if not await self._check_bank_channel(guild_id, current_channel_id, interaction=interaction, ctx=ctx): return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id = str(user.id)

        cursor.execute("SELECT user_id FROM bank_accounts WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            conn.close()
            response_msg = "❌ 통장이 개설되어 있지 않습니다. `/통장개설`을 먼저 이용해주세요."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        cursor.execute("""
            SELECT type, amount, timestamp, related_username, description FROM bank_transactions 
            WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10
        """, (user_id,))
        transactions = cursor.fetchall()
        conn.close()

        if not transactions:
            response_msg = "❌ 최근 거래 내역이 없습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        embed = discord.Embed(
            title=f"💰 {user.display_name}님의 최근 거래 내역",
            color=discord.Color.gold()
        )

        # 거래 내역을 문자열로 만들어 임베드 필드에 추가
        history_text = ""
        for i, tx in enumerate(transactions):
            tx_type = ""
            amount_str = f"{tx['amount']:,} 원" # 통화단위 변경

            if tx['type'] == 'deposit':
                tx_type = "📥 입금"
                amount_str = f"+{amount_str}"
            elif tx['type'] == 'withdrawal':
                tx_type = "📤 출금"
                amount_str = f"-{amount_str}"
            elif tx['type'] == 'transfer_out':
                tx_type = "➡️ 송금"
                amount_str = f"-{amount_str} ➡️ {tx['related_username'] if tx['related_username'] else '알 수 없음'}" # 관련 유저명 없으면 처리
            elif tx['type'] == 'transfer_in':
                tx_type = "⬅️ 입금"
                amount_str = f"+{amount_str} ⬅️ {tx['related_username'] if tx['related_username'] else '알 수 없음'}" # 관련 유저명 없으면 처리
            elif tx['type'] == 'loan_taken':
                tx_type = "🏦 대출"
                amount_str = f"+{amount_str}"
            elif tx['type'] == 'loan_repaid':
                tx_type = "💳 상환"
                amount_str = f"-{amount_str}"

            # 날짜 형식 조정
            tx_time = datetime.datetime.fromisoformat(tx['timestamp']).strftime('%Y-%m-%d %H:%M')

            history_text += f"**{tx_type}**: {amount_str}\n"
            if tx['description']:
                history_text += f"  > {tx['description']}\n"
            history_text += f"  _{tx_time}_\n\n" # 날짜를 더 작게 표시

        if history_text:
            embed.description = history_text[:2048] # 임베드 설명 최대 길이
            if len(history_text) > 2048:
                embed.set_footer(text="...더 많은 거래 내역은 표시할수 없습니다.")

        if interaction: await interaction.followup.send(embed=embed)
        elif ctx: await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Bank(bot))
    # 각 명령어는 bot.add_cog() 호출 시 @app_commands.command 데코레이터에 의해 자동으로 등록됩니다.
    # 따라서 여기에 개별 슬래시 명령어(Bank.open_account_slash 등)를 bot.tree.add_command 할 필요 없습니다.
    # 메시지 기반 명령어는 commands.Bot(command_prefix) 설정에 의해 자동으로 로드됩니다.