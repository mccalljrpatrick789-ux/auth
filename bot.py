import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
import psycopg2
import uuid
import os
import asyncio

# Render Variables
PORT = int(os.environ.get("PORT", 8080))
DATABASE_URL = os.environ.get("DATABASE_URL")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 1. Database Setup (PostgreSQL)
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()
# Updated Table: We now link the user_id directly to a generated license_key
cursor.execute('''
    CREATE TABLE IF NOT EXISTS licenses (
        user_id TEXT PRIMARY KEY, 
        license_key TEXT
    )
''')
conn.commit()

# 2. Discord Bot Setup
class LicenseBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        # Syncs the slash commands to Discord when the bot starts
        await self.tree.sync()
        print("Slash commands synced successfully!")

bot = LicenseBot()

# 3. Slash Command for Key Generation
@bot.tree.command(name="generate", description="Generates a unique license key for a user")
@app_commands.describe(member="The user to assign the key to")
@app_commands.default_permissions(administrator=True) # Only admins can run this
async def generate_key(interaction: discord.Interaction, member: discord.Member):
    user_id = str(member.id)
    license_key = str(uuid.uuid4()) # Generate random key (e.g., 550e8400-e29b-41d4-a716-446655440000)

    try:
        # Insert or update the user's key in the database
        cursor.execute(
            """
            INSERT INTO licenses (user_id, license_key) 
            VALUES (%s, %s)
            ON CONFLICT (user_id) 
            DO UPDATE SET license_key = EXCLUDED.license_key
            """, 
            (user_id, license_key)
        )
        conn.commit()
        
        # Respond ephemerally so only the admin sees the confirmation in the channel
        await interaction.response.send_message(
            f"✅ Generated license for {member.mention}.\n**Key:** `{license_key}`", 
            ephemeral=True
        )
        
        # Optionally DM the user their new key
        try:
            await member.send(f"Here is your loader access key: `{license_key}`\nEnter this along with your Discord ID.")
        except:
            pass # User might have DMs disabled

    except Exception as e:
        await interaction.response.send_message(f"❌ Database error: {e}", ephemeral=True)


# 4. Web API Setup for C++ Verification
async def verify_license(request):
    user_id = request.query.get('user_id')
    license_key = request.query.get('license_key')

    if not user_id or not license_key:
        return web.json_response({"status": "error", "message": "Missing parameters"}, status=400)

    # Check if the exact user_id and license_key combination exists
    cursor.execute("SELECT license_key FROM licenses WHERE user_id=%s AND license_key=%s", (user_id, license_key))
    row = cursor.fetchone()

    if row:
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
