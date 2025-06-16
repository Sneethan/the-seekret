# The Seekret - Discord Bot Version

A Discord bot implementation that monitors SEEK job listings and provides interactive job notifications with save and reminder functionality, now with AI-powered job compatibility matching.

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
- **AI-powered job compatibility analysis** with tailored CV recommendations
- **Resume storage** for quick job compatibility checks

## 🔧 Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required Discord Settings
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_JOBS_CHANNEL_ID=channel_for_job_posts
DISCORD_LOGS_CHANNEL_ID=channel_for_console_logs
DISCORD_SAVED_JOBS_CHANNEL_ID=channel_for_saved_jobs

# OpenAI API Settings (for AI job compatibility)
OPENAI_API_KEY=your_openai_api_key  # Required for AI features
OPENAI_MODEL=gpt-4o                 # OpenAI model to use (defaults to gpt-4o)

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
- 🤖 **Check Compatibility** - Analyze how well your resume matches the job

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

## 🧠 AI Job Matching

The AI job matching feature:
- Compares your resume against job listings
- Provides a compatibility score (0-100%)
- Highlights your key strengths that match the job
- Identifies areas for improvement
- Suggests how to tailor your resume for the specific job

To use this feature:
1. Upload your resume using `/upload_resume` command
2. Click "Check Compatibility" on any job post
3. View and manage your stored resume with `/view_resume`

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
- User resumes and profile information
- AI compatibility scores and analysis results
- Reminder tracking
- Job statistics 