import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import sqlite3
import datetime
import google.generativeai as genai # Gemini AI 라이브러리 임포트

from discord import app_commands 

load_dotenv()

# --- SQLite 설정 ---
DB_FILE = "rp_server_data.db" 

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row 
    return conn

# 데이터베이스 초기화 (모든 봇의 테이블 생성)
def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 공통 테이블: 봇 상태
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            bot_name TEXT PRIMARY KEY,
            last_heartbeat TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            guild_count INTEGER NOT NULL
        )
    """)
    # 공통 테이블: 서버별 설정
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_configs (
            guild_id TEXT PRIMARY KEY,
            guild_name TEXT, 
            -- 일반 설정 General Settings --
            welcome_message_enabled INTEGER DEFAULT 0,
            welcome_message_text TEXT,
            leave_message_enabled INTEGER DEFAULT 0,
            leave_message_text TEXT,
            log_channel_id TEXT, 

            -- 차량 봇 설정 Car Bot Settings --
            car_registration_tax INTEGER DEFAULT 50000,
            car_forbidden_cars_json TEXT DEFAULT '["탱크", "전투기", "핵잠수함", "우주선"]', 
            registration_channel_id TEXT, 
            car_admin_channel_id TEXT,    
            car_admin_role_id TEXT,       
            approved_cars_channel_id TEXT, 

            -- 은행 봇 설정 Bank Bot Settings --
            bank_loan_enabled INTEGER DEFAULT 1, 
            bank_max_loan_amount INTEGER DEFAULT 1000000, 
            bank_loan_interest_rate REAL DEFAULT 0.032,
            bank_channel_id TEXT, -- <--- 추가: 은행 전용 채널 ID

            -- 모더레이션 봇 설정 Moderation Bot Settings --
            auto_kick_warn_count INTEGER DEFAULT 5, 
            mute_role_id TEXT, 

            -- 티켓 설정 Ticket Settings --
            ticket_open_channel_id TEXT,  
            ticket_category_id TEXT,      
            ticket_staff_role_id TEXT,

            -- 보안 설정 (새로 추가) --
            invite_filter_enabled INTEGER DEFAULT 0, -- 초대 링크 필터링 활성화 (0: 비활성화, 1: 활성화)
            spam_filter_enabled INTEGER DEFAULT 0,   -- 도배 감지 필터링 활성화 (0: 비활성화, 1: 활성화)
            spam_threshold INTEGER DEFAULT 5,        -- 도배로 간주할 메시지 개수
            spam_time_window INTEGER DEFAULT 10      -- 도배 감지 시간 범위 (초)
        )
    """)
    # 만약 guild_name 컬럼이 없는 경우 추가 (기존 DB 파일 호환성)
    try:
        cursor.execute("SELECT guild_name FROM server_configs LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE server_configs ADD COLUMN guild_name TEXT")
        print("✅ server_configs 테이블에 'guild_name' 컬럼을 추가했습니다.")

    # 보안 설정 관련 컬럼들이 없는 경우 추가 (DB 파일 호환성을 위해)
    cursor.execute("ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS invite_filter_enabled INTEGER DEFAULT 0")
    cursor.execute("ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS spam_filter_enabled INTEGER DEFAULT 0")
    cursor.execute("ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS spam_threshold INTEGER DEFAULT 5")
    cursor.execute("ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS spam_time_window INTEGER DEFAULT 10")
    cursor.execute("ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS bank_channel_id TEXT") # <--- 추가: 은행 채널 ID

    # 새로운 공통 테이블: 서버별 커맨드 활성화/비활성화 상태
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS server_command_states (
            guild_id TEXT NOT NULL,
            command_name TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1, -- 1 for enabled, 0 for disabled
            PRIMARY KEY (guild_id, command_name)
        )
    """)
    # 새로운 공통 테이블: 봇 현재 상태 및 활동 (슈퍼 관리자용)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_presence_settings (
            id INTEGER PRIMARY KEY DEFAULT 1, -- 항상 1개의 레코드만 가짐
            status TEXT DEFAULT 'online', -- online, idle, dnd, invisible
            activity_type TEXT DEFAULT 'playing', -- playing, streaming, listening, watching
            activity_name TEXT DEFAULT 'RP 서버 운영'
        )
    """)
    # 초기 봇 상태 설정이 없으면 기본값 삽입
    cursor.execute("INSERT OR IGNORE INTO bot_presence_settings (id, status, activity_type, activity_name) VALUES (1, 'online', 'playing', 'RP 서버 운영')")

    # 은행 계좌 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_accounts (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0
        )
    """)
    # 은행 거래 내역 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            type TEXT NOT NULL, -- 'deposit', 'withdrawal', 'transfer_out', 'transfer_in', 'loan_taken', 'loan_repaid'
            amount INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            related_user_id TEXT,
            related_username TEXT,
            description TEXT
        )
    """)
    # 차량 등록 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS car_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            car_name TEXT NOT NULL,
            registration_tax INTEGER NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            guild_id TEXT,
            channel_id TEXT,
            approved_by TEXT,
            approved_at TEXT,
            rejected_by TEXT,
            rejected_at TEXT,
            rejection_reason TEXT,
            timed_out_at TEXT
        )
    """)
    # 사용자 경고 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            reason TEXT NOT NULL,
            moderator_id TEXT NOT NULL,
            moderator_name TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    # 게임 통계 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_type TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            sides INTEGER,
            result TEXT,
            user_choice TEXT,
            bot_choice TEXT,
            timestamp TEXT NOT NULL
        )
    """)
    # 보험 관련 테이블 (모두 제거됨)
    cursor.execute("""
        DROP TABLE IF EXISTS insurance_policies
    """)
    cursor.execute("""
        DROP TABLE IF EXISTS insurance_claims
    """)
    cursor.execute("""
        DROP TABLE IF EXISTS insurance_blackbox_reports
    """)

    # 티켓 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            status TEXT NOT NULL, -- open, closed, claimed, archived
            reason TEXT,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            closed_by TEXT
        )
    """)
    # 대출 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            loan_amount INTEGER NOT NULL,
            interest_rate REAL NOT NULL,
            total_repay_amount INTEGER NOT NULL,
            paid_amount INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL, -- active, paid, overdue
            loan_date TEXT NOT NULL,
            due_date TEXT
        )
    """)
    # 대출 상환 내역 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loan_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            payment_amount INTEGER NOT NULL,
            payment_date TEXT NOT NULL,
            FOREIGN KEY (loan_id) REFERENCES loans(id)
        )
    """)

    # 악성 사용자 블랙리스트 테이블 (개념적인 구현)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_blacklist (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            reason TEXT,
            added_by TEXT,
            added_at TEXT
        )
    """)
    # 테스트용 블랙리스트 사용자 추가 (예시)
    cursor.execute("INSERT OR IGNORE INTO global_blacklist (user_id, username, reason, added_by, added_at) VALUES ('123456789012345678', '테스트악성유저', '자동화 도배 봇', 'system', datetime('now'))")
    cursor.execute("INSERT OR IGNORE INTO global_blacklist (user_id, username, reason, added_by, added_at) VALUES ('987654321098765432', '광고용계정', '스팸 광고', 'system', datetime('now'))")


    conn.commit()
    conn.close()
    print(f"✅ 저스트봇: SQLite 데이터베이스 '{DB_FILE}' 초기화 완료!")

