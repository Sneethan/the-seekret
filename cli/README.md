# JobBot - CLI Version

The CLI version of JobBot is a lightweight command-line tool that monitors SEEK job listings and delivers notifications through Discord webhooks.

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

## 🔧 Configuration

Copy `.env.example` to `.env` and configure the following variables:

```bash
# Required
DISCORD_WEBHOOK_URL=your_webhook_url_here

# Optional (with defaults)
CHECK_INTERVAL=300          # Time between checks in seconds
LOCATION="Hobart TAS 7000"  # Target job location
SALARY_MIN=0               # Minimum salary filter

# Filtering (comma-separated)
EXCLUDED_COMPANIES=        # Companies to exclude
REQUIRED_KEYWORDS=         # Must-have keywords
EXCLUDED_KEYWORDS=         # Keywords to filter out
```

## 🚀 Running

You can run the CLI version in two ways:

1. Using the central runner:
   ```bash
   python ../run.py cli
   ```

2. Directly:
   ```bash
   python seek_jobs_monitor.py
   ```

## 📊 Console Output

The CLI uses emoji-based logging for clarity:
- 🚀 Startup
- ⚡ Job check initiated
- ✓ Success messages
- ℹ Information updates
- ✗ Error notifications
- 💤 Sleep/wait states
- 📊 Statistics updates

## 💾 Database

The CLI version uses a local SQLite database (`jobs.db`) to:
- Track processed job listings
- Prevent duplicate notifications
- Generate job statistics
- Monitor company activity

## 🔔 Discord Notifications

Each job notification includes:
- 📋 Job title with SEEK link
- 🏢 Company name and logo
- 📍 Location details
- 💼 Employment type
- 💰 Salary information (when available)
- 📝 Job description
- 🔑 Key bullet points
- ⏰ Posting timestamp 