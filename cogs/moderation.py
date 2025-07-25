import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import datetime
import json # JSON 처리 임포트 (show_all_configs에서 사용)
import os # os.getenv 사용을 위해 임포트
import re # 정규표현식 (초대 링크 감지)
import collections # 도배 감지를 위한 deque 사용
import asyncio # 비동기 작업을 위한 asyncio 모듈 임포트

class Moderation(commands.Cog):
    # 도배 감지를 위한 딕셔너리 (메시지 보낸 시간 기록)
    # key: guild_id, value: {user_id: deque(timestamps)}
    message_timestamps = collections.defaultdict(lambda: collections.defaultdict(collections.deque))

    def __init__(self, bot):
        self.bot = bot
        self.get_db_connection = bot.get_db_connection
        self.get_server_config = bot.get_server_config
        self.set_server_config = bot.set_server_config
        self.is_command_enabled = bot.is_command_enabled 
        self.set_command_enabled_state = bot.set_command_enabled_state
        self.get_bot_presence_settings = bot.get_bot_presence_settings # 봇 상태 가져오기 함수 주입
        self.set_bot_presence_settings = bot.set_bot_presence_settings # 봇 상태 설정 함수 주입
        self.gemini_model = bot.gemini_model # Gemini AI 모델 주입

    # --- 메시지 리스너 (모든 메시지 처리의 시작점) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: # 봇이 보낸 메시지 또는 DM은 무시
            return

        # 보안 필터 (초대링크, 도배 감지) 실행
        # 이 함수가 False를 반환하면 메시지 삭제 등으로 메시지 처리 중단
        await self._process_security_filters(message)
        # _process_security_filters 내부에서 이미 메시지가 삭제되었다면, 여기서 추가 작업 필요 없음.
        # 메시지가 삭제되지 않았다면, bot.py의 on_message에서 bot.process_commands(message)가 호출되어
        # 해당 메시지에 대한 command (메시지 기반 명령어)가 처리됩니다.


    # --- 슬래시 커맨드 그룹 ---
    config_group = app_commands.Group(name="설정", description="이 서버의 봇 설정을 관리합니다.", guild_only=True)

    @config_group.command(name="차량등록채널", description="차량 등록 신청 포스트가 올라올 채널을 설정합니다.")
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_registration_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel):
        await self._set_channel_config(interaction.guild.id, 'registration_channel_id', 채널, interaction)

    @config_group.command(name="차량관리채널", description="차량 등록 알림 및 관리 버튼이 표시될 채널을 설정합니다.")
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_car_admin_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel):
        await self._set_channel_config(interaction.guild.id, 'car_admin_channel_id', 채널, interaction)

    @config_group.command(name="차량관리역할", description="차량 등록 알림 멘션을 받을 관리자 역할을 설정합니다.")
    @app_commands.describe(역할="설정할 역할")
    @commands.has_permissions(administrator=True)
    async def set_car_admin_role(self, interaction: discord.Interaction, 역할: discord.Role):
        await self._set_role_config(interaction.guild.id, 'car_admin_role_id', 역할, interaction)

    @config_group.command(name="차량승인채널", description="승인된 차량 등록증이 올라올 채널을 설정합니다.")
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_approved_cars_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel):
        await self._set_channel_config(interaction.guild.id, 'approved_cars_channel_id', 채널, interaction)

    @config_group.command(name="은행채널", description="은행 관련 명령어를 사용할 채널을 설정합니다.") # <--- 추가된 은행 채널 설정
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_bank_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel): # <--- 추가된 은행 채널 설정
        await self._set_channel_config(interaction.guild.id, 'bank_channel_id', 채널, interaction) # <--- 추가된 은행 채널 설정


    @config_group.command(name="보험관리역할", description="보험 청구 알림 멘션을 받을 관리자 역할을 설정합니다.")
    @app_commands.describe(역할="설정할 역할")
    @commands.has_permissions(administrator=True)
    async def set_insurance_admin_role(self, interaction: discord.Interaction, 역할: discord.Role):
        await self._set_role_config(interaction.guild.id, 'insurance_admin_role_id', 역할, interaction)

    @config_group.command(name="보험알림채널", description="새로운 보험 청구 알림이 표시될 채널을 설정합니다.")
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_insurance_notification_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel):
        await self._set_channel_config(interaction.guild.id, 'insurance_notification_channel_id', 채널, interaction)

    @config_group.command(name="티켓개설채널", description="사용자가 /ticket open을 사용할 수 있는 채널을 설정합니다.")
    @app_commands.describe(채널="설정할 채널")
    @commands.has_permissions(administrator=True)
    async def set_ticket_open_channel(self, interaction: discord.Interaction, 채널: discord.TextChannel):
        await self._set_channel_config(interaction.guild.id, 'ticket_open_channel_id', 채널, interaction)

    @config_group.command(name="티켓카테고리", description="새 티켓 채널이 생성될 카테고리를 설정합니다.")
    @app_commands.describe(카테고리="설정할 카테고리")
    @commands.has_permissions(administrator=True)
    async def set_ticket_category(self, interaction: discord.Interaction, 카테고리: discord.CategoryChannel):
        self.set_server_config(interaction.guild.id, 'ticket_category_id', 카테고리.id)
        await interaction.response.send_message(f"✅ 티켓 카테고리가 '{카테고리.name}'으로 설정되었습니다.", ephemeral=True)

    @config_group.command(name="티켓관리역할", description="티켓 채널에 자동 추가될 스태프 역할을 설정합니다.")
    @app_commands.describe(역할="설정할 역할")
    @commands.has_permissions(administrator=True)
    async def set_ticket_staff_role(self, interaction: discord.Interaction, 역할: discord.Role):
        await self._set_role_config(interaction.guild.id, 'ticket_staff_role_id', 역할, interaction)

    @config_group.command(name="등록세", description="차량 등록세를 설정합니다.") # <--- 추가
    @app_commands.describe(금액="설정할 등록세 금액")
    @commands.has_permissions(administrator=True)
    async def set_registration_tax(self, interaction: discord.Interaction, 금액: int):
        self.set_server_config(interaction.guild.id, 'car_registration_tax', 금액)
        await interaction.response.send_message(f"✅ 차량 등록세가 **{금액} 위키원**으로 설정되었습니다.", ephemeral=True) # 통화단위 변경

    @config_group.command(name="금지차량", description="금지 차량 목록을 추가/제거/확인합니다.") # <--- 추가
    @app_commands.describe(행동="추가, 제거, 확인 중 하나", 차량이름="추가/제거할 차량의 이름")
    @app_commands.choices(행동=[
        app_commands.Choice(name="추가", value="add"),
        app_commands.Choice(name="제거", value="remove"),
        app_commands.Choice(name="확인", value="check")
    ])
    @commands.has_permissions(administrator=True)
    async def manage_forbidden_cars(self, interaction: discord.Interaction, 행동: app_commands.Choice[str], 차량이름: str = None):
        server_config = self.bot.get_server_config(interaction.guild.id)
        current_forbidden_cars = json.loads(server_config.get('car_forbidden_cars_json', '[]'))

        if 행동.value == "add":
            if not 차량이름:
                await interaction.response.send_message("❌ 추가할 차량 이름을 입력해주세요.", ephemeral=True)
                return
            if 차량이름.lower() in [c.lower() for c in current_forbidden_cars]:
                await interaction.response.send_message(f"❌ '{차량이름}'은 이미 금지 차량 목록에 있습니다.", ephemeral=True)
                return
            current_forbidden_cars.append(차량이름)
            self.set_server_config(interaction.guild.id, 'car_forbidden_cars_json', json.dumps(current_forbidden_cars))
            await interaction.response.send_message(f"✅ '{차량이름}'을(를) 금지 차량 목록에 추가했습니다.", ephemeral=True)

        elif 행동.value == "remove":
            if not 차량이름:
                await interaction.response.send_message("❌ 제거할 차량 이름을 입력해주세요.", ephemeral=True)
                return
            if 차량이름.lower() not in [c.lower() for c in current_forbidden_cars]:
                await interaction.response.send_message(f"❌ '{차량이름}'은 금지 차량 목록에 없습니다.", ephemeral=True)
                return
            # 대소문자 구분 없이 제거
            current_forbidden_cars = [c for c in current_forbidden_cars if c.lower() != 차량이름.lower()]
            self.set_server_config(interaction.guild.id, 'car_forbidden_cars_json', json.dumps(current_forbidden_cars))
            await interaction.response.send_message(f"✅ '{차량이름}'을(를) 금지 차량 목록에서 제거했습니다.", ephemeral=True)

        elif 행동.value == "check":
            if not current_forbidden_cars:
                response_msg = "✅ 현재 금지 차량이 설정되어 있지 않습니다."
            else:
                response_msg = "현재 금지 차량 목록:\n" + "\n".join([f"- {c}" for c in current_forbidden_cars])
            await interaction.response.send_message(response_msg, ephemeral=True)

    @config_group.command(name="모든설정확인", description="이 서버의 현재 봇 설정들을 확인합니다.")
    @commands.has_permissions(administrator=True)
    async def show_all_configs(self, interaction: discord.Interaction):
        server_config = self.bot.get_server_config(interaction.guild.id) # bot에서 직접 get_server_config 호출
        if not server_config:
            await interaction.response.send_message("❌ 이 서버에 저장된 봇 설정이 없습니다. `/설정` 명령어를 사용해 설정해주세요.", ephemeral=True)
            return

        config_details = "--- 현재 서버 설정 ---\n"
        for key, value in server_config.items():
            if key == 'guild_id':
                config_details += f"**서버 ID:** {value}\n"
            elif key == 'guild_name': # 길드 이름도 표시
                config_details += f"**서버 이름:** {value if value else '미지정'}\n"
            elif '_channel_id' in key and value:
                channel = self.bot.get_channel(int(value))
                config_details += f"**{key.replace('_id', '').replace('_channel', ' 채널')}:** {channel.mention if channel else '채널을 찾을 수 없음'} (`{value}`)\n"
            elif '_role_id' in key and value:
                role = interaction.guild.get_role(int(value))
                config_details += f"**{key.replace('_id', '').replace('_role', ' 역할')}:** {role.mention if role else '역할을 찾을 수 없음'} (`{value}`)\n"
            elif '_category_id' in key and value:
                category = self.bot.get_channel(int(value))
                config_details += f"**{key.replace('_id', '').replace('_category', ' 카테고리')}:** {category.name if category else '카테고리를 찾을 수 없음'} (`{value}`)\n"
            elif 'json' in key: # JSON 형태의 값 처리
                display_value = value
                try:
                    parsed_json = json.loads(value)
                    display_value = str(parsed_json) # 보기 좋게 문자열로
                except json.JSONDecodeError:
                    pass # 파싱 실패 시 원본 텍스트 표시
                config_details += f"**{key.replace('_json', ' (JSON)')}:** {display_value}\n" # _json 태그 제거
            else: # 기타 설정 (숫자, 텍스트, 활성화 상태 등)
                display_value = value
                # 숫자 0,1로 저장되는 활성화 상태
                if isinstance(value, int) and (key.endswith('_enabled') or key.endswith('_active')):
                    display_value = "활성화 ✅" if value == 1 else "비활성화 ❌"
                config_details += f"**{key}:** {display_value}\n"

        embed = discord.Embed(
            title=f"{interaction.guild.name} 서버의 봇 설정",
            description=config_details,
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- 봇 상태 설정 커맨드 (슈퍼 관리자용) ---
    @config_group.command(name="봇상태설정", description="봇의 Discord 상태와 활동을 설정합니다 (슈퍼 관리자 전용).")
    @app_commands.describe(
        상태="봇의 상태 (온라인, 자리비움, 방해금지, 오프라인표시)",
        활동유형="활동 유형 (플레이중, 스트리밍중, 듣는중, 시청중)",
        활동메시지="활동에 표시할 메시지"
    )
    @commands.has_permissions(administrator=True) # 관리자 권한 필요
    async def set_bot_status_command(self, interaction: discord.Interaction, 
                                     상태: str, 활동유형: str, 활동메시지: str):
        # 환경 변수에서 슈퍼 관리자 이름 가져오기
        dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME")
        # interaction.user는 Discord.User 또는 Discord.Member 객체이므로 str()로 변환하여 비교 (Username#Discriminator 형식)
        # Note: Discord Username이 #디스크리미네이터가 없는 경우 str()은 username만 반환합니다.
        # 실제 비교시에는 Discord User ID를 사용하는 것이 더 안전합니다.
        # 이 부분은 관리자 역할 확인 (commands.has_permissions)으로 대체하는 것이 더 권장됩니다.
        # if str(interaction.user) != dashboard_admin_username: 
        #      await interaction.response.send_message("❌ 이 명령어는 슈퍼 관리자만 사용할 수 있습니다.", ephemeral=True)
        #      return

        # 유효한 상태 및 활동 유형인지 확인
        valid_status = ['온라인', '자리비움', '방해금지', '오프라인표시']
        valid_activity_type = ['플레이중', '스트리밍중', '듣는중', '시청중']

        if 상태 not in valid_status:
            await interaction.response.send_message(f"❌ 유효하지 않은 상태입니다. ({', '.join(valid_status)} 중 선택)", ephemeral=True)
            return
        if 활동유형 not in valid_activity_type:
            await interaction.response.send_message(f"❌ 유효하지 않은 활동 유형입니다. ({', '.join(valid_activity_type)} 중 선택)", ephemeral=True)
            return

        # DB에 저장할 값으로 변환
        status_map = {'온라인': 'online', '자리비움': 'idle', '방해금지': 'dnd', '오프라인표시': 'invisible'}
        activity_type_map = {'플레이중': 'playing', '스트리밍중': 'streaming', '듣는중': 'listening', '시청중': 'watching'}

        self.set_bot_presence_settings(
            status_map[상태], 
            activity_type_map[활동유형], 
            활동메시지
        )
        await interaction.response.send_message(f"✅ 봇의 Discord 상태가 성공적으로 설정되었습니다. 몇 분 내로 반영됩니다.", ephemeral=True)


    # --- 명령어 활성화/비활성화 그룹 ---
    command_toggle_group = app_commands.Group(name="명령어", description="이 서버의 명령어 활성화 상태를 관리합니다.", guild_only=True)

    @command_toggle_group.command(name="활성화", description="이 서버에서 특정 슬래시 커맨드를 활성화합니다.")
    @app_commands.describe(커맨드="활성화할 명령어 (예: 잔액, 차량등록)")
    @commands.has_permissions(administrator=True)
    async def enable_command(self, interaction: discord.Interaction, 커맨드: str):
        self.set_command_enabled_state(interaction.guild.id, 커맨드, True)
        await interaction.response.send_message(f"✅ 명령어 `저스트 {커맨드}`가 이 서버에서 활성화되었습니다.", ephemeral=True) # 저스트 접두사 추가

    @command_toggle_group.command(name="비활성화", description="이 서버에서 특정 슬래시 커맨드를 비활성화합니다.")
    @app_commands.describe(커맨드="비활성화할 명령어 (예: 잔액, 차량등록)")
    @commands.has_permissions(administrator=True)
    async def disable_command(self, interaction: discord.Interaction, 커맨드: str):
        self.set_command_enabled_state(interaction.guild.id, 커맨드, False)
        await interaction.response.send_message(f"❌ 명령어 `저스트 {커맨드}`가 이 서버에서 비활성화되었습니다.", ephemeral=True) # 저스트 접두사 추가

    @command_toggle_group.command(name="상태확인", description="이 서버의 모든 명령어 활성화 상태를 확인합니다.")
    @commands.has_permissions(administrator=True)
    async def check_command_states(self, interaction: discord.Interaction):
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT command_name, is_enabled FROM server_command_states WHERE guild_id = ?", (str(interaction.guild.id),))
        states = cursor.fetchall()
        conn.close()

        status_message = "--- 명령어 활성화 상태 ---\n"
        if not states:
            status_message += "모든 명령어는 기본적으로 활성화되어 있습니다 (별도 설정 없음).\n"
        else:
            for state in states:
                status = "활성화됨 ✅" if state['is_enabled'] == 1 else "비활성화됨 ❌"
                status_message += f"**저스트 {state['command_name']}**: {status}\n" # 저스트 접두사 추가

        embed = discord.Embed(
            title=f"{interaction.guild.name} 서버의 명령어 상태",
            description=status_message,
            color=discord.Color.light_grey()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- 슬래시 커맨드 (모더레이션) ---
    @app_commands.command(name="킥", description="유저를 서버에서 강퇴시킵니다.")
    @app_commands.describe(유저="강퇴할 유저", 사유="강퇴 사유")
    @commands.has_permissions(kick_members=True)
    async def kick_slash(self, interaction: discord.Interaction, 유저: discord.Member, 사유: str = "사유 없음"): # 이름 변경
        await self._kick_user(유저, 사유, interaction=interaction)

    @app_commands.command(name="밴", description="유저를 서버에서 추방시킵니다.")
    @app_commands.describe(유저="추방할 유저", 사유="추방 사유", 일수="메시지 삭제 일수 (최대 7일)")
    @commands.has_permissions(ban_members=True)
    async def ban_slash(self, interaction: discord.Interaction, 유저: discord.Member, 사유: str = "사유 없음", 일수: app_commands.Range[int, 0, 7] = 0): # 이름 변경
        await self._ban_user(유저, 사유, 일수, interaction=interaction)

    @app_commands.command(name="청소", description="채널의 메시지를 삭제합니다.")
    @app_commands.describe(개수="삭제할 메시지 개수 (최대 100개)")
    @commands.has_permissions(manage_messages=True)
    async def clear_slash(self, interaction: discord.Interaction, 개수: app_commands.Range[int, 1, 100]): # 이름 변경
        await self._clear_messages(개수, interaction=interaction)

    @app_commands.command(name="역할부여", description="유저에게 역할을 부여합니다.")
    @app_commands.describe(유저="역할을 부여할 유저", 역할="부여할 역할")
    @commands.has_permissions(manage_roles=True)
    async def add_role_slash(self, interaction: discord.Interaction, 유저: discord.Member, 역할: discord.Role): # 이름 변경
        await self._manage_role(유저, 역할, 'add', interaction=interaction)

    @app_commands.command(name="역할삭제", description="유저의 역할을 삭제합니다.")
    @app_commands.describe(유저="역할을 삭제할 유저", 역할="삭제할 역할")
    @commands.has_permissions(manage_roles=True)
    async def remove_role_slash(self, interaction: discord.Interaction, 유저: discord.Member, 역할: discord.Role): # 이름 변경
        await self._manage_role(유저, 역할, 'remove', interaction=interaction)

    @app_commands.command(name="경고", description="유저에게 경고를 부여합니다.")
    @app_commands.describe(유저="경고를 줄 유저", 사유="경고 사유")
    @commands.has_permissions(kick_members=True)
    async def warn_slash(self, interaction: discord.Interaction, 유저: discord.Member, 사유: str = "사유 없음"): # 이름 변경
        await self._warn_user(유저, 사유, interaction=interaction)

    @app_commands.command(name="경고조회", description="유저의 경고 내역을 조회합니다.")
    @app_commands.describe(유저="경고 내역을 조회할 유저")
    async def check_warnings_slash(self, interaction: discord.Interaction, 유저: discord.Member): # 이름 변경
        await self._check_warnings(유저, interaction=interaction)

    @app_commands.command(name="경고삭제", description="유저의 경고를 삭제합니다.")
    @app_commands.describe(유저="경고를 삭제할 유저", 인덱스="삭제할 경고의 번호 (모두 삭제하려면 '모두')", 사유="경고 삭제 사유")
    @commands.has_permissions(kick_members=True)
    async def remove_warning_slash(self, interaction: discord.Interaction, 유저: discord.Member, 인덱스: str, 사유: str = "사유 없음"): # 이름 변경
        await self._remove_warning(유저, 인덱스, 사유, interaction=interaction)

    # --- 티켓 명령어 그룹 ---
    ticket_group = app_commands.Group(name="티켓", description="고객 지원 티켓을 관리합니다.", guild_only=True)

    @ticket_group.command(name="오픈", description="새로운 고객 지원 티켓을 엽니다.")
    @app_commands.describe(사유="티켓을 여는 이유")
    async def open_ticket_slash(self, interaction: discord.Interaction, 사유: str = "사유 없음"): # 이름 변경
        await self._open_ticket(interaction.user, 사유, interaction=interaction)

    @ticket_group.command(name="닫기", description="현재 채널의 티켓을 닫습니다.")
    @app_commands.describe(사유="티켓을 닫는 이유")
    async def close_ticket_slash(self, interaction: discord.Interaction, 사유: str = "사유 없음"): # 이름 변경
        await self._close_ticket(interaction.user, interaction.channel, 사유, interaction=interaction)

    @app_commands.command(name="봇상태", description="현재 저스트봇의 상태와 활동을 확인합니다.")
    @app_commands.guild_only()
    async def show_bot_status_slash(self, interaction: discord.Interaction): # 이름 변경
        await self._show_bot_status(interaction.user, interaction.channel, interaction=interaction)

    # --- Gemini AI 채널명 변경 커맨드 ---
    @app_commands.command(name="채널명변경", description="Gemini AI가 텍스트를 분석하여 채널명을 제안하고 변경합니다.")
    @app_commands.describe(분석할텍스트="AI가 채널명을 제안할 기준 텍스트를 입력하세요 (예: 새로운 모험, RPG 길드 채팅)")
    @app_commands.guild_only()
    @commands.has_permissions(manage_channels=True) # 채널 관리 권한 필요
    async def rename_channel_ai_slash(self, interaction: discord.Interaction, 분석할텍스트: str):
        await self._rename_channel_ai(interaction.channel, 분석할텍스트, interaction=interaction)

    # --- 보안 기능 (슬래시 커맨드) ---
    @app_commands.command(name="스캔블랙리스트", description="글로벌 블랙리스트에 등록된 악성 유저인지 스캔합니다.")
    @app_commands.describe(유저="스캔할 유저를 멘션하세요.")
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def scan_blacklist_slash(self, interaction: discord.Interaction, 유저: discord.Member):
        await self._scan_blacklist_user(유저, interaction=interaction)

    @app_commands.command(name="보안리포트", description="이 서버의 보안 설정 상태에 대한 리포트를 제공합니다.")
    @app_commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def security_report_slash(self, interaction: discord.Interaction):
        await self._security_report(interaction=interaction)

    @app_commands.command(name="명령어리스트", description="이 채널에서 사용 가능한 명령어 목록을 보여줍니다.")
    @app_commands.guild_only()
    async def command_list_slash(self, interaction: discord.Interaction):
        await self._list_commands_report(interaction.guild, interaction.channel, interaction=interaction)

    # --- 메시지 기반 명령어 ---
    @commands.command(name="킥", help="유저를 서버에서 강퇴시킵니다. (예: 저스트 킥 @유저 사유)")
    @commands.has_permissions(kick_members=True)
    async def kick_msg(self, ctx: commands.Context, 유저: discord.Member, *, 사유: str = "사유 없음"):
        # 메시지 기반 명령어는 슬래시 커맨드 비활성화와 별개로 작동 (나중에 제어 가능하도록 확장)
        await self._kick_user(유저, 사유, ctx=ctx)

    @commands.command(name="밴", help="유저를 서버에서 추방시킵니다. (예: 저스트 밴 @유저 사유)")
    @commands.has_permissions(ban_members=True)
    async def ban_msg(self, ctx: commands.Context, 유저: discord.Member, *, 사유: str = "사유 없음"):
        await self._ban_user(유저, 사유, 0, ctx=ctx) # 메시지 기반 밴은 일수 설정을 간단히 0으로

    @commands.command(name="청소", help="채널의 메시지를 삭제합니다. (예: 저스트 청소 10)")
    @commands.has_permissions(manage_messages=True)
    async def clear_msg(self, ctx: commands.Context, 개수: int):
        await self._clear_messages(개수, ctx=ctx)

    @commands.command(name="역할부여", help="유저에게 역할을 부여합니다. (예: 저스트 역할부여 @유저 @역할)")
    @commands.has_permissions(manage_roles=True)
    async def add_role_msg(self, ctx: commands.Context, 유저: discord.Member, 역할: discord.Role):
        await self._manage_role(유저, 역할, 'add', ctx=ctx)

    @commands.command(name="역할삭제", help="유저의 역할을 삭제합니다. (예: 저스트 역할삭제 @유저 @역할)")
    @commands.has_permissions(manage_roles=True)
    async def remove_role_msg(self, ctx: commands.Context, 유저: discord.Member, 역할: discord.Role):
        await self._manage_role(유저, 역할, 'remove', ctx=ctx)

    @commands.command(name="경고", help="유저에게 경고를 부여합니다. (예: 저스트 경고 @유저 사유)")
    @commands.has_permissions(kick_members=True)
    async def warn_msg(self, ctx: commands.Context, 유저: discord.Member, *, 사유: str = "사유 없음"):
        await self._warn_user(유저, 사유, ctx=ctx)

    @commands.command(name="경고조회", help="유저의 경고 내역을 조회합니다. (예: 저스트 경고조회 @유저)")
    async def check_warnings_msg(self, ctx: commands.Context, 유저: discord.Member):
        await self._check_warnings(유저, ctx=ctx)

    @commands.command(name="경고삭제", help="유저의 경고를 삭제합니다. (예: 저스트 경고삭제 @유저 1 사유 / 저스트 경고삭제 @유저 모두 사유)")
    @commands.has_permissions(kick_members=True)
    async def remove_warning_msg(self, ctx: commands.Context, 유저: discord.Member, 인덱스: str, *, 사유: str = "사유 없음"):
        await self._remove_warning(유저, 인덱스, 사유, ctx=ctx)

    @commands.command(name="봇상태", help="현재 저스트봇의 상태와 활동을 확인합니다. (예: 저스트 봇상태)")
    async def show_bot_status_msg(self, ctx: commands.Context):
        await self._show_bot_status(ctx.author, ctx.channel, ctx=ctx)

    @commands.command(name="채널명변경", help="Gemini AI가 텍스트를 분석하여 채널명을 제안하고 변경합니다. (예: 저스트 채널명변경 새로운 모험의 시작)")
    @commands.has_permissions(manage_channels=True)
    async def rename_channel_ai_msg(self, ctx: commands.Context, *, 분석할텍스트: str):
        if not ctx.guild:
            await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.")
            return
        await self._rename_channel_ai(ctx.channel, 분석할텍스트, ctx=ctx)

    @commands.command(name="스캔블랙리스트", help="글로벌 블랙리스트에 등록된 악성 유저인지 스캔합니다. (예: 저스트 스캔블랙리스트 @유저)")
    @commands.has_permissions(administrator=True) # 관리자만 스캔 가능
    async def scan_blacklist_msg(self, ctx: commands.Context, 유저: discord.Member):
        await self._scan_blacklist_user(유저, ctx=ctx)

    @commands.command(name="보안리포트", help="이 서버의 보안 설정 상태에 대한 리포트를 제공합니다. (예: 저스트 보안리포트)")
    @commands.has_permissions(administrator=True)
    async def security_report_msg(self, ctx: commands.Context):
        await self._security_report(ctx=ctx)

    @commands.command(name="명령어리스트", help="이 채널에서 사용 가능한 명령어 목록을 보여줍니다. (예: 저스트 명령어리스트)")
    async def command_list_msg(self, ctx: commands.Context):
        if not ctx.guild:
            await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.")
            return
        await self._list_commands_report(ctx.guild, ctx.channel, ctx=ctx)

    # --- 메시지 리스너 (보안 필터) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: # 봇이 보낸 메시지 또는 DM은 무시
            return

        # 보안 필터 (초대링크, 도배 감지) 실행
        # 이 함수가 False를 반환하면 메시지 삭제 등으로 메시지 처리 중단
        # bot.py의 on_message에서 bot.process_commands(message)를 호출하기 전에
        # 보안 필터가 메시지를 삭제할 수 있도록 먼저 호출됩니다.
        await self._process_security_filters(message)
        # _process_security_filters 내부에서 이미 메시지가 삭제되었다면, 여기서 추가 작업 필요 없음.
        # 메시지가 삭제되지 않았다면, bot.py의 on_message에서 bot.process_commands(message)가 호출되어
        # 해당 메시지에 대한 command (메시지 기반 명령어)가 처리됩니다.

    # --- 내부 함수들 (슬래시 및 메시지 기반 명령어에서 공통 사용) ---
    async def _check_authority(self, caller, target_channel, permission_name: str, has_permission_func):
        """명령어 실행 권한을 확인하고 응답을 보냅니다."""
        is_interaction = isinstance(caller, discord.Interaction)

        if not await has_permission_func(caller.user if is_interaction else caller): # caller는 Interaction or Context.author
            response_msg = f"❌ 이 명령어를 사용할 권한이 없습니다. `{permission_name}` 권한이 필요합니다."
            if is_interaction:
                await caller.response.send_message(response_msg, ephemeral=True)
            else: # commands.Context
                await target_channel.send(response_msg)
            return False
        return True

    async def _kick_user(self, 유저: discord.Member, 사유: str, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저를 서버에서 강퇴 처리합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author # Context의 member는 Context.author (commands.Context.author는 Member 객체임)

        if not await self._check_authority(caller_obj, target_channel, "Kick Members", lambda u: u.guild_permissions.kick_members): return

        if 유저.bot:
            response_msg = "❌ 봇에게는 킥을 할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 봇보다 높은 역할의 유저는 킥 불가
        if 유저.top_role >= target_guild.me.top_role:
            response_msg = "❌ 저보다 높은 역할의 유저는 킥할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 호출자보다 역할이 높거나 같은 유저는 킥 불가 (서버 관리자 제외)
        caller_member = interaction.user if interaction else ctx.author
        if 유저.top_role >= caller_member.top_role and not caller_member.guild_permissions.administrator:
            response_msg = "❌ 당신보다 높은 역할의 유저는 킥할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=False) # 이미 응답이 없으면 defer
            await 유저.kick(reason=사유)
            response_msg = f"✅ {유저.display_name}님을 강퇴했습니다. 사유: {사유}"
            if interaction: await interaction.followup.send(response_msg)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

            try: await 유저.send(f"🚨 당신은 {target_guild.name} 서버에서 강퇴당했습니다. 사유: {사유}")
            except discord.Forbidden: print(f"유저 {유저.display_name}에게 DM을 보낼 수 없습니다.")
        except discord.Forbidden:
            response_msg = "❌ 봇에게 강퇴 권한이 없거나, 대상 유저의 역할이 봇보다 높습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        except Exception as e:
            response_msg = f"❌ 킥 실패: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

    async def _ban_user(self, 유저: discord.Member, 사유: str, 일수: int = 0, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저를 서버에서 추방 처리합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.ban_members)
        if not await self._check_authority(caller_obj, target_channel, "Ban Members", permission_checker): return

        if 유저.bot:
            response_msg = "❌ 봇에게는 밴을 할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 봇보다 높은 역할의 유저는 밴 불가
        if 유저.top_role >= target_guild.me.top_role:
            response_msg = "❌ 저보다 높은 역할의 유저는 밴할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 호출자보다 역할이 높은 유저 밴 불가 (서버 관리자 제외)
        caller_member = interaction.user if interaction else ctx.author
        if 유저.top_role >= caller_member.top_role and not caller_member.guild_permissions.administrator:
            response_msg = "❌ 당신보다 높은 역할의 유저는 밴할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=False)
            await 유저.ban(reason=사유, delete_message_days=일수)
            response_msg = f"✅ {유저.display_name}님을 추방했습니다. 사유: {사유}, 메시지 삭제 일수: {일수}일"
            if interaction: await interaction.followup.send(response_msg)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            try: await 유저.send(f"🚨 당신은 {target_guild.name} 서버에서 추방당했습니다. 사유: {사유}")
            except discord.Forbidden: print(f"유저 {유저.display_name}에게 DM을 보낼 수 없습니다.")
        except discord.Forbidden:
            response_msg = "❌ 봇에게 추방 권한이 없거나, 대상 유저의 역할이 봇보다 높습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        except Exception as e:
            response_msg = f"❌ 밴 실패: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

    async def _clear_messages(self, 개수: int, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """채널의 메시지를 삭제합니다."""
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.manage_messages)
        if not await self._check_authority(caller_obj, target_channel, "Manage Messages", permission_checker): return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=True)
            deleted = await target_channel.purge(limit=개수)
            response_msg = f"✅ 메시지 {len(deleted)}개를 삭제했습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        except discord.Forbidden:
            response_msg = "❌ 봇에게 메시지 관리 권한이 없습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        except Exception as e:
            response_msg = f"❌ 청소 실패: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

    async def _manage_role(self, 유저: discord.Member, 역할: discord.Role, action: str, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저의 역할을 부여하거나 삭제합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.manage_roles)
        if not await self._check_authority(caller_obj, target_channel, "Manage Roles", permission_checker): return

        if 역할 >= target_guild.me.top_role: # 봇보다 높은 역할은 관리 불가
            response_msg = "❌ 저보다 높은 역할은 부여/삭제할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 호출자보다 역할이 높은 유저 역할 관리 불가 (서버 관리자 제외)
        caller_member = interaction.user if interaction else ctx.author
        if 역할 >= caller_member.top_role and not caller_member.guild_permissions.administrator:
            response_msg = "❌ 당신보다 높은 역할은 부여/삭제할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=False)
            if action == 'add':
                await 유저.add_roles(역할)
                response_msg = f"✅ {유저.display_name}님에게 '{역할.name}' 역할을 부여했습니다."
            else: # action == 'remove'
                await 유저.remove_roles(역할)
                response_msg = f"✅ {유저.display_name}님에게서 '{역할.name}' 역할을 삭제했습니다."

            if interaction: await interaction.followup.send(response_msg)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

        except discord.Forbidden:
            response_msg = "❌ 봇에게 역할 관리 권한이 없거나, 대상 역할의 위치가 봇보다 높습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        except Exception as e:
            response_msg = f"❌ 역할 관리 실패: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

    async def _warn_user(self, 유저: discord.Member, 사유: str, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저에게 경고를 부여합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.kick_members)
        if not await self._check_authority(caller_obj, target_channel, "Kick Members", permission_checker): return

        if 유저.bot:
            response_msg = "❌ 봇에게는 경고를 줄 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        if 유저.id == (interaction.user.id if interaction else ctx.author.id):
            response_msg = "❌ 자기 자신에게 경고를 줄 순 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        # 호출자보다 역할이 높은 유저는 경고 불가 (서버 관리자 제외)
        caller_member = interaction.user if interaction else ctx.author
        if 유저.top_role >= caller_member.top_role and not caller_member.guild_permissions.administrator:
            response_msg = "❌ 당신보다 높은 역할의 유저는 경고할 수 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id_str = str(유저.id)

        cursor.execute("""
            INSERT INTO user_warnings (user_id, username, reason, moderator_id, moderator_name, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id_str, 유저.display_name, 사유, str(caller_member.id), caller_member.display_name, datetime.datetime.now(datetime.UTC).isoformat())) # DeprecationWarning 수정
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM user_warnings WHERE user_id = ?", (user_id_str,))
        warning_count = cursor.fetchone()[0]
        conn.close()

        warn_embed = discord.Embed(
            title="🚨 경고 알림",
            description=f"{유저.mention}님이 경고를 받았습니다.",
            color=discord.Color.red()
        )
        warn_embed.add_field(name="사유", value=사유, inline=False)
        warn_embed.add_field(name="경고 횟수", value=f"총 **{warning_count}회**", inline=False)
        warn_embed.set_footer(text=f"관리자: {caller_member.display_name}")

        if interaction and not interaction.response.is_done(): await interaction.response.send_message(embed=warn_embed)
        elif ctx: await ctx.send(embed=warn_embed)
        elif channel_to_send: await channel_to_send.send(embed=warn_embed)

        try:
            await 유저.send(f"🚨 당신은 {target_guild.name} 서버에서 경고를 받았습니다. 사유: {사유}\n총 경고 횟수: {warning_count}회")
        except discord.Forbidden:
            print(f"유저 {유저.display_name}에게 DM을 보낼 수 없습니다.")

        # 자동 강퇴 경고 횟수 확인 (서버 설정에서 불러오기)
        server_config = self.bot.get_server_config(target_guild.id)
        auto_kick_warn_count = server_config.get('auto_kick_warn_count', 5) # 기본값 5

        if warning_count >= auto_kick_warn_count:
            try:
                await 유저.kick(reason=f"경고 {auto_kick_warn_count}회 누적으로 자동 강퇴")
                if target_channel: await target_channel.send(f"⚠️ {유저.mention}님이 경고 누적({warning_count}회)으로 서버에서 자동 강퇴되었습니다.")
            except discord.Forbidden:
                if target_channel: await target_channel.send(f"⚠️ {유저.mention}님이 경고 누적({warning_count}회)으로 자동 강퇴 대상이지만, 봇의 권한 부족으로 강퇴하지 못했습니다.")
            except Exception as e:
                print(f"자동 강퇴 처리 중 오류 발생: {e}")
                if target_channel: await target_channel.send(f"⚠️ {유저.mention}님 자동 강퇴 처리 중 오류 발생: {e}")


    async def _check_warnings(self, 유저: discord.Member, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저의 경고 내역을 조회합니다."""
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.kick_members) # 경고 조회는 킥 권한이 있는 사람만으로 가정
        if not await self._check_authority(caller_obj, target_channel, "Kick Members", permission_checker): return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id_str = str(유저.id)
        cursor.execute("SELECT reason, moderator_name, timestamp FROM user_warnings WHERE user_id = ? ORDER BY timestamp ASC", (user_id_str,))
        warnings = cursor.fetchall()
        conn.close()

        if not warnings:
            response_msg = f"✅ {유저.display_name}님은 경고 내역이 없습니다!"
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        warn_list_str = ""
        for i, w in enumerate(warnings):
            # 시간 포맷 변경 (날짜만)
            warn_time = datetime.datetime.fromisoformat(w['timestamp']).strftime('%Y-%m-%d')
            warn_list_str += f"{i+1}. 사유: {w['reason']} (관리자: {w['moderator_name']}, 날짜: {warn_time})\n"

        embed = discord.Embed(
            title=f"⚠️ {유저.display_name}님의 경고 내역 (총 {len(warnings)}회)",
            description=warn_list_str,
            color=discord.Color.orange()
        )
        if interaction and not interaction.response.is_done(): await interaction.response.send_message(embed=embed, ephemeral=True)
        elif ctx: await ctx.send(embed=embed)
        elif channel_to_send: await channel_to_send.send(embed=embed)

    async def _remove_warning(self, 유저: discord.Member, 인덱스: str, 사유: str, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """유저의 경고를 삭제합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        permission_checker = (lambda u: u.guild_permissions.kick_members) # 경고 삭제는 킥 권한이 있는 사람만으로 가정
        if not await self._check_authority(caller_obj, target_channel, "Kick Members", permission_checker): return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        user_id_str = str(유저.id)

        if 인덱스.lower() == "모두":
            cursor.execute("DELETE FROM user_warnings WHERE user_id = ?", (user_id_str,))
            conn.commit()
            conn.close()
            response_msg = f"✅ {유저.display_name}님의 모든 경고를 삭제했습니다. 사유: {사유}"
            if interaction and not interaction.response.is_done(): await interaction.response.send_message(response_msg)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
        else:
            try:
                idx = int(인덱스) - 1
                cursor.execute("SELECT id FROM user_warnings WHERE user_id = ? ORDER BY timestamp ASC LIMIT 1 OFFSET ?", (user_id_str, idx))
                warning_to_delete = cursor.fetchone()

                if warning_to_delete:
                    cursor.execute("DELETE FROM user_warnings WHERE id = ?", (warning_to_delete['id'],))
                    conn.commit()
                    conn.close()
                    response_msg = f"✅ {유저.display_name}님의 {idx+1}번째 경고를 삭제했습니다. 사유: {사유}"
                    if interaction and not interaction.response.is_done(): await interaction.response.send_message(response_msg)
                    elif ctx: await ctx.send(response_msg)
                    elif channel_to_send: await channel_to_send.send(response_msg)
                else:
                    conn.close()
                    response_msg = "❌ 유효하지 않은 경고 번호입니다!"
                    if interaction and not interaction.response.is_done(): await interaction.response.send_message(response_msg, ephemeral=True)
                    elif ctx: await ctx.send(response_msg)
                    elif channel_to_send: await channel_to_send.send(response_msg)
            except ValueError:
                conn.close()
                response_msg = "❌ 경고 번호는 숫자이거나 '모두'여야 합니다!"
                if interaction and not interaction.response.is_done(): await interaction.response.send_message(response_msg, ephemeral=True)
                elif ctx: await ctx.send(response_msg)
                elif channel_to_send: await channel_to_send.send(response_msg)

    async def _open_ticket(self, user: discord.User, 사유: str, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """새로운 고객 지원 티켓을 엽니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        # 권한 확인은 별도로 하지 않음 (누구나 티켓 열 수 있어야 함)

        if not target_guild:
            response_msg = "❌ 이 명령어는 서버(길드)에서만 사용할 수 있습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        server_config = self.bot.get_server_config(target_guild.id)
        if not server_config:
            response_msg = "❌ 이 서버의 봇 설정이 완료되지 않았습니다. 관리자에게 문의하여 `/설정` 명령어를 사용해 필요한 채널과 역할을 설정해달라고 요청하세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        ticket_open_channel_id = server_config.get('ticket_open_channel_id')
        ticket_category_id = server_config.get('ticket_category_id')
        ticket_staff_role_id = server_config.get('ticket_staff_role_id')

        if not all([ticket_open_channel_id, ticket_category_id, ticket_staff_role_id]):
            response_msg = (
                "❌ 티켓 기능의 필수 설정(티켓 개설 채널, 티켓 카테고리, 티켓 관리 역할)이 완료되지 않았습니다. "
                "관리자에게 문의하여 `/설정` 명령어를 사용해 필요한 채널과 역할을 설정해달라고 요청하세요."
            )
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        # 티켓 개설 채널에서만 명령어가 사용되었는지 확인
        if str(target_channel.id) != ticket_open_channel_id:
            ticket_channel_obj = self.bot.get_channel(int(ticket_open_channel_id))
            response_msg = f"❌ 티켓은 {ticket_channel_obj.mention if ticket_channel_obj else '설정된 티켓 개설 채널'}에서만 열 수 있습니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        # 이미 열려있는 티켓이 있는지 확인
        cursor.execute("SELECT channel_id FROM tickets WHERE user_id = ? AND status = 'open'", (str(user.id),))
        if cursor.fetchone():
            conn.close()
            response_msg = "❌ 이미 열려있는 티켓이 있습니다. 먼저 기존 티켓을 닫아주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        overwrites = {
            target_guild.default_role: discord.PermissionOverwrite(read_messages=False), # @everyone 읽기 권한 제거
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True), # 티켓 개설자 읽기/쓰기
            target_guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True) # 봇 읽기/쓰기
        }
        staff_role_obj = target_guild.get_role(int(ticket_staff_role_id))
        if staff_role_obj:
            overwrites[staff_role_obj] = discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)

        category_obj = self.bot.get_channel(int(ticket_category_id))
        if not category_obj or not isinstance(category_obj, discord.CategoryChannel):
            response_msg = "❌ 설정된 티켓 카테고리를 찾을 수 없습니다. 관리자에게 문의하세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=True) # defer
            ticket_channel_name = f"티켓-{user.name.lower().replace(' ', '-')}-{datetime.datetime.now(datetime.UTC).strftime('%m%d%H%M')}"
            channel = await target_guild.create_text_channel(
                ticket_channel_name,
                category=category_obj,
                overwrites=overwrites,
                topic=f"{user.name}님이 개설한 티켓입니다. 사유: {사유}"
            )

            cursor.execute("""
                INSERT INTO tickets (user_id, username, guild_id, channel_id, status, reason, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(user.id), user.display_name, str(target_guild.id), str(channel.id), "open", 사유, datetime.datetime.now(datetime.UTC).isoformat()))
            ticket_id = cursor.lastrowid
            conn.commit()
            conn.close()

            ticket_embed = discord.Embed(
                title=f"📝 새 티켓이 생성되었습니다! #{ticket_id}",
                description=f"{user.mention}님, 티켓을 열어주셔서 감사합니다. 스태프가 곧 연락드릴 것입니다.",
                color=discord.Color.blue()
            )
            ticket_embed.add_field(name="개설 사유", value=사유, inline=False)
            if staff_role_obj:
                ticket_embed.set_footer(text=f"문의 사항이 있다면 {staff_role_obj.name} 역할을 멘션해주세요.")

            await channel.send(user.mention + (staff_role_obj.mention if staff_role_obj else ""), embed=ticket_embed)
            response_msg = f"✅ 티켓이 성공적으로 생성되었습니다! {channel.mention}으로 이동해주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)

        except discord.Forbidden:
            conn.close()
            response_msg = "❌ 티켓 채널을 생성할 권한이 없습니다. 봇의 권한을 확인해주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
        except Exception as e:
            conn.close()
            print(f"티켓 생성 중 오류 발생: {e}")
            response_msg = f"❌ 티켓 생성 중 알 수 없는 오류가 발생했습니다: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)

    async def _close_ticket(self, user: discord.User, target_channel: discord.TextChannel, 사유: str, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """현재 채널의 티켓을 닫습니다."""
        target_guild = interaction.guild if interaction else ctx.guild

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'", (str(target_channel.id),))
        ticket = cursor.fetchone()

        if not ticket:
            conn.close()
            response_msg = "❌ 이 채널은 열려있는 티켓 채널이 아니거나, 이미 닫혔습니다."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        ticket_staff_role_id = self.bot.get_server_config(target_guild.id).get('ticket_staff_role_id')
        is_staff = False
        if ticket_staff_role_id:
            staff_role_obj = target_guild.get_role(int(ticket_staff_role_id))
            if staff_role_obj and staff_role_obj in user.roles:
                is_staff = True

        if str(user.id) != ticket['user_id'] and not is_staff and not user.guild_permissions.administrator:
            conn.close()
            response_msg = "❌ 티켓 개설자 또는 스태프(관리자)만 티켓을 닫을 수 있습니다."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        try:
            if interaction and not interaction.response.is_done(): await interaction.response.defer(ephemeral=True)
            cursor.execute("""
                UPDATE tickets SET status = ?, closed_at = ?, closed_by = ?
                WHERE id = ?
            """, ("closed", datetime.datetime.now(datetime.UTC).isoformat(), str(user.id), ticket['id'])) # DeprecationWarning 수정
            conn.commit()
            conn.close()

            embed = discord.Embed(
                title=f"🔒 티켓 #{ticket['id']}이(가) 닫혔습니다.",
                description=f"티켓이 {user.mention}에 의해 닫혔습니다.\n**사유:** {사유}",
                color=discord.Color.red()
            )
            embed.set_footer(text="이 채널은 잠시 후 자동으로 삭제됩니다.")
            await target_channel.send(embed=embed)

            response_msg = f"✅ 티켓이 성공적으로 닫혔습니다. 채널은 잠시 후 삭제됩니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)

            await asyncio.sleep(5) # 5초 대기
            await target_channel.delete(reason=f"티켓 #{ticket['id']} 닫힘.")

        except discord.Forbidden:
            response_msg = "❌ 채널을 삭제할 권한이 없습니다. 봇의 권한을 확인해주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
        except Exception as e:
            print(f"티켓 닫기 중 오류 발생: {e}")
            response_msg = f"❌ 티켓 닫기 중 알 수 없는 오류가 발생했습니다: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)

    async def _show_bot_status(self, user: discord.User, channel: discord.TextChannel, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """현재 저스트봇의 상태와 활동을 확인하고 보고합니다."""
        if interaction: await interaction.response.defer(ephemeral=False)

        settings = self.bot.get_bot_presence_settings()
        if not settings:
            response_msg = "❌ 봇 상태 설정 정보를 불러올 수 없습니다. 관리자에게 문의하세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        status_display_map = {
            'online': '🟢 온라인',
            'idle': '🟠 자리 비움',
            'dnd': '🔴 방해 금지',
            'invisible': '⚫ 오프라인 표시'
        }
        activity_type_display_map = {
            'playing': '🎮 플레이 중',
            'streaming': '📺 스트리밍 중',
            'listening': '🎧 듣는 중',
            'watching': '🎬 시청 중'
        }

        embed = discord.Embed(
            title="✨ 저스트봇 현재 상태",
            description=f"현재 저스트봇의 상태와 활동 정보입니다.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="상태", value=status_display_map.get(settings['status'], '알 수 없음'), inline=False)
        embed.add_field(name="활동", value=f"{activity_type_display_map.get(settings['activity_type'], '알 수 없음')}: {settings['activity_name']}", inline=False)
        embed.set_footer(text=f"최종 업데이트: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S')} (UTC)") # DeprecationWarning 수정

        if interaction: await interaction.followup.send(embed=embed)
        elif ctx: await ctx.send(embed=embed)

    async def _rename_channel_ai(self, channel: discord.TextChannel, 분석할텍스트: str, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """Gemini AI가 텍스트를 분석하여 채널명을 제안하고 변경합니다."""
        if interaction: await interaction.response.defer(ephemeral=True)

        if not self.gemini_model:
            response_msg = "❌ Gemini AI가 초기화되지 않았습니다. 관리자에게 문의하거나 `.env` 파일의 `GEMINI_API_KEY`를 확인하세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        if not (2 <= len(분석할텍스트) <= 100):
            response_msg = "❌ 분석할 텍스트는 2자 이상 100자 이하여야 합니다."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            return

        try:
            prompt = (
                f"다음 텍스트를 분석하여 Discord 채널에 적합한 짧고 간결한 영어/한글 채널명 1개를 제안해주세요. "
                f"채널명은 소문자와 하이픈(-)으로만 구성되어야 하며, 띄어쓰기는 하이픈으로 대체해주세요. "
                f"한글은 그대로 사용하고, 그 외 특수문자는 제거해주세요. "
                f"최대 길이는 30자 이내입니다. 예를 들어 '새로운 모험의 시작' -> 'new-adventure' 또는 '새로운-모험' 입니다. "
                f"채널명 외에 다른 설명은 일절 포함하지 마세요. "
                f"텍스트: '{분석할텍스트}'"
            )

            response = await asyncio.to_thread(lambda: self.gemini_model.generate_content(prompt)) # 비동기로 Gemini 호출
            suggested_name_raw = response.text.strip().lower()

            # AI가 제안한 채널명 정제 (하이픈, 한글, 영어 소문자, 숫자 외 모든 문자 제거)
            new_channel_name_chars = []
            for char in suggested_name_raw:
                if 'a' <= char <= 'z' or '0' <= char <= '9' or char == '-' or ('가' <= char <= '힣'):
                    new_channel_name_chars.append(char)
                elif char.isspace(): # 띄어쓰기는 하이픈으로
                    new_channel_name_chars.append('-')

            new_channel_name = "".join(new_channel_name_chars)
            new_channel_name = re.sub(r'-+', '-', new_channel_name) # 연속 하이픈 제거
            new_channel_name = new_channel_name.strip('-') # 시작/끝 하이픈 제거

            if not (2 <= len(new_channel_name) <= 100): # Discord 채널명 길이 제한 2-100자
                if len(new_channel_name) < 2:
                    response_msg = f"❌ AI가 제안한 채널명('{new_channel_name}')이 너무 짧습니다. 다른 텍스트를 시도해주세요."
                else:
                    response_msg = f"❌ AI가 제안한 채널명('{new_channel_name}')이 너무 깁니다. (최대 100자)"
                if interaction: await interaction.followup.send(response_msg, ephemeral=True)
                elif ctx: await ctx.send(response_msg)
                return

            if not new_channel_name: # 유효한 이름이 생성되지 않음
                response_msg = "❌ AI가 유효한 채널명을 제안하지 못했습니다. 다른 텍스트를 시도해주세요."
                if interaction: await interaction.followup.send(response_msg, ephemeral=True)
                elif ctx: await ctx.send(response_msg)
                return

            old_channel_name = channel.name
            await channel.edit(name=new_channel_name, reason=f"Gemini AI 제안 기반 채널명 변경: {분석할텍스트}")

            response_msg = f"✅ 채널 이름이 **`#{old_channel_name}`**에서 **`#{new_channel_name}`** (AI 제안)으로 변경되었습니다!"
            if interaction: await interaction.followup.send(response_msg, ephemeral=False)
            elif ctx: await ctx.send(response_msg)

        except genai.APIError as e:
            print(f"Gemini AI API 오류: {e}")
            response_msg = "❌ Gemini AI 서비스에 문제가 발생했습니다. 잠시 후 다시 시도해주세요."
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
        except Exception as e:
            print(f"채널명 변경 중 오류 발생: {e}")
            response_msg = f"❌ 채널명 변경 중 알 수 없는 오류가 발생했습니다: {e}"
            if interaction: await interaction.followup.send(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)

    async def _scan_blacklist_user(self, 유저: discord.Member, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """글로벌 블랙리스트에 등록된 악성 유저인지 스캔합니다."""
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        # 권한 확인 (관리자만 가능)
        permission_checker = (lambda u: u.guild_permissions.administrator)
        if not await self._check_authority(caller_obj, target_channel, "Administrator", permission_checker): return

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, reason FROM global_blacklist WHERE user_id = ?", (str(유저.id),))
        result = cursor.fetchone()
        conn.close()

        if result:
            response_msg = f"🚨 **{유저.display_name}**님은 글로벌 블랙리스트에 등록된 악성 유저입니다!\n사유: {result['reason']}"
            embed = discord.Embed(
                title="⚠️ 블랙리스트 스캔 결과",
                description=response_msg,
                color=discord.Color.red()
            )
            if interaction: await interaction.response.send_message(embed=embed, ephemeral=False)
            elif ctx: await ctx.send(embed=embed)
            elif channel_to_send: await channel_to_send.send(embed=embed)
        else:
            response_msg = f"✅ **{유저.display_name}**님은 글로벌 블랙리스트에 없습니다."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=False)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)

    async def _security_report(self, interaction: discord.Interaction = None, ctx: commands.Context = None, channel_to_send=None):
        """이 서버의 보안 설정 상태에 대한 리포트를 제공합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        target_channel = interaction.channel if interaction else ctx.channel if ctx else channel_to_send
        caller_obj = interaction if interaction else ctx.author

        # 권한 확인 (관리자만 가능)
        permission_checker = (lambda u: u.guild_permissions.administrator)
        if not await self._check_authority(caller_obj, target_channel, "Administrator", permission_checker): return

        server_config = self.bot.get_server_config(target_guild.id)
        if not server_config:
            response_msg = "❌ 이 서버에 저장된 봇 보안 설정이 없습니다. 기본 설정이 적용 중일 수 있습니다."
            if interaction: await interaction.response.send_message(response_msg, ephemeral=True)
            elif ctx: await ctx.send(response_msg)
            elif channel_to_send: await channel_to_send.send(response_msg)
            return

        invite_filter_status = "활성화 ✅" if server_config.get('invite_filter_enabled', 0) == 1 else "비활성화 ❌"
        spam_filter_status = "활성화 ✅" if server_config.get('spam_filter_enabled', 0) == 1 else "비활성화 ❌"
        spam_threshold = server_config.get('spam_threshold', 5)
        spam_time_window = server_config.get('spam_time_window', 10)

        embed = discord.Embed(
            title=f"🛡️ {target_guild.name} 서버 보안 리포트",
            description="현재 서버에 적용된 저스트봇 보안 설정입니다.",
            color=discord.Color.dark_teal()
        )
        embed.add_field(name="초대 링크 검열", value=invite_filter_status, inline=False)
        embed.add_field(name="도배 감지", value=spam_filter_status, inline=False)
        if server_config.get('spam_filter_enabled', 0) == 1:
            embed.add_field(name="└ 도배 기준", value=f"{spam_threshold} 메시지/{spam_time_window}초", inline=False)

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_warnings WHERE guild_id = ?", (str(target_guild.id),))
        total_warnings = cursor.fetchone()[0]
        embed.add_field(name="누적 경고 수", value=f"총 {total_warnings}회", inline=False)
        conn.close()

        if interaction: await interaction.response.send_message(embed=embed, ephemeral=False)
        elif ctx: await ctx.send(embed=embed)
        elif channel_to_send: await channel_to_send.send(embed=embed)

    async def _list_commands_report(self, guild: discord.Guild, channel: discord.TextChannel, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """이 채널에서 사용 가능한 명령어 목록을 보여줍니다."""
        if interaction: await interaction.response.defer(ephemeral=False)

        server_config = self.bot.get_server_config(guild.id)
        bank_channel_id = server_config.get('bank_channel_id')

        # 모든 명령어 이름 가져오기
        all_slash_commands = []
        for cmd in self.bot.tree.get_commands(guild=guild): # guild=guild로 해당 서버에 등록된 명령어만 가져옴
            all_slash_commands.append(cmd.qualified_name)

        all_message_commands = [cmd.name for cmd in self.bot.commands if cmd.enabled and cmd.hidden is False] # 메시지 기반 명령어는 ctx.bot.commands에서 가져옴

        commands_categorized = {
            "일반 명령어": [],
            "은행 명령어": [],
            "차량 명령어": [],
            "관리 명령어": [],
            "티켓 명령어": [],
            "음악 명령어": [],
            "게임 명령어": [],
            "보안 명령어": [],
            "설정 명령어": []
        }

        # 명령어들을 카테고리별로 분류하고, 채널 제한을 고려하여 표시
        for cmd_name in sorted(list(set(all_slash_commands + all_message_commands))): # 중복 제거 후 정렬
            is_slash = cmd_name in all_slash_commands
            is_msg = cmd_name in all_message_commands

            display_name = f"/{cmd_name}" if is_slash else f"{self.bot.command_prefix}{cmd_name}"

            # 명령어 활성화 상태 확인
            enabled = self.bot.is_command_enabled(guild.id, cmd_name)
            status_icon = "✅" if enabled else "❌"

            # 채널 제한 확인
            is_bank_command = cmd_name in ["통장개설", "잔액", "입금", "출금", "송금", "대출", "상환", "거래내역", "통장"]

            command_info = {
                "name": display_name,
                "status": status_icon,
                "available_in_this_channel": True # 일단 현재 채널에서 사용 가능하다고 가정
            }

            if is_bank_command:
                if bank_channel_id and str(channel.id) != bank_channel_id:
                    command_info["available_in_this_channel"] = False
                    commands_categorized["은행 명령어"].append(command_info)
                else:
                    commands_categorized["은행 명령어"].append(command_info)
            elif cmd_name in ["차량등록"]:
                commands_categorized["차량 명령어"].append(command_info)
            elif cmd_name in ["킥", "밴", "청소", "역할부여", "역할삭제", "경고", "경고조회", "경고삭제"]:
                commands_categorized["관리 명령어"].append(command_info)
            elif cmd_name in ["오픈", "닫기"] and "티켓" in cmd_name: # 티켓 그룹 명령어
                 commands_categorized["티켓 명령어"].append(command_info)
            elif cmd_name in ["들어와", "나가", "재생", "정지"]:
                commands_categorized["음악 명령어"].append(command_info)
            elif cmd_name in ["주사위", "가위바위보"]:
                commands_categorized["게임 명령어"].append(command_info)
            elif cmd_name in ["스캔블랙리스트", "보안리포트"]:
                commands_categorized["보안 명령어"].append(command_info)
            elif cmd_name in ["설정", "명령어"]: # 설정 그룹 명령어는 설정 코그에서 처리되므로 단순화
                commands_categorized["설정 명령어"].append(command_info)
            elif cmd_name in ["봇상태", "채널명변경"]: # 모더레이션 코그에 있으나 그룹에 속하지 않는 최상위 명령어
                commands_categorized["일반 명령어"].append(command_info)
            else:
                commands_categorized["일반 명령어"].append(command_info)

        embed = discord.Embed(
            title=f"📜 {guild.name} 서버 명령어 목록",
            description=f"현재 채널에서 사용 가능한 명령어입니다. (접두사: `{self.bot.command_prefix}`)\n",
            color=discord.Color.dark_blue()
        )

        for category, commands_in_category in commands_categorized.items():
            if commands_in_category:
                field_value = ""
                for cmd in commands_in_category:
                    if cmd["available_in_this_channel"]:
                        field_value += f"{cmd['status']} `{cmd['name']}`\n"
                    else:
                        field_value += f"🚫 `{cmd['name']}` (다른 채널 전용)\n"

                if field_value: # 필터링 후에도 내용이 있으면 필드 추가
                    embed.add_field(name=category, value=field_value, inline=True)

        embed.set_footer(text="❌: 비활성화됨, 🚫: 이 채널에서 사용 불가")

        if interaction: await interaction.followup.send(embed=embed)
        elif ctx: await ctx.send(embed=embed)