# 서버별 설정 불러오는 헬퍼 함수
def get_server_config(guild_id):
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM server_configs WHERE guild_id = ?", (str(guild_id),))
    config = cursor.fetchone()
    conn.close()
    return config

# 서버별 설정 업데이트/삽입 헬퍼 함수
def set_server_config(guild_id, config_name, config_value):
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute(f"""
        INSERT INTO server_configs (guild_id, {config_name}) VALUES (?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET {config_name} = EXCLUDED.{config_name}
    """, (str(guild_id), str(config_value)))
    conn.commit()
    conn.close()

# 특정 명령어의 활성화 상태를 확인하는 헬퍼 함수
def is_command_enabled(guild_id: int, command_name: str) -> bool:
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute("SELECT is_enabled FROM server_command_states WHERE guild_id = ? AND command_name = ?", (str(guild_id), command_name))
    result = cursor.fetchone()
    conn.close()
    return result[0] == 1 if result else True # 기본적으로 활성화 (설정 없으면 켜진 상태)

# 명령어 활성화 상태를 업데이트하는 헬퍼 함수
def set_command_enabled_state(guild_id: int, command_name: str, is_enabled: bool):
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    enabled_val = 1 if is_enabled else 0
    cursor.execute("""
        INSERT INTO server_command_states (guild_id, command_name, is_enabled)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, command_name) DO UPDATE SET is_enabled = EXCLUDED.is_enabled
    """, (str(guild_id), command_name, enabled_val))
    conn.commit()
    conn.close()

# 봇 상태 및 활동 설정 불러오기
def get_bot_presence_settings():
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute("SELECT status, activity_type, activity_name FROM bot_presence_settings WHERE id = 1")
    settings = cursor.fetchone()
    conn.close()
    return settings if settings else {'status': 'online', 'activity_type': 'playing', 'activity_name': 'RP 서버 운영'} # 기본값

