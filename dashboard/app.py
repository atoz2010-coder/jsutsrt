from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
import sqlite3
import datetime
import requests # Discord OAuth2 통신용
import json # JSON 처리용 (managed_guild_ids_json)

load_dotenv()

# --- Flask 앱 설정 ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "your_flask_secret_key_for_dashboard")

# --- Flask-Login 설정 ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- SQLite 설정 ---
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rp_server_data.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# --- Discord OAuth2 설정 ---
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
# TODO: 배포 시 이 값을 실제 도메인으로 변경해야 합니다. (예: "https://dashjbot.infy.uk/callback")
# Replit 테스트 시에는 현재 웹뷰 주소 + /callback 으로 변경해야 합니다.
DISCORD_REDIRECT_URI = "https://35fbbcbf-98b0-4e0b-8468-1e7aa0c22e46-00-80500zghanlt.pike.replit.dev:8008/callback" 
DISCORD_API_BASE_URL = "https://discord.com/api/v10"

# --- 사용자 모델 (Flask-Login용) ---
class User(UserMixin):
    def __init__(self, user_id, username, is_discord_user=False, managed_guild_ids=None):
        self.id = user_id
        self.username = username
        self.is_discord_user = is_discord_user 
        self.managed_guild_ids = managed_guild_ids if managed_guild_ids is not None else [] 

    @staticmethod
    def get(user_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, is_discord_user, managed_guild_ids_json FROM dashboard_users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        conn.close()
        if user_data:
            managed_guild_ids = []
            if user_data['managed_guild_ids_json']:
                managed_guild_ids = json.loads(user_data['managed_guild_ids_json'])

            return User(str(user_data["id"]), user_data["username"], bool(user_data['is_discord_user']), managed_guild_ids)
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- 초기 관리자 계정 생성 및 DB 초기화 ---
def initialize_dashboard_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 대시보드 사용자 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT, 
            is_discord_user INTEGER NOT NULL DEFAULT 0, 
            discord_user_id TEXT UNIQUE, 
            managed_guild_ids_json TEXT 
        )
    """)
    conn.commit()

    admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME", "admin")
    admin_password = os.getenv("DASHBOARD_ADMIN_PASSWORD", "your_strong_admin_password")

    cursor.execute("SELECT * FROM dashboard_users WHERE username = ?", (admin_username,))
    if not cursor.fetchone():
        hashed_password = generate_password_hash(admin_password)
        cursor.execute("INSERT INTO dashboard_users (username, password, is_discord_user) VALUES (?, ?, ?)", (admin_username, hashed_password, 0))
        conn.commit()
        print(f"✅ 초기 관리자 계정 '{admin_username}' 생성 완료!")
    else:
        print(f"✅ 관리자 계정 '{admin_username}' 이미 존재합니다.")
    conn.close()

# --- 헬퍼 함수 ---
def get_all_managed_guild_info():
    """DB에 저장된 모든 서버 정보를 가져와 대시보드용으로 가공합니다."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_id, guild_name FROM server_configs")
    all_guilds_in_db = cursor.fetchall()
    conn.close()

    managed_guilds_data = []
    # Discord API를 통해 길드 아이콘 URL을 가져오려면 bot process와 통신이 필요.
    # Flask 앱에서는 직접 불가능하므로, 기본 아이콘 또는 추후 구현 (Discord API 통신 모듈 분리 등)
    # 현재는 guild_name만 사용. guild_icon은 추후 Discord API 연동이 되면 추가할 수 있습니다.

    # 사용자가 관리하는 길드만 필터링 (current_user 사용)
    if current_user.is_authenticated:
        dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME")
        if current_user.username == dashboard_admin_username: # 슈퍼 관리자
            # 모든 서버 보여주기
            for row in all_guilds_in_db:
                managed_guilds_data.append({
                    "id": row['guild_id'], 
                    "name": row['guild_name'] if row['guild_name'] else f"서버 ID: {row['guild_id']}",
                    "icon_url": None # Placeholder
                })
        elif current_user.is_discord_user: # Discord 사용자
            for guild_id in current_user.managed_guild_ids:
                for row in all_guilds_in_db:
                    if row['guild_id'] == guild_id:
                        managed_guilds_data.append({
                            "id": row['guild_id'], 
                            "name": row['guild_name'] if row['guild_name'] else f"서버 ID: {row['guild_id']}",
                            "icon_url": None # Placeholder
                        })
                        break
    return managed_guilds_data

