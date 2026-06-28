import discord
from discord.ext import commands
from aiohttp import web
import psycopg2
import uuid
import os
import asyncio

# Render provides the PORT variable automatically.
# DATABASE_URL and BOT_TOKEN will be set manually in the Render dashboard.
PORT = int(os.environ.get("PORT", 8080))
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 1. Database Setup (PostgreSQL)
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS licenses (
        user_id TEXT, 
        server_id TEXT, 
        license_key TEXT,
        PRIMARY KEY (user_id, server_id)
    )
''')
conn.commit()

# 2. Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command(name="assign")
@commands.has_permissions(administrator=True)
async def assign_license(ctx, member: discord.Member):
    user_id = str(member.id)
    server_id = str(ctx.guild.id)
    license_key = str(uuid.uuid4())

    try:
        cursor.execute(
            """
            INSERT INTO licenses (user_id, server_id, license_key) 
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, server_id) 
            DO UPDATE SET license_key = EXCLUDED.license_key
            """, 
            (user_id, server_id, license_key)
        )
        conn.commit()
        await ctx.send(f"✅ Assigned license to {member.mention}.\nKey: `{license_key}`")
    except Exception as e:
        await ctx.send(f"❌ Error assigning license: {e}")

# 3. Web API Setup
async def verify_license(request):
    user_id = request.query.get('user_id')
    server_id = request.query.get('server_id')

    if not user_id or not server_id:
        return web.json_response({"status": "error", "message": "Missing parameters"}, status=400)

    cursor.execute("SELECT license_key FROM licenses WHERE user_id=%s AND server_id=%s", (user_id, server_id))
    row = cursor.fetchone()

    if row:
        return web.json_response({"status": "valid", "license_key": row[0]})
    else:
        return web.json_response({"status": "invalid"}, status=401)

app = web.Application()
app.router.add_get('/api/check', verify_license)

# 4. Execution Engine
@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    
    # Bind to 0.0.0.0 and the dynamic port specified by Render
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"API backend actively listening on port {PORT}")

if __name__ == "__main__":
    bot.run(BOT_TOKEN)