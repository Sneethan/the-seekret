import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import asyncio
from datetime import datetime, timedelta
import seek_jobs_monitor as seek
import sys
from io import StringIO
import random
import aiosqlite
import signal
from functools import lru_cache

# Load environment variables
load_dotenv()

# Bot configuration
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
JOBS_CHANNEL_ID = int(os.getenv('DISCORD_JOBS_CHANNEL_ID', '0'))
LOGS_CHANNEL_ID = int(os.getenv('DISCORD_LOGS_CHANNEL_ID', '0'))
SAVED_JOBS_CHANNEL_ID = int(os.getenv('DISCORD_SAVED_JOBS_CHANNEL_ID', '0'))

# Global flag for shutdown
shutdown_flag = False
shutdown_event = None  # Will be initialized in main()

# Global bot instance for job posting
bot_instance = None

# Database connection pool
class DatabasePool:
    def __init__(self):
        self._pool = []
        self._pool_lock = asyncio.Lock()
        self._max_size = 5  # Maximum number of connections to keep in pool

    async def get_connection(self):
        async with self._pool_lock:
            if self._pool:
                return self._pool.pop()
            return await aiosqlite.connect(seek.DATABASE_PATH)

    async def release_connection(self, conn):
        async with self._pool_lock:
            if len(self._pool) < self._max_size:
                self._pool.append(conn)
            else:
                await conn.close()

    async def cleanup(self):
        async with self._pool_lock:
            while self._pool:
                conn = self._pool.pop()
                await conn.close()

# Global database pool instance
db_pool = DatabasePool()

# Cache for job data
@lru_cache(maxsize=1000)
def get_job_cache_key(job_id: str, user_id: str = None):
    """Generate a cache key for job data"""
    return f"{job_id}:{user_id if user_id else '*'}"

async def get_cached_job_data(job_id: str, user_id: str = None):
    """Get job data with caching"""
    cache_key = get_job_cache_key(job_id, user_id)
    
    # Try to get a connection from the pool
    conn = await db_pool.get_connection()
    try:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            '''
            SELECT j.*, sj.user_id, sj.status, sj.saved_date
            FROM jobs j
            LEFT JOIN saved_jobs sj ON j.id = sj.job_id AND sj.user_id = ?
            WHERE j.id = ?
            ''',
            (user_id, job_id) if user_id else (None, job_id)
        ) as cursor:
            job_data = await cursor.fetchone()
            return dict(job_data) if job_data else None
    finally:
        await db_pool.release_connection(conn)

# Reminder messages
REMINDER_MESSAGES = [
    "Hey! 👋 Just checking in about that job you saved. Have you had a chance to apply yet?",
    "Don't forget about this opportunity! The perfect job won't wait forever. 🚀",
    "Still interested in this position? Now might be the perfect time to apply! ✨",
    "Quick reminder about this job you saved - it's still waiting for your application! 📝",
    "This job caught your eye earlier. Why not take the next step and apply? 🎯"
]

