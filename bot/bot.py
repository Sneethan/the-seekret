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
import openai
import json
import time
import re

# Load environment variables
load_dotenv()

# Bot configuration
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
JOBS_CHANNEL_ID = int(os.getenv('DISCORD_JOBS_CHANNEL_ID', '0'))
LOGS_CHANNEL_ID = int(os.getenv('DISCORD_LOGS_CHANNEL_ID', '0'))
SAVED_JOBS_CHANNEL_ID = int(os.getenv('DISCORD_SAVED_JOBS_CHANNEL_ID', '0'))

# OpenAI API Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o')

# Initialize OpenAI client if key exists
if OPENAI_API_KEY:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    print("✓ OpenAI client initialized")
else:
    openai_client = None
    print("⚠ OpenAI API key not found, AI features will not be available")

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
            
            # Check if job data is valid
            if not job_data:
                print(f"⚠ Warning: No job data found for job_id: {job_id}")
                return None
                
            # Convert to dict and check all required fields are present
            job_dict = dict(job_data)
            
            # Ensure critical fields are not None
            required_fields = ['title', 'company', 'description']
            for field in required_fields:
                if field not in job_dict or job_dict[field] is None:
                    job_dict[field] = f"Unknown {field}"
                    
            # Ensure bullet_points is valid JSON or empty list
            if 'bullet_points' not in job_dict or not job_dict['bullet_points']:
                job_dict['bullet_points'] = '[]'
                
            return job_dict
    except Exception as e:
        print(f"Error retrieving job data: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None
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
        # Create saved jobs table with additional fields for compatibility
        await db.execute('''
            CREATE TABLE IF NOT EXISTS saved_jobs (
                job_id TEXT PRIMARY KEY,
                user_id TEXT,
                saved_date TEXT,
                last_reminder_date TEXT,
                reminder_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'saved',
                message_id TEXT,
                ai_compatibility_score REAL,
                ai_compatibility_details TEXT,
                last_analyzed_date TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs (id)
            )
        ''')
        
        # Create user resumes table
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_resumes (
                user_id TEXT PRIMARY KEY,
                resume_text TEXT,
                upload_date TEXT,
                resume_name TEXT,
                last_updated TEXT
            )
        ''')
        
        await db.commit()
        
        # Run migrations for saved_jobs table
        await migrate_saved_jobs_table(db)
        
    print("✓ Saved jobs and resumes tables initialized")

async def migrate_saved_jobs_table(db):
    """Check for and apply migrations to the saved_jobs table."""
    try:
        print("🔄 Checking for saved_jobs table migrations...")
        
        # Get current table schema
        async with db.execute("PRAGMA table_info(saved_jobs)") as cursor:
            columns = await cursor.fetchall()
            column_names = [column[1] for column in columns]
            
        # Check for missing columns and add them
        missing_columns = []
        expected_columns = {
            "ai_compatibility_score": "REAL",
            "ai_compatibility_details": "TEXT",
            "last_analyzed_date": "TEXT"
        }
        
        for col_name, col_type in expected_columns.items():
            if col_name not in column_names:
                missing_columns.append((col_name, col_type))
        
        # Add any missing columns
        for col_name, col_type in missing_columns:
            print(f"➕ Adding missing column to saved_jobs: {col_name}")
            await db.execute(f"ALTER TABLE saved_jobs ADD COLUMN {col_name} {col_type}")
        
        if missing_columns:
            await db.commit()
            print(f"✅ Added {len(missing_columns)} missing columns to saved_jobs table")
        else:
            print("✓ No saved_jobs table migrations needed")
            
    except Exception as e:
        print(f"⚠️ Error during saved_jobs table migration: {str(e)}")
        # Don't raise exception to allow app to continue with partial functionality

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
        
        # Add the purge command
        @self.tree.command(
            name="purge",
            description="Delete job listings containing the specified search term"
        )
        @app_commands.describe(
            search_term="The term to search for in job listings (e.g. 'dental')"
        )
        async def purge(interaction: discord.Interaction, search_term: str):
            """Purge job listings containing the specified search term"""
            await interaction.response.defer(ephemeral=True)
            
            try:
                # Get message history from the channel
                deleted_count = 0
                messages_to_delete = []
                
                async for message in interaction.channel.history(limit=None):
                    # Check if message is from the bot and has embeds
                    if message.author.id == self.user.id and message.embeds:
                        for embed in message.embeds:
                            # Search in title, description, and fields
                            searchable_content = [
                                embed.title or '',
                                embed.description or ''
                            ]
                            searchable_content.extend(
                                field.value for field in embed.fields
                            )
                            
                            # Join all content and search case-insensitively
                            content = ' '.join(searchable_content).lower()
                            if search_term.lower() in content:
                                messages_to_delete.append(message)
                                deleted_count += 1
                                break  # Break after finding a match in any embed
                
                # Delete the messages
                if messages_to_delete:
                    await interaction.channel.delete_messages(messages_to_delete)
                    embed = discord.Embed(
                        description=f"<:checkboxchecked4x:1333305636993241161> Deleted {deleted_count} job listing{'s' if deleted_count != 1 else ''} containing '{search_term}'",
                        color=discord.Color.from_str('#fd0585')
                    )
                else:
                    embed = discord.Embed(
                        description=f"<:squarexmark4x:1341573622484963450> No job listings found containing '{search_term}'",
                        color=discord.Color.from_str('#fd0585')
                    )
                
                # Send response and delete it after 5 seconds
                response_message = await interaction.followup.send(embed=embed, ephemeral=True)
                await asyncio.sleep(5)
                try:
                    await response_message.delete()
                except:
                    pass  # Ignore any errors during deletion
                
            except discord.errors.Forbidden:
                embed = discord.Embed(
                    description="<:squarexmark4x:1341573622484963450> I don't have permission to delete messages",
                    color=discord.Color.from_str('#fd0585')
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.errors.HTTPException as e:
                embed = discord.Embed(
                    description=f"<:squarexmark4x:1341573622484963450> Error: {str(e)}",
                    color=discord.Color.from_str('#fd0585')
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as e:
                print(f"Error in purge command: {str(e)}")
                embed = discord.Embed(
                    description="<:squarexmark4x:1341573622484963450> An error occurred while purging messages",
                    color=discord.Color.from_str('#fd0585')
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        # Add resume upload command
        @self.tree.command(
            name="upload_resume",
            description="Upload your resume file or paste resume text for AI job compatibility matching"
        )
        @app_commands.describe(
            resume_name="Optional name for your resume (e.g. 'My Technical Resume')",
            resume_file="Upload your resume file (PDF, DOCX, TXT, etc.)"
        )
        async def upload_resume(
            interaction: discord.Interaction, 
            resume_name: str = None,
            resume_file: discord.Attachment = None
        ):
            """Upload a resume to be used for job compatibility matching"""
            try:
                # If no file is provided, show the text input modal
                if not resume_file:
                    await interaction.response.send_modal(ResumeModal(resume_name=resume_name))
                    return
                
                # Check file size (8MB limit for safety)
                if resume_file.size > 8 * 1024 * 1024:
                    await interaction.response.send_message(
                        "❌ File too large. Please upload a file smaller than 8MB.",
                        ephemeral=True
                    )
                    return
                
                # Check file extension
                allowed_extensions = ['.pdf', '.docx', '.doc', '.txt', '.rtf']
                file_ext = os.path.splitext(resume_file.filename.lower())[1]
                
                if file_ext not in allowed_extensions:
                    await interaction.response.send_message(
                        f"❌ Unsupported file format. Please upload one of: {', '.join(allowed_extensions)}",
                        ephemeral=True
                    )
                    return
                
                # Defer the response since processing might take time
                await interaction.response.defer(ephemeral=True)
                
                # Create a temporary file to download the attachment
                temp_file_path = f"temp_{interaction.user.id}{file_ext}"
                await resume_file.save(temp_file_path)
                
                try:
                    # Process the file using OpenAI
                    resume_text = await process_resume_file(temp_file_path, file_ext)
                    
                    if not resume_text:
                        await interaction.followup.send(
                            "❌ Failed to extract text from your resume. Please try uploading a different file or use the text input method.",
                            ephemeral=True
                        )
                        return
                    
                    # Use the uploaded filename as resume name if not provided
                    if not resume_name:
                        resume_name = os.path.splitext(resume_file.filename)[0]
                    
                    # Save the processed resume
                    success = await save_resume(
                        interaction.user.id,
                        resume_text,
                        resume_name
                    )
                    
                    if success:
                        # Send confirmation with preview
                        preview = resume_text[:500] + ("..." if len(resume_text) > 500 else "")
                        
                        embed = discord.Embed(
                            title="✅ Resume Uploaded Successfully",
                            description=f"Your resume '{resume_name}' has been processed and stored. You can now use the 'Check Compatibility' button on job posts.",
                            color=discord.Color.green()
                        )
                        
                        embed.add_field(
                            name="Content Preview",
                            value=preview,
                            inline=False
                        )
                        
                        await interaction.followup.send(
                            embed=embed,
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            "❌ Error saving your resume to the database. Please try again later.",
                            ephemeral=True
                        )
                finally:
                    # Clean up the temporary file
                    try:
                        os.remove(temp_file_path)
                    except Exception:
                        pass
                    
            except Exception as e:
                print(f"Error in resume upload command: {str(e)}")
                
                # If response hasn't been sent yet
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            f"❌ An error occurred while processing your resume: {str(e)}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"❌ An error occurred while processing your resume: {str(e)}",
                            ephemeral=True
                        )
                except:
                    pass
                
        # Add view resume command
        @self.tree.command(
            name="view_resume",
            description="View your currently stored resume"
        )
        async def view_resume(interaction: discord.Interaction):
            """View your currently stored resume"""
            try:
                resume = await get_user_resume(interaction.user.id)
                
                if not resume:
                    await interaction.response.send_message(
                        "❌ You don't have a resume stored yet. Use `/upload_resume` to upload one.",
                        ephemeral=True
                    )
                    return
                    
                # Create embed to show resume info
                embed = discord.Embed(
                    title=f"Your Resume: {resume['resume_name']}",
                    description="Here's a preview of your stored resume:",
                    color=discord.Color.from_str('#fd0585')
                )
                
                # Add resume text preview (first 500 chars)
                preview_text = resume['resume_text'][:500] + "..." if len(resume['resume_text']) > 500 else resume['resume_text']
                embed.add_field(
                    name="Content Preview",
                    value=preview_text,
                    inline=False
                )
                
                # Add last updated date
                embed.add_field(
                    name="Last Updated",
                    value=resume['last_updated'],
                    inline=False
                )
                
                # Add buttons to delete or reupload
                view = ResumeActionsView()
                
                await interaction.response.send_message(
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
                
            except Exception as e:
                print(f"Error in view resume command: {str(e)}")
                await interaction.response.send_message(
                    "❌ An error occurred while retrieving your resume.",
                    ephemeral=True
                )
        
        # Add migrate database command for admins
        @self.tree.command(
            name="migrate_database",
            description="Force a database migration to fix schema issues (Admin only)"
        )
        async def migrate_database(interaction: discord.Interaction):
            """Force a database migration to update schema"""
            try:
                # Check if user has admin permissions
                if not interaction.user.guild_permissions.administrator:
                    await interaction.response.send_message(
                        "❌ This command requires administrator permissions.",
                        ephemeral=True
                    )
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                # Connect to database and run migrations
                async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                    # First run migration for jobs table
                    await seek.migrate_database(db)
                    
                    # Then run migration for saved_jobs table
                    await migrate_saved_jobs_table(db)
                    
                await interaction.followup.send(
                    "✅ Database migration completed successfully! Schema should now be up-to-date.",
                    ephemeral=True
                )
                
            except Exception as e:
                print(f"Error in migrate_database command: {str(e)}")
                await interaction.followup.send(
                    f"❌ Error during database migration: {str(e)}",
                    ephemeral=True
                )
        
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
                
                try:
                    jobs = await seek.fetch_jobs()
                    if not jobs:
                        print("✗ No jobs fetched or error occurred")
                        continue
                    
                    print(f"ℹ Found {len(jobs)} jobs")
                    
                    async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                        new_jobs = 0
                        filtered_jobs = 0
                        for job in jobs:
                            try:
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
                            except Exception as job_error:
                                print(f"❌ Error processing job {job.get('id', 'unknown')}: {str(job_error)}")
                                # Continue with next job
                        
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
                except aiosqlite.OperationalError as db_error:
                    print(f"\n❌ Database schema error: {str(db_error)}")
                    print("🔄 This may be due to a schema change. Please restart the bot to apply migrations.")
                except Exception as e:
                    print(f"\n❌ Error during job processing: {str(e)}")
                    import traceback
                    print(traceback.format_exc())
                
                # Break into smaller sleep intervals to check shutdown_event
                for _ in range(seek.CHECK_INTERVAL):
                    if self.shutdown_event.is_set():
                        break
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            print("Job check loop cancelled")
        except Exception as e:
            print(f"\n❌ Error in main loop: {str(e)}")
            import traceback
            print(traceback.format_exc())  # Print full traceback for easier debugging
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

    @discord.ui.button(
        label="Check Compatibility",
        style=discord.ButtonStyle.secondary,
        emoji="<:sparkle220x:1384044645511860294>",
        custom_id="ai_compatibility"
    )
    async def ai_compatibility_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle AI compatibility check button click"""
        try:
            # Extract job ID from the message URL
            message_embeds = interaction.message.embeds
            if not message_embeds:
                await interaction.response.send_message("❌ Error: Could not find job information", ephemeral=True)
                return
                
            job_url = message_embeds[0].url
            job_id = job_url.split('/')[-1]
            
            # Check if user has a resume uploaded
            resume = await get_user_resume(interaction.user.id)
            
            if not resume:
                # No resume found, prompt to upload one
                await interaction.response.send_modal(
                    ResumeModal(job_id=job_id, analyze_immediately=True)
                )
                return
            
            # User has a resume, start the compatibility analysis
            await interaction.response.defer(ephemeral=True)
            
            # Get job data
            job_data = await get_cached_job_data(job_id)
            if not job_data:
                await interaction.followup.send(
                    "❌ Could not find job data for compatibility analysis. The job may no longer exist in our database.",
                    ephemeral=True
                )
                return
                
            # Validate resume text
            if not resume['resume_text'] or len(resume['resume_text']) < 50:
                await interaction.followup.send(
                    "❌ Your stored resume appears to be empty or too short for analysis. Please upload a complete resume using `/upload_resume`.",
                    ephemeral=True
                )
                return
            
            # Send initial status
            await interaction.followup.send(
                "🔍 Analyzing your resume against this job posting...\nThis may take up to 30 seconds.",
                ephemeral=True
            )
            
            try:
                # Run the analysis
                score, analysis = await analyze_job_compatibility(resume['resume_text'], job_data)
                
                # Create the results embed
                embed = create_compatibility_embed(job_data, score, analysis)
                
                # Send the results to the user
                await interaction.followup.send(
                    content=f"Here's your AI job match analysis for: **{job_data.get('title')}**",
                    embed=embed,
                    ephemeral=True
                )
                
                # Save the analysis results
                await save_compatibility_results(job_id, interaction.user.id, score, analysis)
            except Exception as analysis_error:
                print(f"Error during compatibility analysis: {str(analysis_error)}")
                import traceback
                print(traceback.format_exc())
                
                await interaction.followup.send(
                    f"❌ Error analyzing job compatibility: {str(analysis_error)}\n\n" +
                    "This could be due to a server issue or a problem with OpenAI's API. Please try again later.",
                    ephemeral=True
                )
            
        except Exception as e:
            print(f"Error in AI compatibility check: {str(e)}")
            import traceback
            print(traceback.format_exc())
            
            # Try to send an error message, but don't error if response is already sent
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ An error occurred during the compatibility check.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ An error occurred during the compatibility check.", ephemeral=True)
            except:
                pass

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

async def save_resume(user_id: str, resume_text: str, resume_name: str = "resume.txt"):
    """Save a user's resume to the database."""
    try:
        current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
            await db.execute('''
                INSERT OR REPLACE INTO user_resumes
                (user_id, resume_text, upload_date, resume_name, last_updated)
                VALUES (?, ?, datetime(?), ?, datetime(?))
            ''', (str(user_id), resume_text, current_time, resume_name, current_time))
            await db.commit()
        return True
    except Exception as e:
        print(f"Error saving resume: {str(e)}")
        return False

async def get_user_resume(user_id: str):
    """Get a user's resume from the database."""
    try:
        async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT resume_text, resume_name, last_updated FROM user_resumes WHERE user_id = ?',
                (str(user_id),)
            ) as cursor:
                resume = await cursor.fetchone()
                return dict(resume) if resume else None
    except Exception as e:
        print(f"Error getting resume: {str(e)}")
        return None

async def analyze_job_compatibility(resume_text: str, job_data: dict):
    """Analyze compatibility between resume and job using OpenAI API."""
    if not openai_client:
        return None, "OpenAI API key not configured."

    try:
        # Safely parse JSON fields with proper error handling
        def safe_parse_json(json_str):
            if not json_str:
                return []
            try:
                return json.loads(json_str)
            except (json.JSONDecodeError, TypeError):
                return []
        
        # Format job data for the AI prompt
        job_description = {
            "title": job_data.get('title', ''),
            "company": job_data.get('company', ''),
            "description": job_data.get('description', ''),
            "bullet_points": safe_parse_json(job_data.get('bullet_points')),
            "classification": job_data.get('classification', ''),
            "subclassification": job_data.get('subclassification', ''),
            "work_type": job_data.get('work_type', ''),
            "salary": job_data.get('salary', '')
        }
        
        # Debug info
        print(f"Processing job compatibility for: {job_description['title']}")
        
        # Construct the prompt
        prompt = f"""
        Please analyze the compatibility between this resume and job description. Provide:
        1. A compatibility score from 0-100%
        2. Key strengths that match the job requirements
        3. Areas where the resume could be improved for this specific position
        4. Suggestions for tailoring the resume to better match this job
        
        JOB DESCRIPTION:
        {json.dumps(job_description, indent=2)}
        
        RESUME:
        {resume_text}
        
        Format your response as a JSON object with the following keys:
        - score: A number between 0-100
        - strengths: An array of strings
        - improvement_areas: An array of strings
        - tailoring_suggestions: An array of strings
        """
        
        # Set up API parameters - some models don't support temperature
        api_params = {
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": "You are a professional resume analyzer and job matching expert."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        # Only add temperature for models known to support it
        # GPT-4 and GPT-3.5-turbo typically support temperature
        if "gpt-4" in OPENAI_MODEL or "gpt-3.5-turbo" in OPENAI_MODEL:
            api_params["temperature"] = 0.3
        
        print(f"Calling OpenAI API with model: {OPENAI_MODEL}")
        
        # Call OpenAI API
        try:
            response = openai_client.chat.completions.create(**api_params)
        except openai.BadRequestError as e:
            # If temperature is the issue, retry without it
            if "temperature" in str(e):
                print("Temperature not supported by this model, retrying without temperature parameter")
                if "temperature" in api_params:
                    del api_params["temperature"]
                response = openai_client.chat.completions.create(**api_params)
            else:
                # Re-raise if it's not a temperature issue
                raise
        
        # Extract and parse the response
        result_text = response.choices[0].message.content.strip()
        
        # Debug response
        print(f"OpenAI API response received, length: {len(result_text)}")
        
        # Parse result with error handling
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as e:
            print(f"Error parsing OpenAI response: {str(e)}")
            print(f"Response was: {result_text[:100]}...")
            return 50, {
                "error": "Failed to parse AI response",
                "strengths": ["Unable to analyze strengths automatically"],
                "improvement_areas": ["Unable to analyze improvement areas"],
                "tailoring_suggestions": ["Unable to provide tailoring suggestions"]
            }
        
        # Ensure all expected fields exist
        result = {
            "score": result.get("score", 50),
            "strengths": result.get("strengths", []),
            "improvement_areas": result.get("improvement_areas", []),
            "tailoring_suggestions": result.get("tailoring_suggestions", [])
        }
        
        # Return score and details
        return result.get('score', 0), result
        
    except Exception as e:
        print(f"Error analyzing job compatibility: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return 0, {"error": str(e), "strengths": [], "improvement_areas": [], "tailoring_suggestions": []}

class ResumeModal(discord.ui.Modal):
    """Modal for submitting a resume."""
    
    resume_text = discord.ui.TextInput(
        label="Paste your resume text here",
        style=discord.TextStyle.paragraph,
        placeholder="Paste the contents of your resume/CV here...",
        required=True,
        max_length=4000  # Discord limit
    )
    
    def __init__(self, job_id: str = None, analyze_immediately: bool = False, resume_name: str = None):
        self.job_id = job_id
        self.analyze_immediately = analyze_immediately
        super().__init__(title="Upload Your Resume")
        
        # Set resume name field with provided value if any
        self.resume_name = discord.ui.TextInput(
            label="Resume Name",
            placeholder="My Professional Resume",
            required=False,
            max_length=100,
            default=resume_name or ""
        )
        self.add_item(self.resume_name)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle resume submission."""
        try:
            # Save the resume
            resume_name = self.resume_name.value or "Resume"
            success = await save_resume(
                interaction.user.id, 
                self.resume_text.value, 
                resume_name
            )
            
            if success:
                if self.analyze_immediately and self.job_id:
                    # Tell the user we're analyzing
                    await interaction.response.send_message(
                        "Resume saved! Analyzing compatibility with this job...",
                        ephemeral=True
                    )
                    
                    # Start analysis in background
                    asyncio.create_task(
                        self.analyze_job_compatibility_now(interaction, self.job_id)
                    )
                else:
                    await interaction.response.send_message(
                        "✅ Resume saved successfully! You can now use the 'Check Compatibility' button on job posts.",
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "❌ Error saving your resume. Please try again later.",
                    ephemeral=True
                )
        except Exception as e:
            print(f"Error in resume submission: {str(e)}")
            await interaction.response.send_message(
                "An error occurred while processing your resume.",
                ephemeral=True
            )
    
    async def analyze_job_compatibility_now(self, interaction, job_id):
        """Analyze job compatibility immediately after resume submission."""
        try:
            # Get job data
            job_data = await get_cached_job_data(job_id)
            if not job_data:
                await interaction.followup.send(
                    "❌ Could not find job data for compatibility analysis.",
                    ephemeral=True
                )
                return
            
            # Get the user's resume that was just saved
            resume = await get_user_resume(interaction.user.id)
            if not resume:
                await interaction.followup.send(
                    "❌ Could not retrieve your resume for analysis.",
                    ephemeral=True
                )
                return
            
            # Analyze compatibility
            score, analysis = await analyze_job_compatibility(resume['resume_text'], job_data)
            
            # Create an embed to display results
            embed = create_compatibility_embed(job_data, score, analysis)
            
            # Send results
            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )
            
            # Save the analysis results to the database
            await save_compatibility_results(job_id, interaction.user.id, score, analysis)
            
        except Exception as e:
            print(f"Error in job compatibility analysis: {str(e)}")
            await interaction.followup.send(
                "❌ An error occurred during compatibility analysis.",
                ephemeral=True
            )

async def save_compatibility_results(job_id, user_id, score, analysis_details):
    """Save job compatibility analysis results to the database."""
    try:
        current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        analysis_json = json.dumps(analysis_details) if isinstance(analysis_details, dict) else '{}'
        
        async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
            await db.execute('''
                UPDATE saved_jobs
                SET ai_compatibility_score = ?, 
                    ai_compatibility_details = ?,
                    last_analyzed_date = datetime(?)
                WHERE job_id = ? AND user_id = ?
            ''', (score, analysis_json, current_time, job_id, str(user_id)))
            await db.commit()
        return True
    except Exception as e:
        print(f"Error saving compatibility results: {str(e)}")
        return False

def create_compatibility_embed(job_data, score, analysis):
    """Create a Discord embed to display job compatibility results."""
    # Format the score as a percentage
    score_display = f"{score:.1f}%" if isinstance(score, (int, float)) else "N/A"
    
    # Create the embed
    embed = discord.Embed(
        title=f"AI Job Match: {job_data.get('title', 'Job Opening')}",
        description=f"**Compatibility Score: {score_display}**",
        color=get_score_color(score)
    )
    
    # Add job details
    embed.add_field(
        name=f"{seek.EMOTE_COMPANY} Company",
        value=job_data.get('company', 'Unknown Company'),
        inline=True
    )
    
    # Add strengths
    strengths = analysis.get('strengths', [])
    if strengths:
        embed.add_field(
            name="💪 Key Strengths",
            value="\n• " + "\n• ".join(strengths[:3]),
            inline=False
        )
    
    # Add improvement areas
    improvements = analysis.get('improvement_areas', [])
    if improvements:
        embed.add_field(
            name="🎯 Areas to Improve",
            value="\n• " + "\n• ".join(improvements[:3]),
            inline=False
        )
    
    # Add tailoring suggestions
    suggestions = analysis.get('tailoring_suggestions', [])
    if suggestions:
        embed.add_field(
            name="✏️ Tailoring Suggestions",
            value="\n• " + "\n• ".join(suggestions[:3]),
            inline=False
        )
    
    # Add footer with timestamp
    embed.set_footer(
        text=f"Analysis generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        icon_url="https://cdn.getminted.cc/seek.png"
    )
    
    return embed

def get_score_color(score):
    """Get an appropriate color based on the compatibility score."""
    if isinstance(score, (int, float)):
        if score >= 80:
            return discord.Color.green()
        elif score >= 60:
            return discord.Color.gold()
        elif score >= 40:
            return discord.Color.orange()
        else:
            return discord.Color.red()
    return discord.Color.from_str('#fd0585')  # Default color

class ResumeActionsView(discord.ui.View):
    """View with buttons for resume management."""
    def __init__(self):
        super().__init__(timeout=300)  # 5 minute timeout

    @discord.ui.button(
        label="Update Resume",
        style=discord.ButtonStyle.primary,
        emoji="📝"
    )
    async def update_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open modal to update resume"""
        try:
            await interaction.response.send_modal(ResumeModal())
        except Exception as e:
            print(f"Error opening resume modal: {str(e)}")
            await interaction.response.send_message(
                "❌ An error occurred while opening the resume update form.",
                ephemeral=True
            )
            
    @discord.ui.button(
        label="Delete Resume",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def delete_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Delete the user's resume"""
        try:
            async with seek.aiosqlite.connect(seek.DATABASE_PATH) as db:
                await db.execute(
                    'DELETE FROM user_resumes WHERE user_id = ?',
                    (str(interaction.user.id),)
                )
                await db.commit()
                
            await interaction.response.edit_message(
                content="✅ Your resume has been successfully deleted.",
                embed=None,
                view=None
            )
        except Exception as e:
            print(f"Error deleting resume: {str(e)}")
            await interaction.response.send_message(
                "❌ An error occurred while deleting your resume.",
                ephemeral=True
            )

async def process_resume_file(file_path, file_ext):
    """Process resume file and extract text content using OpenAI."""
    if not openai_client:
        raise Exception("OpenAI API key not configured. Cannot process resume files.")
    
    try:
        # For simple text files, just read the content directly
        if file_ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        
        # For all other file types, we need to extract file contents
        file_content = None
        
        if file_ext == '.pdf':
            try:
                # Try to use PyPDF2 if available
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page_num in range(len(reader.pages)):
                        text += reader.pages[page_num].extract_text() + "\n\n"
                    file_content = text
            except ImportError:
                # If PyPDF2 is not available, use a simple approach
                print("PyPDF2 not available, using fallback method for PDF")
                with open(file_path, 'rb') as f:
                    # Read binary content for processing with OpenAI
                    file_content = "PDF binary content extracted"
        
        elif file_ext == '.docx':
            try:
                # Try to use python-docx if available
                import docx
                doc = docx.Document(file_path)
                text = []
                for para in doc.paragraphs:
                    text.append(para.text)
                file_content = '\n'.join(text)
            except ImportError:
                # If python-docx is not available, use a simple approach
                print("python-docx not available, using fallback method for DOCX")
                with open(file_path, 'rb') as f:
                    # Read binary content for processing with OpenAI
                    file_content = "DOCX binary content extracted"
        
        else:
            # For other file types, just note the format
            with open(file_path, 'rb') as f:
                file_content = f"File content in {file_ext} format"
                
        # Now use OpenAI to process the extracted content
        if file_content:
            # Set up API parameters
            api_params = {
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": """You are a resume parser. Extract or format the text content from the provided resume.
                     Format the content in clean Markdown, preserving the structure, sections, bullet points, and important formatting.
                     Include ALL content from the resume - contact details, education, experience, skills, etc.
                     Format the output as properly structured Markdown with appropriate headers and bullet points."""},
                    {"role": "user", "content": f"Here's the content from a resume in {file_ext} format. Please format it as clean markdown:\n\n{file_content}"}
                ]
            }
            
            # Only add temperature for models known to support it
            if "gpt-4" in OPENAI_MODEL or "gpt-3.5-turbo" in OPENAI_MODEL:
                api_params["temperature"] = 0.2
                
            print(f"Processing resume file with model: {OPENAI_MODEL}")
            
            # Call OpenAI API with error handling
            try:
                response = openai_client.chat.completions.create(**api_params)
            except openai.BadRequestError as e:
                # If temperature is the issue, retry without it
                if "temperature" in str(e):
                    print("Temperature not supported for resume processing, retrying without temperature")
                    if "temperature" in api_params:
                        del api_params["temperature"]
                    response = openai_client.chat.completions.create(**api_params)
                else:
                    # Re-raise if it's not a temperature issue
                    raise
            
            return response.choices[0].message.content.strip()
        
        return None
    except Exception as e:
        print(f"Error processing resume file: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

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