# --- 라우트 정의 ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('select_server')) # 로그인 후 서버 선택 화면으로 이동

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # 일반 로그인 처리
        if username and password:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password FROM dashboard_users WHERE username = ? AND is_discord_user = 0", (username,))
            user_data = cursor.fetchone()
            conn.close()

            if user_data and user_data['password'] and check_password_hash(user_data['password'], password):
                user = User(str(user_data['id']), user_data['username']) 
                login_user(user)
                return redirect(url_for('select_server')) # 로그인 후 서버 선택 화면으로 이동
            else:
                flash('유효하지 않은 사용자 이름 또는 비밀번호입니다.')
        else:
            flash('사용자 이름과 비밀번호를 입력해주세요.')

    # Discord OAuth2 로그인 URL
    discord_oauth_url = (
        f"{DISCORD_API_BASE_URL}/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
    )
    return render_template('login.html', discord_oauth_url=discord_oauth_url)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        flash('Discord 인증 코드를 받지 못했습니다.', 'error')
        return redirect(url_for('login'))

    # Access Token 교환
    token_url = f"{DISCORD_API_BASE_URL}/oauth2/token"
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'scope': 'identify guilds'
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    response = requests.post(token_url, data=data, headers=headers)
    token_info = response.json()

    if 'access_token' not in token_info:
        flash(f"액세스 토큰 획득 실패: {token_info.get('error_description', '알 수 없는 오류')}", 'error')
        return redirect(url_for('login'))

    access_token = token_info['access_token']
    token_type = token_info['token_type']

    # User Information
    user_info_url = f"{DISCORD_API_BASE_URL}/users/@me"
    headers = {
        'Authorization': f'{token_type} {access_token}'
    }
    user_response = requests.get(user_info_url, headers=headers)
    discord_user_data = user_response.json()

    if 'id' not in discord_user_data:
        flash('Discord 사용자 정보를 가져오지 못했습니다.', 'error')
        return redirect(url_for('login'))

    discord_user_id = discord_user_data['id']
    discord_username = discord_user_data['username'] 

    # Get User's Guilds (봇이 들어가 있고, 사용자가 관리자 권한을 가진 길드)
    guilds_url = f"{DISCORD_API_BASE_URL}/users/@me/guilds"
    guilds_response = requests.get(guilds_url, headers=headers)
    discord_user_guilds = guilds_response.json()

    managed_guild_ids = []
    conn = get_db_connection()
    cursor = conn.cursor()

    # 봇이 데이터를 가지고 있는 모든 서버 목록 (server_configs에 저장된 서버들)
    cursor.execute("SELECT guild_id FROM server_configs")
    bot_managed_guilds_in_db = [row['guild_id'] for row in cursor.fetchall()]

    for guild_data in discord_user_guilds:
        # Check if the user has Administrator permission in this guild
        if (int(guild_data['permissions']) & 8) == 8: 
            if guild_data['id'] in bot_managed_guilds_in_db:
                managed_guild_ids.append(guild_data['id'])

    # 사용자 정보를 DB에 저장 또는 업데이트
    managed_guild_ids_json = json.dumps(managed_guild_ids)

    cursor.execute("SELECT id FROM dashboard_users WHERE discord_user_id = ?", (discord_user_id,))
    existing_user = cursor.fetchone()

    if existing_user:
        cursor.execute("""
            UPDATE dashboard_users SET username = ?, is_discord_user = ?, managed_guild_ids_json = ?, password = NULL
            WHERE id = ?
        """, (discord_username, 1, managed_guild_ids_json, existing_user['id']))
        user_id_for_login = existing_user['id']
    else:
        cursor.execute("""
            INSERT INTO dashboard_users (username, is_discord_user, discord_user_id, managed_guild_ids_json)
            VALUES (?, ?, ?, ?)
        """, (discord_username, 1, discord_user_id, managed_guild_ids_json))
        user_id_for_login = cursor.lastrowid # 새로 생성된 ID
    conn.commit()
    conn.close()

    user = User(str(user_id_for_login), discord_username, is_discord_user=True, managed_guild_ids=managed_guild_ids)
    login_user(user)

    # 봇이 추가된 관리 서버가 없는 경우, 대시보드가 아닌 로그인 페이지로 리다이렉트
    if not managed_guild_ids:
        flash("저스트봇이 초대된 서버가 없거나, 관리 권한이 있는 서버가 없습니다. 봇을 서버에 추가해주세요.", "warning")
        return redirect(url_for('login')) 

    return redirect(url_for('select_server')) # 서버 선택 화면으로 이동

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@app.route('/servers') # 루트 경로를 서버 선택 화면으로
@login_required
def select_server():
    managed_guilds_data = get_all_managed_guild_info()
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME")

    # 서버가 하나도 없으면 메시지 표시 (이미 callback에서 처리되지만 혹시 모를 상황)
    if not managed_guilds_data:
        flash("저스트봇이 초대된 서버가 없거나, 관리 권한이 있는 서버가 없습니다. 봇을 서버에 추가해주세요.", "warning")

    # render_template에 dashboard_admin_username을 명시적으로 전달
    return render_template('server_selection.html', guilds=managed_guilds_data, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>')
@login_required
def dashboard(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME")

    # 유저가 해당 guild_id를 관리할 권한이 있는지 다시 확인
    if current_user.username != dashboard_admin_username: # 슈퍼관리자 통과
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    # 길드 이름 가져오기
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()

    guild_name = guild_data['guild_name'] if guild_data and guild_data['guild_name'] else f"서버 ID: {guild_id}"

    # 봇 상태 정보 (대시보드 메인 페이지용)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bot_status")
    raw_bot_statuses = cursor.fetchall()
    conn.close()

    bot_statuses = []
    for status_row in raw_bot_statuses:
        status = dict(status_row)
        last_heartbeat_utc = datetime.datetime.fromisoformat(status['last_heartbeat'])
        status['last_heartbeat_kst'] = (last_heartbeat_utc + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M:%S')
        # 상태 오프라인 감지
        if datetime.datetime.now(datetime.UTC) - last_heartbeat_utc > datetime.timedelta(minutes=2): # UTC
            status['status'] = "Offline"
            status['message'] = "하트비트 없음"
        bot_statuses.append(status)

    # 렌더링할 때 선택된 길드 ID와 이름, 봇 상태 등을 전달
    return render_template(
        'dashboard.html', 
        guild_id=guild_id, 
        guild_name=guild_name, 
        bot_statuses=bot_statuses,
        dashboard_admin_username=dashboard_admin_username # os.getenv 오류 수정
    )


# Helper function to filter data based on user's managed guilds (used by bank, mod, car, game routes)
def get_filtered_data(table_name, order_by_column, guild_filter_column=None, user_id_filter_column=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    sql_query = f"SELECT * FROM {table_name}"
    sql_params = []
    where_clauses = []

    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username: # 슈퍼 관리자 아니면 필터링
        if current_user.is_discord_user and current_user.managed_guild_ids and guild_filter_column:
            placeholders = ','.join('?' * len(current_user.managed_guild_ids))
            where_clauses.append(f"{guild_filter_column} IN ({placeholders})")
            sql_params.extend(current_user.managed_guild_ids)
        elif current_user.is_discord_user and user_id_filter_column: 
            discord_user_db_id = None
            cursor.execute("SELECT discord_user_id FROM dashboard_users WHERE id = ? AND is_discord_user = 1", (current_user.id,))
            result = cursor.fetchone()
            if result:
                discord_user_db_id = result['discord_user_id']
                where_clauses.append(f"{user_id_filter_column} = ?")
                sql_params.append(discord_user_db_id)
            else: 
                conn.close()
                return []
        else: # Discord 사용자지만 관리하는 길드 없거나 필터링 기준 없으면 데이터 없음
            conn.close()
            return []

    if where_clauses:
        sql_query += " WHERE " + " AND ".join(where_clauses)

    sql_query += f" ORDER BY {order_by_column} DESC"

    cursor.execute(sql_query, sql_params)
    data = cursor.fetchall()
    conn.close()
    return data


@app.route('/dashboard/<guild_id>/bank')
@login_required
def bank_data(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    bank_accounts = get_filtered_data('bank_accounts', 'username', user_id_filter_column='user_id') # user_id로 필터링
    loans = get_filtered_data('loans', 'loan_date', user_id_filter_column='user_id') # user_id로 필터링

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"


    return render_template('bank.html', guild_id=guild_id, guild_name=guild_name, bank_accounts=bank_accounts, loans=loans, timedelta=datetime.datetime, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>/moderation')
@login_required
def moderation_data(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    warnings = get_filtered_data('user_warnings', 'timestamp', guild_filter_column='guild_id') # guild_id로 필터링
    tickets = get_filtered_data('tickets', 'opened_at', guild_filter_column='guild_id') # guild_id로 필터링

    warnings_by_user = {}
    for warning in warnings:
        warning_dict = dict(warning)
        if warning_dict['user_id'] not in warnings_by_user:
            warnings_by_user[warning_dict['user_id']] = {
                "user_id": warning_dict['user_id'],
                "username": warning_dict['username'],
                "warnings": []
            }
        warnings_by_user[warning_dict['user_id']]["warnings"].append({
            "reason": warning_dict['reason'],
            "moderator_name": warning_dict['moderator_name'],
            "timestamp": datetime.datetime.fromisoformat(warning_dict['timestamp'])
        })

    warnings_list = list(warnings_by_user.values())

    processed_tickets = []
    for ticket in tickets:
        ticket_dict = dict(ticket)
        ticket_dict['opened_at'] = datetime.datetime.fromisoformat(ticket_dict['opened_at'])
        if ticket_dict['closed_at']:
            ticket_dict['closed_at'] = datetime.datetime.fromisoformat(ticket_dict['closed_at'])
        processed_tickets.append(ticket_dict)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"

    return render_template('moderation.html', guild_id=guild_id, guild_name=guild_name, warnings=warnings_list, tickets=processed_tickets, timedelta=datetime.datetime, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>/car')
@login_required
def car_data(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    cars = get_filtered_data('car_registrations', 'requested_at', guild_filter_column='guild_id') # guild_id로 필터링

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"

    return render_template('car.html', guild_id=guild_id, guild_name=guild_name, cars=cars, timedelta=datetime.datetime, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>/insurance')
@login_required
def insurance_data(guild_id): # 현재 보험 기능은 없으므로 Placeholder
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"

    return render_template('insurance.html', guild_id=guild_id, guild_name=guild_name, policies=[], claims=[], blackbox_reports=[], timedelta=datetime.datetime, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>/game')
@login_required
def game_data(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    games = get_filtered_data('game_stats', 'timestamp', user_id_filter_column='user_id') # user_id로 필터링

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    conn.close()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"

    return render_template('game.html', guild_id=guild_id, guild_name=guild_name, game_stats=games, timedelta=datetime.datetime, dashboard_admin_username=dashboard_admin_username)

# --- 봇 상태 및 활동 설정 API 엔드포인트 (슈퍼 관리자만 접근 가능) ---
@app.route('/api/bot_presence', methods=['GET', 'POST'])
@login_required
def bot_presence_api():
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username != dashboard_admin_username:
        return {"error": "권한이 없습니다."}, 403

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'GET':
        cursor.execute("SELECT status, activity_type, activity_name FROM bot_presence_settings WHERE id = 1")
        settings = cursor.fetchone()
        conn.close()
        if settings:
            return dict(settings)
        else:
            return {'status': 'online', 'activity_type': 'playing', 'activity_name': 'RP 서버 운영'} # 기본값
    elif request.method == 'POST':
        data = request.json
        status = data.get('status')
        activity_type = data.get('activity_type')
        activity_name = data.get('activity_name')

        if status and activity_type is not None and activity_name is not None:
            conn_for_bot_presence = get_db_connection() # DB 연결 새로 열기
            cursor_for_bot_presence = conn_for_bot_presence.cursor()
            cursor_for_bot_presence.execute("""
                INSERT OR REPLACE INTO bot_presence_settings (id, status, activity_type, activity_name)
                VALUES (1, ?, ?, ?)
            """, (status, activity_type, activity_name))
            conn_for_bot_presence.commit()
            conn_for_bot_presence.close()
            return {"message": "봇 상태 설정이 성공적으로 업데이트되었습니다. 몇 분 내로 봇에 반영됩니다."}, 200
        else:
            conn.close()
            return {"error": "필수 필드가 누락되었습니다."}, 400


# --- 새로운 설정 페이지 라우트 ---
@app.route('/dashboard/<guild_id>/settings')
@login_required
def settings_list(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    # 유저가 해당 guild_id를 관리할 권한이 있는지 다시 확인
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 길드 이름 가져오기
    cursor.execute("SELECT guild_name FROM server_configs WHERE guild_id = ?", (guild_id,))
    guild_data = cursor.fetchone()
    guild_name = guild_data['guild_name'] if guild_data else f"서버 ID: {guild_id}"

    # 모든 설정 필드 (server_configs 테이블의 컬럼 이름과 일치해야 함)
    # config_fields 정의
    config_fields = [
        # General Settings
        {'name': 'welcome_message_enabled', 'type': 'checkbox', 'label': '환영 메시지 활성화', 'section': 'general'},
        {'name': 'welcome_message_text', 'type': 'textarea', 'label': '환영 메시지 텍스트', 'section': 'general'},
        {'name': 'leave_message_enabled', 'type': 'checkbox', 'label': '퇴장 메시지 활성화', 'section': 'general'},
        {'name': 'leave_message_text', 'type': 'textarea', 'label': '퇴장 메시지 텍스트', 'section': 'general'},
        {'name': 'log_channel_id', 'type': 'text', 'label': '로그 채널 ID', 'section': 'general'},
        # Car Bot Settings
        {'name': 'car_registration_tax', 'type': 'number', 'label': '차량 등록세', 'section': 'car'},
        {'name': 'car_forbidden_cars_json', 'type': 'text', 'label': '금지 차량 (JSON Array)', 'section': 'car'},
        {'name': 'registration_channel_id', 'type': 'text', 'label': '차량 등록 채널 ID', 'section': 'car'},
        {'name': 'car_admin_channel_id', 'type': 'text', 'label': '차량 관리 채널 ID', 'section': 'car'},
        {'name': 'car_admin_role_id', 'type': 'text', 'label': '차량 관리 역할 ID', 'section': 'car'},
        {'name': 'approved_cars_channel_id', 'type': 'text', 'label': '승인 차량 채널 ID', 'section': 'car'},
        # Bank Bot Settings
        {'name': 'bank_loan_enabled', 'type': 'checkbox', 'label': '은행 대출 기능 활성화', 'section': 'bank'},
        {'name': 'bank_max_loan_amount', 'type': 'number', 'label': '은행 최대 대출 금액', 'section': 'bank'},
        {'name': 'bank_loan_interest_rate', 'type': 'number', 'step': '0.001', 'label': '은행 대출 이자율 (연 이자)', 'section': 'bank'},
        {'name': 'bank_channel_id', 'type': 'text', 'label': '은행 채널 ID', 'section': 'bank'}, # <-- 은행 채널 추가
        # Moderation Bot Settings
        {'name': 'auto_kick_warn_count', 'type': 'number', 'label': '자동 강퇴 경고 횟수', 'section': 'moderation'},
        {'name': 'mute_role_id', 'type': 'text', 'label': '뮤트 역할 ID', 'section': 'moderation'},
        # Security Settings (Modertation에 포함)
        {'name': 'invite_filter_enabled', 'type': 'checkbox', 'label': '초대 링크 검열 활성화', 'section': 'security'},
        {'name': 'spam_filter_enabled', 'type': 'checkbox', 'label': '도배 감지 활성화', 'section': 'security'},
        {'name': 'spam_threshold', 'type': 'number', 'label': '도배 기준 (메시지 개수)', 'section': 'security'},
        {'name': 'spam_time_window', 'type': 'number', 'label': '도배 시간 범위 (초)', 'section': 'security'},
        # Ticket Settings
        {'name': 'ticket_open_channel_id', 'type': 'text', 'label': '티켓 개설 채널 ID', 'section': 'ticket'},
        {'name': 'ticket_category_id', 'type': 'text', 'label': '티켓 카테고리 ID', 'section': 'ticket'},
        {'name': 'ticket_staff_role_id', 'type': 'text', 'label': '티켓 스태프 역할 ID', 'section': 'ticket'}
    ]

    # 모든 앱 명령어 목록 (슬래시 커맨드 이름 기준)
    all_commands = [
        "통장개설", "잔액", "입금", "출금", "송금", "대출", "상환", "거래내역",
        "차량등록",
        "킥", "밴", "청소", "역할부여", "역할삭제", "경고", "경고조회", "경고삭제",
        "티켓 오픈", "티켓 닫기",
        "들어와", "나가", "재생", "정지",
        "주사위", "가위바위보",
        "채널명변경", "스캔블랙리스트", "보안리포트", "명령어리스트" # 새 명령어
    ]

    # 봇 상태 설정 불러오기 (슈퍼 관리자용)
    bot_presence_settings = None
    if current_user.username == dashboard_admin_username:
        bot_presence_settings = get_bot_presence_settings()
        if not bot_presence_settings:
            bot_presence_settings = {'status': 'online', 'activity_type': 'playing', 'activity_name': 'RP 서버 운영'}

    # 현재 서버의 설정 로드
    cursor.execute("SELECT * FROM server_configs WHERE guild_id = ?", (guild_id,))
    current_settings = cursor.fetchone()
    settings_dict = {}
    if current_settings:
        settings_dict = dict(current_settings) 

    # 명령어 활성화 상태 로드
    command_states_db = {}
    cursor.execute("SELECT command_name, is_enabled FROM server_command_states WHERE guild_id = ?", (guild_id,))
    for row in cursor.fetchall():
        command_states_db[row['command_name']] = row['is_enabled'] == 1
    conn.close() # DB 연결 닫기

    commands_with_states = []
    for cmd in all_commands:
        commands_with_states.append({
            'name': cmd,
            'enabled': command_states_db.get(cmd, True) # DB에 없으면 True (기본 활성화)
        })

    # 섹션별로 필드를 그룹화
    settings_by_section = {}
    for field in config_fields:
        section = field.get('section', 'general')
        if section not in settings_by_section:
            settings_by_section[section] = []
        settings_by_section[section].append(field)

    return render_template('settings.html', guild_id=guild_id, guild_name=guild_name, settings=settings_dict, config_fields=config_fields, commands_with_states=commands_with_states, settings_by_section=settings_by_section, bot_presence_settings=bot_presence_settings, dashboard_admin_username=dashboard_admin_username)

@app.route('/dashboard/<guild_id>/settings', methods=['POST'])
@login_required
def edit_settings(guild_id):
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    # 유저가 해당 guild_id를 관리할 권한이 있는지 다시 확인
    if current_user.username != dashboard_admin_username:
        if current_user.is_discord_user and guild_id not in current_user.managed_guild_ids:
            flash("❌ 이 서버에 대한 관리 권한이 없습니다.", 'error')
            return redirect(url_for('select_server'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 서버 설정 업데이트 전에, 서버가 DB에 없으면 새로 추가
    cursor.execute("SELECT guild_id FROM server_configs WHERE guild_id = ?", (guild_id,))
    if not cursor.fetchone():
        # guild_name도 함께 삽입
        # POST 요청에는 guild_name이 없으므로, 기본값으로 설정하거나, 미리 DB에서 가져온 값이 있다면 활용
        guild_name = request.form.get('guild_name', f"서버 ID: {guild_id}") 
        cursor.execute("INSERT INTO server_configs (guild_id, guild_name) VALUES (?, ?)", (guild_id, guild_name))
        conn.commit()

    # 모든 설정 필드 (server_configs 테이블의 컬럼 이름과 일치해야 함) - GET 요청과 동일하게 유지
    config_fields = [
        # General Settings
        {'name': 'welcome_message_enabled', 'type': 'checkbox', 'label': '환영 메시지 활성화', 'section': 'general'},
        {'name': 'welcome_message_text', 'type': 'textarea', 'label': '환영 메시지 텍스트', 'section': 'general'},
        {'name': 'leave_message_enabled', 'type': 'checkbox', 'label': '퇴장 메시지 활성화', 'section': 'general'},
        {'name': 'leave_message_text', 'type': 'textarea', 'label': '퇴장 메시지 텍스트', 'section': 'general'},
        {'name': 'log_channel_id', 'type': 'text', 'label': '로그 채널 ID', 'section': 'general'},
        # Car Bot Settings
        {'name': 'car_registration_tax', 'type': 'number', 'label': '차량 등록세', 'section': 'car'},
        {'name': 'car_forbidden_cars_json', 'type': 'text', 'label': '금지 차량 (JSON Array)', 'section': 'car'},
        {'name': 'registration_channel_id', 'type': 'text', 'label': '차량 등록 채널 ID', 'section': 'car'},
        {'name': 'car_admin_channel_id', 'type': 'text', 'label': '차량 관리 채널 ID', 'section': 'car'},
        {'name': 'car_admin_role_id', 'type': 'text', 'label': '차량 관리 역할 ID', 'section': 'car'},
        {'name': 'approved_cars_channel_id', 'type': 'text', 'label': '승인 차량 채널 ID', 'section': 'car'},
        # Bank Bot Settings
        {'name': 'bank_loan_enabled', 'type': 'checkbox', 'label': '은행 대출 기능 활성화', 'section': 'bank'},
        {'name': 'bank_max_loan_amount', 'type': 'number', 'label': '은행 최대 대출 금액', 'section': 'bank'},
        {'name': 'bank_loan_interest_rate', 'type': 'number', 'step': '0.001', 'label': '은행 대출 이자율 (연 이자)', 'section': 'bank'},
        {'name': 'bank_channel_id', 'type': 'text', 'label': '은행 채널 ID', 'section': 'bank'}, # <-- 은행 채널 추가
        # Moderation Bot Settings
        {'name': 'auto_kick_warn_count', 'type': 'number', 'label': '자동 강퇴 경고 횟수', 'section': 'moderation'},
        {'name': 'mute_role_id', 'type': 'text', 'label': '뮤트 역할 ID', 'section': 'moderation'},
        # Security Settings (Modertation에 포함)
        {'name': 'invite_filter_enabled', 'type': 'checkbox', 'label': '초대 링크 검열 활성화', 'section': 'security'},
        {'name': 'spam_filter_enabled', 'type': 'checkbox', 'label': '도배 감지 활성화', 'section': 'security'},
        {'name': 'spam_threshold', 'type': 'number', 'label': '도배 기준 (메시지 개수)', 'section': 'security'},
        {'name': 'spam_time_window', 'type': 'number', 'label': '도배 시간 범위 (초)', 'section': 'security'},
        # Ticket Settings
        {'name': 'ticket_open_channel_id', 'type': 'text', 'label': '티켓 개설 채널 ID', 'section': 'ticket'},
        {'name': 'ticket_category_id', 'type': 'text', 'label': '티켓 카테고리 ID', 'section': 'ticket'},
        {'name': 'ticket_staff_role_id', 'type': 'text', 'label': '티켓 스태프 역할 ID', 'section': 'ticket'}
    ]

    # 모든 앱 명령어 목록 (슬래시 커맨드 이름 기준) - GET 요청과 동일하게 유지
    all_commands = [
        "통장개설", "잔액", "입금", "출금", "송금", "대출", "상환", "거래내역",
        "차량등록",
        "킥", "밴", "청소", "역할부여", "역할삭제", "경고", "경고조회", "경고삭제",
        "티켓 오픈", "티켓 닫기",
        "들어와", "나가", "재생", "정지",
        "주사위", "가위바위보",
        "채널명변경", "스캔블랙리스트", "보안리포트", "명령어리스트" # 새 명령어
    ]


    for field_info in config_fields:
        field_name = field_info['name']
        field_type = field_info['type']
        value = request.form.get(field_name)

        if field_type == 'checkbox':
            db_value = 1 if value == 'on' else 0
        elif field_type == 'number' and (value == '' or value is None): # 빈 값 또는 None은 DB에 NULL로 저장
            db_value = None 
        elif field_type == 'number':
            # float인지 int인지 판단하여 저장
            db_value = float(value) if '.' in value else int(value) 
        elif field_name == 'car_forbidden_cars_json': # JSON 배열 형태 처리
            try:
                # 쉼표로 분리하고 공백 제거 후 JSON 배열로 저장
                items = [item.strip() for item in value.split(',') if item.strip()]
                db_value = json.dumps(items)
            except Exception:
                db_value = '[]' # 파싱 오류 시 빈 배열
        else:
            db_value = value if value else None 

        cursor.execute(f"UPDATE server_configs SET {field_name} = ? WHERE guild_id = ?", (db_value, guild_id))

    # 명령어 활성화 상태 업데이트
    for cmd in all_commands:
        is_enabled = request.form.get(f"cmd_{cmd}_enabled") == 'on' # 'on'이면 체크된 상태
        enabled_val = 1 if is_enabled else 0
        cursor.execute("""
            INSERT INTO server_command_states (guild_id, command_name, is_enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, command_name) DO UPDATE SET is_enabled = EXCLUDED.is_enabled
        """, (str(guild_id), cmd, enabled_val))

    conn.commit()
    flash(f'서버 ({guild_id}) 설정이 성공적으로 업데이트되었습니다!', 'success')

    # 봇 상태 및 활동 설정 업데이트 (슈퍼 관리자만)
    dashboard_admin_username = os.getenv("DASHBOARD_ADMIN_USERNAME") # os.getenv 호출
    if current_user.username == dashboard_admin_username: 
        bot_status = request.form.get('status') # field.name 그대로 사용
        activity_type = request.form.get('activity_type') # field.name 그대로 사용
        activity_name = request.form.get('activity_name') # field.name 그대로 사용

        if bot_status and activity_type is not None and activity_name is not None:
            conn_for_bot_presence = get_db_connection() # DB 연결 새로 열기
            cursor_for_bot_presence = conn_for_bot_presence.cursor()
            cursor_for_bot_presence.execute("""
                INSERT OR REPLACE INTO bot_presence_settings (id, status, activity_type, activity_name)
                VALUES (1, ?, ?, ?)
            """, (bot_status, activity_type, activity_name))
            conn_for_bot_presence.commit()
            conn_for_bot_presence.close()
            flash('봇 상태 및 활동 설정이 성공적으로 업데이트되었습니다. 몇 분 내로 봇에 반영됩니다.', 'success')
        else:
            flash('봇 상태 및 활동 설정을 저장하는 데 실패했습니다. 모든 필드를 채워주세요.', 'warning')

    conn.close() # 모든 작업 후 DB 연결 닫기
    return redirect(url_for('settings_list', guild_id=guild_id)) # 변경된 설정 페이지로 리다이렉트

# --- 앱 실행 ---
if __name__ == '__main__':
    initialize_dashboard_db()
    app.run(host='0.0.0.0', port=5000, debug=True)