# 봇 상태 및 활동 설정 업데이트
def set_bot_presence_settings(status, activity_type, activity_name):
    conn = sqlite3.connect(DB_FILE) # 헬퍼 함수 내에서 직접 연결/종료
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO bot_presence_settings (id, status, activity_type, activity_name)
        VALUES (1, ?, ?, ?)
    """, (status, activity_type, activity_name))
    conn.commit()
    conn.close()

initialize_db()

# Gemini AI 초기화
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Gemini AI 설정 완료.")
else:
    print("❌ GEMINI_API_KEY가 설정되지 않았습니다. Gemini AI 기능을 사용할 수 없습니다.")

intents = discord.Intents.all()
intents.message_content = True # 메시지 내용 읽기 권한 활성화

# 봇 접두사 변경 (저스트!)
bot = commands.Bot(command_prefix='저스트 ', intents=intents) 

BOT_NAME = "저스트봇" 
BOT_TOKEN = os.getenv("BOT_TOKEN")

@tasks.loop(minutes=1)
async def record_bot_status():
    conn = get_db_connection()
    cursor = conn.cursor()
    status_info = {
        "bot_name": BOT_NAME,
        "last_heartbeat": datetime.datetime.now(datetime.UTC).isoformat(), 
        "status": "Online",
        "message": "정상 작동 중",
        "guild_count": len(bot.guilds) if bot.guilds else 0
    }
    cursor.execute("""
        INSERT OR REPLACE INTO bot_status (bot_name, last_heartbeat, status, message, guild_count)
        VALUES (?, ?, ?, ?, ?)
    """, (status_info["bot_name"], status_info["last_heartbeat"], status_info["status"], status_info["message"], status_info["guild_count"]))
    conn.commit()
    conn.close()

# 봇 상태 업데이트 작업
@tasks.loop(minutes=5) # 5분마다 봇 상태 업데이트
async def update_bot_presence():
    settings = get_bot_presence_settings()
    if not settings: return # 설정 없으면 아무것도 안 함

    status_map = {
        'online': discord.Status.online,
        'idle': discord.Status.idle,
        'dnd': discord.Status.dnd,
        'invisible': discord.Status.invisible
    }
    activity_type_map = {
        'playing': discord.ActivityType.playing,
        'listening': discord.ActivityType.listening,
        'watching': discord.ActivityType.watching,
        'streaming': discord.ActivityType.streaming # streaming은 URL이 필요할 수 있으므로 주의
    }

    discord_status = status_map.get(settings['status'], discord.Status.online)
    discord_activity_type = activity_type_map.get(settings['activity_type'], discord.ActivityType.playing)

    activity = discord.Activity(type=discord_activity_type, name=settings['activity_name'])

    await bot.change_presence(status=discord_status, activity=activity)
    print(f"✅ 봇 상태 업데이트 완료: 상태={settings['status']}, 활동={settings['activity_type']} {settings['activity_name']}")


@bot.event
async def on_ready():
    print(f'🚀 {bot.user.name} 봇 준비 완료! 모든 기능 야무지게 시작합니다.')
    try:
        # 슬래시 커맨드 동기화: 글로벌 동기화 (모든 서버에 반영, 시간이 오래 걸림)
        await bot.tree.sync() # guild 인자를 제거하여 글로벌 동기화
        print(f"✅ 슬래시 커맨드 동기화 완료! (글로벌)")
    except Exception as e:
        print(f"❌ 슬래시 커맨드 동기화 실패: {e}")
    record_bot_status.start()
    update_bot_presence.start() # 봇 상태 업데이트 작업 시작

    # Cogs 로드 시 필요한 함수들을 bot 객체에 직접 할당
    bot.get_server_config = get_server_config
    bot.set_server_config = set_server_config
    bot.get_db_connection = get_db_connection
    bot.is_command_enabled = is_command_enabled
    bot.set_command_enabled_state = set_command_enabled_state
    bot.get_bot_presence_settings = get_bot_presence_settings # 대시보드에서 불러올 함수
    bot.set_bot_presence_settings = set_bot_presence_settings # 대시보드에서 업데이트할 함수

    # Gemini AI 모델도 bot 객체에 저장 (Gemini AI 키가 있다면)
    if GEMINI_API_KEY:
        try:
            bot.gemini_model = genai.GenerativeModel('gemini-pro')
            print("✅ 'gemini-pro' 모델 로드 완료.")
        except Exception as e:
            print(f"❌ Gemini 모델 로드 실패: {e}")
            bot.gemini_model = None
    else:
        bot.gemini_model = None

    cogs_to_load = [
        "cogs.bank", 
        "cogs.car", 
        "cogs.moderation", 
        "cogs.music", 
        "cogs.game", 
    ]
    for cog in cogs_to_load:
        try:
            await bot.load_extension(cog)
            print(f"로드 성공: {cog}")
        except Exception as e:
            print(f"로드 실패: {cog} - {e}")

    # 봇이 켜질 때 guild_name이 없는 server_configs 항목을 채워 넣기
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_id FROM server_configs WHERE guild_name IS NULL")
    guild_ids_without_name = cursor.fetchall()

    for guild_row in guild_ids_without_name:
        guild_id = int(guild_row['guild_id'])
        guild = bot.get_guild(guild_id) # Discord API를 통해 길드 객체 가져오기
        if guild:
            cursor.execute("UPDATE server_configs SET guild_name = ? WHERE guild_id = ?", (guild.name, str(guild_id)))
            print(f"✅ 서버 ID {guild_id}의 이름 '{guild.name}'을(를) DB에 업데이트했습니다.")
        else:
            print(f"⚠️ 봇이 길드 {guild_id}에 접근할 수 없습니다. 길드가 존재하지 않거나 봇이 서버에 없습니다.")
    conn.commit()
    conn.close()


@bot.event
async def on_message(message):
    # 봇이 보낸 메시지 또는 DM은 처리하지 않음
    if message.author == bot.user or not message.guild:
        return

    # bot.process_commands(message)는 각 코그의 on_message 리스너를 호출한 다음
    # 해당 메시지에 대한 command (메시지 기반 명령어)를 찾아서 실행합니다.
    await bot.process_commands(message)


# 모든 명령어에 대한 전역 체크를 on_interaction 이벤트 리스너로 처리합니다.
@bot.event
async def on_interaction(interaction: discord.Interaction):
    # 상호작용이 애플리케이션 명령(슬래시 커맨드)이고 길드(서버)에서 발생했을 때만 체크
    if interaction.type == discord.InteractionType.application_command and interaction.guild:
        # 그룹 명령어와 서브 명령어 모두 처리 (풀 커맨드 이름 생성)
        command_name_parts = [interaction.command.name]
        if interaction.command.parent: # 서브그룹이 있을 경우
            command_name_parts.insert(0, interaction.command.parent.name)
            if interaction.command.parent.parent: # 최상위 그룹이 있을 경우
                command_name_parts.insert(0, interaction.command.parent.parent.name)
        full_command_name = " ".join(command_name_parts)

        # is_command_enabled 함수를 사용하여 명령어 활성화 상태 확인
        if not is_command_enabled(interaction.guild.id, full_command_name):
            await interaction.response.send_message(f"❌ 이 명령어 (`/{full_command_name}`)는 현재 이 서버에서 비활성화되어 있습니다.", ephemeral=True)
            return # 여기서 함수의 실행을 중단합니다.

    # 상호작용이 애플리케이션 명령이 아니거나 활성화된 명령이라면, Discord.py의 기본 처리 흐름을 따릅니다.
    await bot.process_commands(interaction)


# 에러 핸들러
@bot.tree.error
async def on_app_command_error_global(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if interaction.response.is_done(): # 이미 응답이 전송되었다면 (예: 명령어 비활성화 메시지)
        print(f"오류 발생 (이미 응답 전송됨): {error}")
        return

    if isinstance(error, app_commands.CommandInvokeError):
        # Commands.CheckFailure는 on_interaction에서 이미 처리하고 응답을 보냈으므로, 여기로 오지 않습니다.
        # 따라서 CommandInvokeError는 다른 종류의 예외로 인한 것입니다.
        print(f"전역 오류 발생: {error.original}") # 실제 예외 로깅
        await interaction.response.send_message(f"오류가 발생했습니다: {error.original}", ephemeral=True) # 사용자에게는 원본 예외 전달

    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다. 관리자(Administrator) 권한이 필요합니다.", ephemeral=True)
    elif isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"❌ 이 명령어는 쿨타임 중입니다. {error.retry_after:.2f}초 후에 다시 시도해주세요.", ephemeral=True)
    else:
        print(f"알 수 없는 전역 오류: {error}")
        await interaction.response.send_message(f"알 수 없는 오류가 발생했습니다: {error}", ephemeral=True)

try:
    bot.run(BOT_TOKEN)
except discord.LoginFailure:
    print("❌ 봇 토큰이 올바르지 않거나 비어있습니다. 토큰을 확인해주세요!")
except Exception as e:
    print(f"❌ 봇 실행 중 예상치 못한 오류가 발생했습니다: {e}")