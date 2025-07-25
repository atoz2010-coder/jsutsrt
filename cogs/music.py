import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl 
import asyncio
import datetime # datetime 모듈 임포트 (utcnow() DeprecationWarning 회피)

# yt-dlp 설정 (음악 스트리밍 최적화)
# yt-dlp의 기본 동작은 버그 리포트 메시지를 자동으로 비활성화합니다.
# youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True, # 재생목록 다운로드 방지 (개별 곡 재생)
    'nocheckcertificate': True, # SSL 인증서 검증 무시 (가끔 발생하는 오류 회피)
    'ignoreerrors': False, # 오류 발생 시 무시하지 않음
    'logtostderr': False, # 로그를 표준 에러로 출력하지 않음
    'quiet': True, # 조용하게 실행 (터미널에 불필요한 메시지 출력 안 함)
    'no_warnings': True, # 경고 메시지 출력 안 함
    'default_search': 'auto', # URL이 아닌 검색어 입력 시 자동 검색
    'source_address': '0.0.0.0'  # 모든 네트워크 인터페이스에 바인딩
}

ffmpeg_options = {
    'options': '-vn' # 비디오 트랙 제외 (오디오만 스트리밍)
}

# youtube_dl.YoutubeDL 객체 생성
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url') # 스트리밍 가능한 최종 URL

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        """URL로부터 음악 정보를 추출하고 오디오 소스를 반환합니다."""
        loop = loop or asyncio.get_event_loop()
        # 블로킹 호출인 extract_info를 별도의 스레드에서 비동기적으로 실행
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        # 재생목록의 경우 첫 번째 항목을 가져옴 (재생목록 지원을 확장하려면 큐 로직 필요)
        if 'entries' in data:
            data = data['entries'][0]

        # FFmpegPCMAudio는 로컬 파일 경로 또는 스트리밍 URL을 받을 수 있음
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- 메시지 리스너 (모든 메시지 처리의 시작점) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """이 코그에서는 특별히 on_message 필터링 로직이 없으므로,
        메시지를 commands 프레임워크로 전달하기 위한 명시적 호출은 bot.py의 on_message에서 처리됩니다."""
        pass

    # --- 슬래시 커맨드 ---
    @app_commands.command(name="들어와", description="음성 채널에 봇을 초대합니다.")
    @app_commands.guild_only()
    async def join_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._join_voice_channel(interaction.user, interaction=interaction)

    @app_commands.command(name="나가", description="음성 채널에서 봇을 내보냅니다.")
    @app_commands.guild_only()
    async def leave_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._leave_voice_channel(interaction=interaction)

    @app_commands.command(name="재생", description="유튜브 URL로 음악을 재생합니다.")
    @app_commands.describe(url="재생할 유튜브 동영상 또는 재생목록 URL")
    @app_commands.guild_only()
    async def play_slash(self, interaction: discord.Interaction, url: str): # 이름 변경하여 메시지 기반과 구분
        await self._play_music(interaction.user, url, interaction=interaction)

    @app_commands.command(name="정지", description="현재 재생 중인 음악을 정지합니다.")
    @app_commands.guild_only()
    async def stop_slash(self, interaction: discord.Interaction): # 이름 변경하여 메시지 기반과 구분
        await self._stop_music(interaction=interaction)

    # --- 메시지 기반 명령어 ---
    @commands.command(name="들어와", help="음성 채널에 봇을 초대합니다. (예: 저스트 들어와)")
    async def msg_join(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "들어와"): # 명령어 활성화 상태 확인
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}들어와`는 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._join_voice_channel(ctx.author, ctx=ctx)

    @commands.command(name="나가", help="음성 채널에서 봇을 내보냅니다. (예: 저스트 나가)")
    async def msg_leave(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "나가"): # 명령어 활성화 상태 확인
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}나가`는 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._leave_voice_channel(ctx=ctx)

    @commands.command(name="재생", help="유튜브 URL로 음악을 재생합니다. (예: 저스트 재생 [유튜브URL])")
    async def msg_play(self, ctx: commands.Context, url: str):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "재생"): # 명령어 활성화 상태 확인
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}재생`은 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._play_music(ctx.author, url, ctx=ctx)

    @commands.command(name="정지", help="현재 재생 중인 음악을 정지합니다. (예: 저스트 정지)")
    async def msg_stop(self, ctx: commands.Context):
        if not ctx.guild: await ctx.send("이 명령어는 서버에서만 사용할 수 있습니다.") ; return
        if not self.bot.is_command_enabled(ctx.guild.id, "정지"): # 명령어 활성화 상태 확인
             await ctx.send(f"❌ 명령어 `{self.bot.command_prefix}정지`는 현재 이 서버에서 비활성화되어 있습니다."); return
        await self._stop_music(ctx=ctx)

    # --- 내부 함수 (슬래시 및 메시지 기반 명령어에서 공통 사용) ---
    async def _join_voice_channel(self, user: discord.User, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """음성 채널에 봇을 초대합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        if interaction: 
            send_response = interaction.response.send_message
            ephemeral = True
        else: 
            send_response = ctx.send
            ephemeral = False

        if not user.voice:
            await send_response("❌ 음성 채널에 먼저 들어와 있어야 합니다.", ephemeral=ephemeral)
            return

        channel = user.voice.channel
        if target_guild.voice_client:
            await target_guild.voice_client.move_to(channel)
            await send_response(f"✅ {channel.mention}으로 이동했습니다.", ephemeral=ephemeral)
        else:
            await channel.connect()
            await send_response(f"✅ {channel.mention}에 접속했습니다.", ephemeral=ephemeral)

    async def _leave_voice_channel(self, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """음성 채널에서 봇을 내보냅니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        if interaction: 
            send_response = interaction.response.send_message
            ephemeral = True
        else: 
            send_response = ctx.send
            ephemeral = False

        if target_guild.voice_client:
            await target_guild.voice_client.disconnect()
            await send_response("✅ 음성 채널에서 나갑니다.", ephemeral=ephemeral)
        else:
            await send_response("❌ 봇이 음성 채널에 연결되어 있지 않습니다.", ephemeral=ephemeral)

    async def _play_music(self, user: discord.User, url: str, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """유튜브 URL로 음악을 재생합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        if interaction: 
            # 슬래시 커맨드의 경우 defer를 먼저 보내고 followup을 사용
            send_response = interaction.response.send_message
            defer_response = interaction.response.defer
            final_send_response = interaction.followup.send
            ephemeral = True
        else: 
            # 메시지 기반의 경우 ctx.typing을 보내고 ctx.send를 사용
            send_response = ctx.send
            defer_response = ctx.typing
            final_send_response = ctx.send
            ephemeral = False

        if not target_guild.voice_client:
            if user.voice:
                try:
                    await user.voice.channel.connect()
                except discord.ClientException as e:
                    await send_response(f"❌ 음성 채널에 접속할 수 없습니다: {e}", ephemeral=ephemeral)
                    return
            else:
                await send_response("❌ 음성 채널에 먼저 들어와 있거나, 음성 채널에 봇을 초대해야 합니다.", ephemeral=ephemeral)
                return

        # defer_response는 Interaction에만 defer()가 있으므로 확인 후 호출
        if interaction:
            await defer_response(ephemeral=ephemeral)
        else:
            await defer_response() # ctx.typing()

        try:
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)

            if target_guild.voice_client.is_playing():
                await final_send_response("🎶 현재 다른 음악이 재생 중입니다. 요청하신 곡은 큐에 추가되지 않습니다.", ephemeral=ephemeral)
                # 실제 봇에서는 큐 로직을 여기에 구현해야 합니다.
            else:
                target_guild.voice_client.play(player, after=lambda e: print(f'플레이어 오류: {e}') if e else None)
                await final_send_response(f'🎶 **{player.title}**을(를) 재생합니다!', ephemeral=ephemeral)

        except Exception as e:
            print(f"Music play error: {e}") 
            await final_send_response(f'❌ 음악 재생 중 오류 발생: {e}\n유효한 유튜브 URL인지 확인해주세요.', ephemeral=ephemeral)
            return

    async def _stop_music(self, interaction: discord.Interaction = None, ctx: commands.Context = None):
        """현재 재생 중인 음악을 정지합니다."""
        target_guild = interaction.guild if interaction else ctx.guild
        if interaction: 
            send_response = interaction.response.send_message
            ephemeral = True
        else: 
            send_response = ctx.send
            ephemeral = False

        if target_guild.voice_client and target_guild.voice_client.is_playing():
            target_guild.voice_client.stop()
            await send_response("✅ 음악을 정지합니다.", ephemeral=ephemeral)
        else:
            await send_response("❌ 현재 재생 중인 음악이 없습니다.", ephemeral=ephemeral)

async def setup(bot):
    await bot.add_cog(Music(bot))
    # 각 명령어는 bot.add_cog() 호출 시 @app_commands.command 데코레이터에 의해 자동으로 등록됩니다.