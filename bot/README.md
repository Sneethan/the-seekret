# The Seekret - Discord Bot Version

A Discord bot implementation that monitors SEEK job listings and provides interactive job notifications with save and reminder functionality.

```
                   (                                
  *   )   )        )\ )             )            )  
` )  /(( /(   (   (()/(   (   (  ( /((     (  ( /(  
 ( )(_))\()) ))\   /(_)) ))\ ))\ )\())(   ))\ )\()) 
(_(_()|(_)\ /((_) (_))  /((_)((_|(_)(()\ /((_|_))/  
|_   _| |(_|_))   / __|(_))(_)) | |(_|(_|_)) | |_   
  | | | ' \/ -_)  \__ \/ -_) -_)| / / '_/ -_)|  _|  
  |_| |_||_\___|  |___/\___\___||_\_\_| \___| \__|  
                                                    
```

## 🤖 Features

- Automatic job monitoring and posting
- Interactive job notifications with action buttons
- Job saving functionality with reminders
- Automatic job filtering based on criteria
- Console output logging to Discord channel

## 🔧 Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required Discord Settings
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_JOBS_CHANNEL_ID=channel_for_job_posts
DISCORD_LOGS_CHANNEL_ID=channel_for_console_logs
DISCORD_SAVED_JOBS_CHANNEL_ID=channel_for_saved_jobs

# Database Configuration
DATABASE_PATH=/path/to/your/production/jobs.db  # Optional: Defaults to local jobs.db in bot directory

# Job Search Settings
CHECK_INTERVAL=300          # Time between checks in seconds
LOCATION="Hobart TAS 7000"  # Target job location
SALARY_MIN=0               # Minimum salary filter

# Filtering (comma-separated)
EXCLUDED_COMPANIES=        # Companies to exclude
REQUIRED_KEYWORDS=         # Must-have keywords
EXCLUDED_KEYWORDS=         # Keywords to filter out
```

## 🚀 Running

You can run the bot version in two ways:

1. Using the central runner:
   ```bash
   python ../run.py bot
   ```

2. Directly:
   ```bash
   python bot.py
   ```

## 💬 Job Notifications

Each job post includes interactive buttons:
- 📝 **Apply** - Direct link to the SEEK job listing
- ❌ **Not Interested** - Dismiss the job post
- 📌 **Save** - Save the job for later with reminders

## 📌 Saved Jobs

When you save a job:
- It's tracked in the database
- You'll receive reminder notifications
- Reminders include options to:
  - ✅ Mark as applied
  - ⏰ Remind later
  - ❌ Dismiss the job

Reminders are sent:
- Once per day
- Up to 3 times total
- In the designated saved jobs channel

## 📊 Console Output

The bot logs its activity with emoji indicators:
- 🚀 Bot startup
- ⚡ Job check initiated
- ✓ Success messages
- ℹ Information updates
- ✗ Error notifications
- 📊 Statistics updates

All console output is also sent to the designated logs channel.

## 💾 Database

The bot uses SQLite (`jobs.db`) to store:
- Job listings and metadata
- Saved jobs and their status
- Reminder tracking
- Job statistics 