async def setup_saved_jobs_table():
    """Initialize the saved jobs table in the database."""
    async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS saved_jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT,
                saved_date TEXT,
                last_reminder_date TEXT,
                reminder_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'saved',
                message_id TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs (id)
            )
        ''')
        await db.commit()
    print("✓ Saved jobs table initialized")

async def save_job_for_user(job_id: str, user_id: str, message_id: str):
    """Save a job for a user and set up initial reminder."""
    try:
        async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
            # Store dates in UTC ISO format for consistency
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            await db.execute('''
                INSERT OR REPLACE INTO saved_jobs 
                (job_id, user_id, saved_date, last_reminder_date, reminder_count, status, message_id)
                VALUES (?, ?, datetime(?), NULL, 0, 'saved', ?)
            ''', (job_id, str(user_id), current_time, message_id))
            await db.commit()
    except Exception as e:
        print(f"Error saving job for user: {str(e)}")
        raise

async def check_saved_jobs_reminders():
    """Check saved jobs and send reminders if needed."""
    if not bot_instance:
        print("⚠ Bot instance not available for reminders")
        return
        
    try:
        channel = bot_instance.get_channel(SAVED_JOBS_CHANNEL_ID)
        if not channel:
            print("⚠ Could not find saved jobs channel")
            return
            
        print(f"📊 Checking saved jobs in channel: {channel.name}")
        async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row  # Enable dictionary access
            print("🔍 Querying for jobs needing reminders...")
            
            # Debug current time
            current_time = datetime.now()
            print(f"🕒 Current time: {current_time.isoformat()}")
            
            # Get saved jobs that haven't had a reminder in 24 hours and have less than 3 reminders
            query = '''
                SELECT sj.*, j.title, j.company,
                       CASE 
                           WHEN sj.last_reminder_date IS NULL THEN 'never reminded'
                           ELSE datetime(sj.last_reminder_date)
                       END as last_reminder,
                       datetime('now') as current_time
                FROM saved_jobs sj
                JOIN jobs j ON sj.job_id = j.id
                WHERE sj.status = 'saved'
                AND (
                    sj.last_reminder_date IS NULL 
                    OR 
                    datetime(sj.last_reminder_date) <= datetime('now', '-1 day')
                )
                AND sj.reminder_count < 3
            '''
            
            print(f"🔍 Executing query: {query}")
            async with db.execute(query) as cursor:
                saved_jobs = await cursor.fetchall()
                
            job_count = len(saved_jobs) if saved_jobs else 0
            print(f"📝 Found {job_count} jobs needing reminders")
            
            if job_count > 0:
                # Debug first job's reminder info
                first_job = saved_jobs[0]
                print(f"📋 First job debug info:")
                print(f"  - Job ID: {first_job['job_id']}")
                print(f"  - Last reminder: {first_job['last_reminder']}")
                print(f"  - Current DB time: {first_job['current_time']}")
                print(f"  - Reminder count: {first_job['reminder_count']}")
                print(f"  - Status: {first_job['status']}")
            
            for job in saved_jobs:
                try:
                    print(f"📬 Sending reminder for job {job['job_id']} to user {job['user_id']}")
                    # Create reminder embed
                    embed = discord.Embed(
                        title="Job Application Reminder",
                        description=random.choice(REMINDER_MESSAGES),
                        color=discord.Color.from_str('#fd0585')
                    )
                    embed.add_field(
                        name="Job Details",
                        value=f"**{job['title']}** at {job['company']}\n[View Original Post](https://discord.com/channels/{channel.guild.id}/{JOBS_CHANNEL_ID}/{job['message_id']})",
                        inline=False
                    )
                    
                    # Add reminder buttons
                    view = ReminderActionsView(job['job_id'])
                    
                    # Send reminder
                    await channel.send(
                        # content=f"<@{job['user_id']}>",  # Temporarily removed user mention
                        embed=embed,
                        view=view
                    )
                    
                    # Update reminder count and date using UTC time
                    current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                    await db.execute('''
                        UPDATE saved_jobs 
                        SET last_reminder_date = datetime(?), reminder_count = reminder_count + 1
                        WHERE job_id = ? AND user_id = ?
                    ''', (current_time, job['job_id'], job['user_id']))
                    await db.commit()  # Commit after each reminder to ensure it's saved
                    
                except Exception as e:
                    print(f"Error sending reminder for job {job['job_id']}: {str(e)}")
                    print(f"Full job data: {dict(job)}")  # Debug full job data on error
            
    except Exception as e:
        print(f"Error checking saved jobs: {str(e)}")
        import traceback
        print(traceback.format_exc())  # Print full traceback for debugging

class ReminderActionsView(discord.ui.View):
    def __init__(self, job_id: str):
        super().__init__(timeout=None)
        self.job_id = job_id
        
        # Add the Apply button
        self.add_item(discord.ui.Button(
            label="Apply Now",
            style=discord.ButtonStyle.link,
            emoji="<:blog:1330298579377590376>",
            url=f"https://www.seek.com.au/job/{job_id}" if job_id != "*" else "https://www.seek.com.au"
        ))

    @discord.ui.button(
        label="I've Applied!",
        style=discord.ButtonStyle.secondary,
        emoji="<:checkbox:1333302678339452969>",
        custom_id="applied"  # Base custom_id, job_id will be extracted from the message
    )
    async def applied_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the applied button click"""
        try:
            # Extract job ID from the message URL or embed field
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
            
            # Try to extract job ID from the embed field that contains the original post URL
            job_id = None
            for field in message_embeds[0].fields:
                if field.name == "Job Details":
                    # Extract job ID from the message link in the field value
                    message_link = field.value.split('/')[-1]
                    # Get the job data using the message ID
                    async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                        async with db.execute(
                            'SELECT job_id FROM saved_jobs WHERE message_id = ?',
                            (message_link,)
                        ) as cursor:
                            result = await cursor.fetchone()
                            if result:
                                job_id = result[0]
                            
            if not job_id:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                await db.execute('''
                    UPDATE saved_jobs 
                    SET status = 'applied'
                    WHERE job_id = ? AND user_id = ?
                ''', (job_id, str(interaction.user.id)))
                await db.commit()
            
            # Update the message content to show it's been handled
            embed = interaction.message.embeds[0]
            embed.description = "✅ Marked as applied!"
            embed.color = discord.Color.green()
            
            await interaction.response.edit_message(embed=embed, view=None)
            await interaction.message.delete(delay=3)  # Delete after 3 seconds
        except Exception as e:
            print(f"Error in applied button: {str(e)}")
            await interaction.response.send_message("❌ An error occurred", ephemeral=True)

    @discord.ui.button(
        label="Remind Later",
        style=discord.ButtonStyle.secondary,
        emoji="<:alarmclock:1333302675865079891>",
        custom_id="remind_later"  # Base custom_id, job_id will be extracted from the message
    )
    async def remind_later_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the remind later button click"""
        try:
            # Extract job ID similar to applied button
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
            
            # Try to extract job ID from the embed field that contains the original post URL
            job_id = None
            for field in message_embeds[0].fields:
                if field.name == "Job Details":
                    # Extract job ID from the message link in the field value
                    message_link = field.value.split('/')[-1]
                    # Get the job data using the message ID
                    async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                        async with db.execute(
                            'SELECT job_id FROM saved_jobs WHERE message_id = ?',
                            (message_link,)
                        ) as cursor:
                            result = await cursor.fetchone()
                            if result:
                                job_id = result[0]
            
            if not job_id:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                await db.execute('''
                    UPDATE saved_jobs 
                    SET last_reminder_date = datetime(?)
                    WHERE job_id = ? AND user_id = ?
                ''', (current_time, job_id, str(interaction.user.id)))
                await db.commit()
            
            # Update the message content to show it's been handled
            embed = interaction.message.embeds[0]
            embed.description = "⏰ Reminder snoozed for 24 hours"
            embed.color = discord.Color.blue()
            
            await interaction.response.edit_message(embed=embed, view=None)
            await interaction.message.delete(delay=3)  # Delete after 3 seconds
        except Exception as e:
            print(f"Error in remind later button: {str(e)}")
            await interaction.response.send_message("❌ An error occurred", ephemeral=True)

    @discord.ui.button(
        label="Not Interested",
        style=discord.ButtonStyle.secondary,
        emoji="<:sqaurex:1330298583135817780>",
        custom_id="not_interested"  # Base custom_id, job_id will be extracted from the message
    )
    async def not_interested_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the not interested button click"""
        try:
            # Extract job ID similar to applied button
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
            
            # Try to extract job ID from the embed field that contains the original post URL
            job_id = None
            for field in message_embeds[0].fields:
                if field.name == "Job Details":
                    # Extract job ID from the message link in the field value
                    message_link = field.value.split('/')[-1]
                    # Get the job data using the message ID
                    async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                        async with db.execute(
                            'SELECT job_id FROM saved_jobs WHERE message_id = ?',
                            (message_link,)
                        ) as cursor:
                            result = await cursor.fetchone()
                            if result:
                                job_id = result[0]
            
            if not job_id:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                await db.execute('''
                    UPDATE saved_jobs 
                    SET status = 'dismissed'
                    WHERE job_id = ? AND user_id = ?
                ''', (job_id, str(interaction.user.id)))
                await db.commit()
            
            # Update the message content to show it's been handled
            embed = interaction.message.embeds[0]
            embed.description = "❌ Job dismissed"
            embed.color = discord.Color.from_str('#e78284')
            
            await interaction.response.edit_message(embed=embed, view=None)
            await interaction.message.delete(delay=3)  # Delete after 3 seconds
        except Exception as e:
            print(f"Error in not interested button: {str(e)}")
            await interaction.response.send_message("❌ An error occurred", ephemeral=True)

class JobBot(commands.Bot):
    def __init__(self, shutdown_event):
        # Set up all intents we need
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # This is a privileged intent
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            description='A bot that monitors SEEK jobs'
        )
        
        # Set up output capture
        self.output_capture = None
        self.shutdown_event = shutdown_event
        
        # Start the reminder check loop
        self.reminder_check_loop.start()
    
    async def close(self):
        """Cleanup when the bot is shutting down."""
        print("🛑 Bot is shutting down...")
        
        # Stop all background tasks
        self.reminder_check_loop.cancel()
        
        # Restore stdout
        if self.output_capture:
            sys.stdout = sys.__stdout__
        
        # Close the database connections
        try:
            await seek.cleanup()
            await db_pool.cleanup()  # Clean up the database pool
        except Exception as e:
            print(f"Error during cleanup: {e}")
        
        await super().close()
        print("✓ Cleanup completed")
    
    async def setup_hook(self):
        """Setup hook that runs when the bot is first starting"""
        print("🔄 Setting up persistent views...")
        # Register persistent views with wildcard job IDs
        self.add_view(JobActionsView("*"))
        self.add_view(ReminderActionsView("*"))
        print("✓ Persistent views registered")
        
        await self.tree.sync()  # Sync slash commands
        print("✓ Commands synced")
        
    async def on_ready(self):
        """Called when the bot is ready"""
        print(f'🤖 Logged in as {self.user} (ID: {self.user.id})')
        print('------')
        
        # Set up output capture after bot is ready
        self.output_capture = OutputCapture(self, LOGS_CHANNEL_ID)
        sys.stdout = self.output_capture
        
        # Set the global bot instance
        global bot_instance
        bot_instance = self
        
        # Start the continuous job check
        asyncio.create_task(self.continuous_job_check())
    
    @tasks.loop(hours=1)  # Check for reminders every hour
    async def reminder_check_loop(self):
        """Check for jobs that need reminders"""
        print("🔔 Checking for job reminders...")
        try:
            await check_saved_jobs_reminders()
            print("✓ Reminder check completed")
        except Exception as e:
            print(f"❌ Error in reminder check: {str(e)}")
    
    @reminder_check_loop.before_loop
    async def before_reminder_check(self):
        """Wait until the bot is ready before starting the loop"""
        await self.wait_until_ready()
        print("✓ Reminder check loop initialized")

    async def continuous_job_check(self):
        """Continuous job checking that mimics seek_jobs_monitor's behavior"""
        try:
            while not self.shutdown_event.is_set():
                # Process jobs using our own implementation
                print(f"⚡ Starting job check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                
                jobs = await seek.fetch_jobs()
                if not jobs:
                    print("✗ No jobs fetched or error occurred")
                    continue
                
                print(f"ℹ Found {len(jobs)} jobs")
                
                async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                    new_jobs = 0
                    filtered_jobs = 0
                    for job in jobs:
                        if not await seek.is_job_processed(db, job['id']):
                            if not seek.should_process_job(job):
                                filtered_jobs += 1
                                continue
                                
                            if await post_job(job):
                                await seek.save_job(db, job)
                                new_jobs += 1
                                print(f"✓ Posted new job: {job['title']} ({job['id']})")
                            else:
                                print(f"✗ Failed to post job: {job['title']} ({job['id']})")
                    
                    if new_jobs == 0 and filtered_jobs == 0:
                        print("ℹ No new jobs found")
                    else:
                        print(f"✓ Posted {new_jobs} new jobs ({filtered_jobs} filtered out)")
                        
                    # Print job statistics
                    try:
                        stats = await seek.get_job_stats()
                        print("\n📊 Job Statistics:")
                        print(f"Total jobs tracked: {stats['total_jobs']}")
                        print(f"Jobs in last 24h: {stats['jobs_last_24h']}")
                        print("\nTop Classifications:")
                        for row in stats['top_classifications']:
                            print(f"• {row['classification']}: {row['count']}")
                        print("\nMost Active Companies:")
                        for row in stats['top_companies']:
                            print(f"• {row['company']}: {row['count']}")
                        print("\nWork Type Distribution:")
                        for row in stats['work_types']:
                            print(f"• {row['work_type']}: {row['count']}")
                    except Exception as e:
                        print(f"⚠ Error getting statistics: {str(e)}")
                
                # Break into smaller sleep intervals to check shutdown_event
                for _ in range(seek.CHECK_INTERVAL):
                    if self.shutdown_event.is_set():
                        break
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            print("Job check loop cancelled")
        except Exception as e:
            print(f"\n❌ Error in main loop: {str(e)}")
        finally:
            print("Job check loop ended")

class JobActionsView(discord.ui.View):
    def __init__(self, job_id: str):
        super().__init__(timeout=None)
        self.job_id = job_id
        
        # Add the Apply button with URL
        self.add_item(discord.ui.Button(
            label="Apply",
            style=discord.ButtonStyle.link,
            emoji="<:blog:1330298579377590376>",
            url=f"https://www.seek.com.au/job/{job_id}" if job_id != "*" else "https://www.seek.com.au"
        ))

    @discord.ui.button(
        label="Not Interested",
        style=discord.ButtonStyle.secondary,
        emoji="<:sqaurex:1330298583135817780>",
        custom_id="dismiss"  # Base custom_id, job_id will be extracted from the message
    )
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the dismiss button click"""
        try:
            # Extract job ID from the message URL
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            job_url = message_embeds[0].url
            job_id = job_url.split('/')[-1]
            
            # Update the message content to show it's been dismissed
            embed = interaction.message.embeds[0]
            embed.description = "❌ Job dismissed"
            embed.color = discord.Color.from_str('#e78284')
            
            await interaction.response.edit_message(embed=embed, view=None)
            await interaction.message.delete(delay=3)  # Delete after 3 seconds
        except Exception as e:
            print(f"Error in dismiss button: {str(e)}")
            await interaction.response.send_message("❌ An error occurred", ephemeral=True)

    @discord.ui.button(
        label="Save",
        style=discord.ButtonStyle.secondary,
        emoji="<:bookmark2:1330298581319417947>",
        custom_id="save"  # Base custom_id, job_id will be extracted from the message
    )
    async def save_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the save button click"""
        try:
            # Extract job ID from the message URL
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            job_url = message_embeds[0].url
            job_id = job_url.split('/')[-1]
            
            # Save the job for the user
            await save_job_for_user(job_id, interaction.user.id, str(interaction.message.id))
            
            # Update the message content to show it's been saved
            embed = interaction.message.embeds[0]
            embed.description = "📌 Job saved! I'll send you reminders in the saved jobs channel."
            embed.color = discord.Color.green()
            
            await interaction.response.edit_message(embed=embed, view=None)
            await interaction.message.delete(delay=3)  # Delete after 3 seconds
            
        except Exception as e:
            print(f"Error saving job: {str(e)}")
            await interaction.response.send_message("❌ An error occurred while saving the job", ephemeral=True)

class OutputCapture:
    def __init__(self, bot, channel_id):
        self.bot = bot
        self.channel_id = channel_id
        self.buffer = StringIO()
        self.last_send = 0
        self.lock = asyncio.Lock()
        self._queue = asyncio.Queue()
        self._task = None

    def write(self, text):
        sys.__stdout__.write(text)  # Still write to terminal
        self._queue.put_nowait(text)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._process_queue())

    def flush(self):
        sys.__stdout__.flush()  # Flush terminal output
        
    async def _process_queue(self):
        """Process the queue of text to write"""
        try:
            while True:
                # Get all available text from queue
                text = await self._queue.get()
                while not self._queue.empty():
                    text += await self._queue.get()

                async with self.lock:
                    self.buffer.write(text)
                    now = datetime.now().timestamp()
                    
                    # Send if buffer is getting full or enough time has passed
                    if (self.buffer.tell() > 1500) or (now - self.last_send > 5):
                        content = self.buffer.getvalue()
                        if content:
                            channel = self.bot.get_channel(self.channel_id)
                            if channel:
                                # Split into chunks if too long
                                chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
                                for chunk in chunks:
                                    try:
                                        await channel.send(f"```\n{chunk}\n```")
                                    except Exception as e:
                                        sys.__stdout__.write(f"Error sending to Discord: {str(e)}\n")
                            
                            self.buffer = StringIO()
                            self.last_send = now

                # Small delay to allow more text to accumulate
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            # Ensure any remaining content is sent
            content = self.buffer.getvalue()
            if content:
                channel = self.bot.get_channel(self.channel_id)
                if channel:
                    try:
                        await channel.send(f"```\n{content}\n```")
                    except Exception as e:
                        sys.__stdout__.write(f"Error sending to Discord: {str(e)}\n")
            raise

def create_embed(job):
    """Create a Discord embed for a job listing using discord.py's Embed class."""
    embed = discord.Embed(
        title=job['title'],
        url=f"https://www.seek.com.au/job/{job['id']}",
        color=discord.Color.from_str('#fd0585')
    )
    
    # Get company name from advertiser description if available, fallback to companyName
    company_name = job.get('advertiser', {}).get('description') or job.get('companyName', 'Unknown Company')
    
    # Add company logo if available
    if logo_url := job.get('branding', {}).get('serpLogoUrl'):
        embed.set_thumbnail(url=logo_url)
    
    # Add fields with custom emotes
    embed.add_field(name=f"{seek.EMOTE_COMPANY} Company", value=company_name, inline=True)
    embed.add_field(name=f"{seek.EMOTE_LOCATION} Location", value=job['locations'][0]['label'], inline=True)
    
    # Add work type and arrangement
    work_types = ' & '.join(job.get('workTypes', ['Not specified']))
    work_arrangements = job.get('workArrangements', {}).get('displayText', 'On-site')
    embed.add_field(name=f"{seek.EMOTE_WORK_TYPE} Work Type", value=f"{work_types} ({work_arrangements})", inline=True)
    
    if job.get('salaryLabel'):
        embed.add_field(name=f"{seek.EMOTE_SALARY} Salary", value=job['salaryLabel'], inline=False)
    
    if job.get('teaser'):
        embed.add_field(name=f"{seek.EMOTE_DESCRIPTION} Description", value=job['teaser'], inline=False)
    
    # Add bullet points if available
    if job.get('bulletPoints'):
        bullet_points = '\n• ' + '\n• '.join(job['bulletPoints'])
        embed.add_field(name=f"{seek.EMOTE_KEY_POINTS} Key Points", value=bullet_points, inline=False)
    
    # Add footer with posting time and any tags
    footer_text = f"Posted {job['listingDateDisplay']}"
    if job.get('tags'):
        tags = [tag['label'] for tag in job['tags']]
        footer_text += f" | {', '.join(tags)}"
    embed.set_footer(text=footer_text, icon_url="https://cdn.getminted.cc/seek.png")
    
    return embed

async def post_job(job):
    """Post a job to the Discord channel using the bot."""
    global bot_instance
    if not bot_instance:
        return False
        
    try:
        channel = bot_instance.get_channel(JOBS_CHANNEL_ID)
        if not channel:
            print(f"⚠ Could not find jobs channel with ID {JOBS_CHANNEL_ID}")
            return False
            
        embed = create_embed(job)
        view = JobActionsView(job['id'])
        await channel.send(embed=embed, view=view)
        return True
    except Exception as e:
        print(f"Error posting job: {str(e)}")
        return False

async def main():
    """Main function to run the bot"""
    try:
        print("📦 Initializing database...")
        # Initialize the database
        await seek.setup_database()
        await setup_saved_jobs_table()
        print("✓ Database initialization complete")
        
        # Create shutdown event
        shutdown_event = asyncio.Event()
        
        # Create and run the bot
        bot = JobBot(shutdown_event)
        
        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        
        def signal_handler():
            print("\n🛑 Shutdown signal received. Cleaning up...")
            shutdown_event.set()
            asyncio.create_task(bot.close())
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
        
        async with bot:
            await bot.start(DISCORD_TOKEN)
            
    except Exception as e:
        print(f"❌ Critical error in main: {str(e)}")
        raise  # Re-raise to ensure the error is not silently caught

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Handle Ctrl+C gracefully 