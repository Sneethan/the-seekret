# JobBot - Discord Bot Version

A full-featured Discord bot implementation that monitors SEEK job listings and provides interactive commands for job searching and notifications.

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

## 🤖 Bot Features

- `/jobs` - Search and filter jobs
- `/stats` - View job statistics
- `/configure` - Update bot settings
- `/help` - List available commands
- `/filters` - Manage job filters
- `/subscribe` - Set up job alerts
- `/unsubscribe` - Remove job alerts

## 🔧 Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=your_guild_id
DISCORD_CHANNEL_ID=your_channel_id

# Optional (with defaults)
CHECK_INTERVAL=300          # Time between checks in seconds
LOCATION="Hobart TAS 7000"  # Target job location
SALARY_MIN=0               # Minimum salary filter

# Filtering (comma-separated)
EXCLUDED_COMPANIES=        # Companies to exclude
REQUIRED_KEYWORDS=         # Must-have keywords
EXCLUDED_KEYWORDS=         # Keywords to filter out

# Discord Bot Settings
COMMAND_PREFIX=!           # Legacy command prefix
BOT_STATUS=watching jobs   # Bot's status message
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

## 💬 Discord Commands

### Job Search
- `/jobs search <keywords>` - Search for jobs
- `/jobs latest` - Show latest listings
- `/jobs filter <options>` - Apply search filters

### Notifications
- `/subscribe <keywords>` - Get notified about specific jobs
- `/unsubscribe` - Stop notifications
- `/configure alerts <options>` - Customize notifications

### Statistics
- `/stats today` - Today's job stats
- `/stats trends` - Job posting trends
- `/stats companies` - Top hiring companies

### Settings
- `/configure location <location>` - Set job location
- `/configure salary <amount>` - Set minimum salary
- `/configure interval <minutes>` - Set check interval

## 📊 Console Output

The bot uses emoji-based logging:
- 🚀 Bot startup
- ⚡ Job check initiated
- ✓ Success messages
- ℹ Information updates
- ✗ Error notifications
- 💤 Sleep/wait states
- 📊 Statistics updates

## 💾 Database

The bot uses SQLite (`jobs.db`) to store:
- Job listings and metadata
- User preferences and subscriptions
- Command history and statistics
- Filter configurations
- Notification settings 