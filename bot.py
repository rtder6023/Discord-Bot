import os
import requests
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import mysql.connector
from gtts import gTTS
from bs4 import BeautifulSoup
from youtube_comment_downloader import YoutubeCommentDownloader
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"  # 예시 URL, 실제 엔드포인트는 문서 참조
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',
    'database': 'discord_bot'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix=".", intents=intents)

def query_gemini(prompt: str):
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY,
    }
    data = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    response = requests.post(GEMINI_API_URL, json=data, headers=headers)

    if response.status_code == 200:
        try:
            json_response = response.json()
            if 'candidates' in json_response and json_response['candidates']:
                content = json_response['candidates'][0]['content']['parts'][0]['text']
                return content
            else:
                print("응답 JSON에 'candidates'가 없음:", json_response)
                return "에러: 응답에 'candidates' 항목이 없음"
        except ValueError:
            return "에러: 응답을 JSON으로 파싱할 수 없음"
    else:
        return f"에러: {response.status_code}, {response.text}"



ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

queue = []

async def play_next(ctx, voice_client):
    if len(queue) > 0:
        player = queue.pop(0) 
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx, voice_client), bot.loop))
        await ctx.send(f'대기열에서 재생 중: {player.title}')
    else:
        await voice_client.disconnect()

@bot.command(name="ㄱ")
async def play(ctx, url: str):
    if not ctx.message.author.voice:
        await ctx.send("음성 채널에 있어야 뭘 하지;; ㅂㅅ")
        return

    channel = ctx.message.author.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

    if not voice_client:
        voice_client = await channel.connect()

    async with ctx.typing():
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        if not voice_client.is_playing():
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx, voice_client), bot.loop))
            await ctx.send(f'재생 중: {player.title}')
        else:
            queue.append(player)
            await ctx.send(f'{player.title}가 대기열에 추가됨.')

@bot.command(name="꺼져")
async def stop(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    
    if voice_client and voice_client.is_connected():
        await ctx.send(
            embed=discord.Embed(color=discord.Color.red()).set_image(url="https://cdn.discordapp.com/attachments/914836778609946627/1339105311994413086/viewimage.png?ex=67ad8281&is=67ac3101&hm=6fe458333159ad6db1110a60ba5503c65a54f20749e8387cc07c256e442f2975&")
        )
        await voice_client.disconnect()
    else:
        await ctx.send("음성 채널에 있어야 뭘 하지;; ㅂㅅ")

@bot.command(name="즐겨찾기")
async def add_favorite(ctx, url: str):
    async with ctx.typing():
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO favorites (user_id, url, title) VALUES (%s, %s, %s)",
            (ctx.author.id, url, player.title)
        )
        connection.commit()
        cursor.close()
        connection.close()

        await ctx.send(f'{player.title}이 즐겨찾기에 추가됨')

@bot.command(name="목록")
async def list_favorites(ctx):
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT title, url FROM favorites WHERE user_id = %s", (ctx.author.id,))
    favorites = cursor.fetchall()
    cursor.close()
    connection.close()

    if not favorites:
        await ctx.send("즐겨찾기 목록이 비어있음.")
    else:
        embed = discord.Embed(title="즐겨찾기 목록", color=discord.Color.blue())
        for title, url in favorites:
            embed.add_field(name=title, value=url, inline=False)
        await ctx.send(embed=embed)

@bot.command(name="제거")
async def remove_favorite(ctx, url: str):
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        "DELETE FROM favorites WHERE user_id = %s AND url = %s",
        (ctx.author.id, url)
    )
    connection.commit()
    if cursor.rowcount > 0:
        await ctx.send("즐겨찾기에서 제거됨")
    else:
        await ctx.send("즐겨찾기에서 찾을 수 없음")
    cursor.close()
    connection.close()

@bot.command(name="재생")
async def play_favorite(ctx, index: int):
    offset = index - 1
    if offset < 0:
        await ctx.send("숫자는 1부터 시작해야 함")
        return

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith("0 "):
        tts_text = message.content[2:].strip()
        if not tts_text:
            await message.channel.send("TTS할 대사를 입력")
            return

        if not message.author.voice:
            await message.channel.send("음성 채널에 있어야 뭘 하지;; ㅂㅅ")
            return

        voice_channel = message.author.voice.channel
        voice_client = discord.utils.get(bot.voice_clients, guild=message.guild)
        if not voice_client:
            voice_client = await voice_channel.connect()
        elif voice_client.channel != voice_channel:
            await voice_client.move_to(voice_channel)

        if voice_client.is_playing():
            await message.channel.send("음악이 재생 중")
            return

        filename = f"tts_{message.author.id}.mp3"
        try:
            tts = gTTS(text=tts_text, lang='ko')
            tts.save(filename)
        except Exception as e:
            await message.channel.send("오류가 발생함")
            return

        source = discord.FFmpegPCMAudio(filename)
        def after_playing(error):
            if os.path.exists(filename):
                os.remove(filename)
        voice_client.play(source, after=after_playing)
        return

    await bot.process_commands(message)

@bot.command(name="url사진")
async def fetch_images(ctx, url: str, count: int):
    await ctx.typing()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Referer": url
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        await ctx.send("웹사이트에 접속할 수 없음")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    images = soup.find_all('img')

    if not images:
        await ctx.send("이미지를 찾을 수 없음")
        return

    sent = 0
    for img in images:
        src = img.get('src')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                from urllib.parse import urljoin
                src = urljoin(url, src)

            await ctx.send(src)
            sent += 1
            if sent >= count:
                break

@bot.command(name="대화")
async def chat_with_gemini(ctx, *, prompt: str):
    response = query_gemini(prompt)
    await ctx.send(response)



bot.run(os.getenv('DISCORD_BOT_TOKEN'))
