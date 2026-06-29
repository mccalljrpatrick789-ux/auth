import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
import psycopg2
import uuid
import os
import datetime

# Render Variables
PORT = int(os.environ.get("PORT", 8080))
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 1. Database Setup
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Added 'expires_at' column to track duration
cursor.execute('''
    CREATE TABLE IF NOT EXISTS licenses (
        user_id TEXT PRIMARY KEY, 
        license_key TEXT,
        expires_at TIMESTAMP
    )
''')
conn.commit()

class LicenseBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        # Change this if you want instant syncing to your specific server!
        await self.tree.sync()
        print("Slash commands synced successfully!")

bot = LicenseBot()

# 3. Slash Command for Key Generation (Now with 'days' argument)
@bot.tree.command(name="generate", description="Generates a unique license key for a user")
@app_commands.describe(member="The user to assign the key to", days="Duration in days (Use 0 for lifetime)")
@app_commands.default_permissions(administrator=True)
async def generate_key(interaction: discord.Interaction, member: discord.Member, days: int = 30):
    user_id = str(member.id)
    license_key = str(uuid.uuid4())
    
    # Calculate expiration date
    expires_at = None
    if days > 0:
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=days)

    try:
        cursor.execute(
            """
            INSERT INTO licenses (user_id, license_key, expires_at) 
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) 
            DO UPDATE SET license_key = EXCLUDED.license_key, expires_at = EXCLUDED.expires_at
            """, 
            (user_id, license_key, expires_at)
        )
        conn.commit()
        
        duration_text = f"{days} Days" if days > 0 else "Lifetime"
        await interaction.response.send_message(
            f"✅ Generated {duration_text} license for {member.mention}.\n**Key:** `{license_key}`", 
            ephemeral=True
        )

    except Exception as e:
        conn.rollback() # Safe fallback
        await interaction.response.send_message(f"❌ Database error: {e}", ephemeral=True)


# 4. Web API Setup for C++ Verification
async def verify_license(request):
    user_id = request.query.get('user_id')
    license_key = request.query.get('license_key')

    if not user_id or not license_key:
        return web.json_response({"status": "error", "message": "Missing parameters"}, status=400)

    cursor.execute("SELECT license_key, expires_at FROM licenses WHERE user_id=%s AND license_key=%s", (user_id, license_key))
    row = cursor.fetchone()

    if row:
        expires_at = row[1]
        # Check if the key has an expiration date AND if that date has passed
        if expires_at and expires_at < datetime.datetime.utcnow():
            return web.json_response({"status": "expired"})
        else:
            return web.json_response({"status": "valid"})
    else:
        return web.json_response({"status": "invalid"}, status=401)

app = web.Application()
app.router.add_get('/api/check', verify_license)

# 5. Execution Engine
@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"API backend actively listening on port {PORT}")

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
