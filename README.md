# The Seekret

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

A powerful Python bot that monitors SEEK job listings and delivers real-time job alerts to your Discord server.

## Features

- 🔍 Smart job monitoring on SEEK Australia
- 🌐 Customizable location filtering (default: Hobart)
- 🎯 Keyword-based job filtering
- 📢 Real-time Discord notifications with rich embeds
- 🔄 Duplicate prevention using SQLite database
- ⏰ Configurable check intervals
- 📝 Detailed console logging with emoji indicators
- 🔒 Secure environment variable configuration
- 📊 Job statistics tracking and reporting
- 🚫 Company and keyword filtering options
- 💰 Salary-based filtering
- 🏷️ Smart tagging system

## Setup

1. Clone this repository:
```bash
git clone https://github.com/yourusername/the-seekret.git
cd the-seekret
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure Discord webhook:
   - Open Discord server settings
   - Navigate to Integrations > Webhooks
   - Create a new webhook
   - Choose a channel for job alerts
   - Copy the webhook URL

4. Set up environment variables:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Edit `.env` with your settings:
     - `DISCORD_WEBHOOK_URL`: Your Discord webhook URL
     - `CHECK_INTERVAL`: Time between checks (seconds)
     - `LOCATION`: Target job location
     - `KEYWORDS`: Comma-separated job keywords
     - `MAX_JOBS`: Maximum jobs to fetch per check
     - `SALARY_MIN`: Minimum salary filter
     - `EXCLUDED_COMPANIES`: Companies to exclude
     - `REQUIRED_KEYWORDS`: Must-have keywords
     - `EXCLUDED_KEYWORDS`: Keywords to filter out

## Usage

Start the bot:
```bash
python seek_jobs_monitor.py
```

The bot will:
- Initialize the SQLite database (`jobs.db`)
- Start monitoring SEEK jobs based on your filters
- Post new jobs to Discord in real-time
- Log all activity to the console
- Track and display job statistics

## Console Indicators

The bot uses emoji-based logging for clarity:
- 🚀 Bot startup
- ⚡ Job check initiated
- ✓ Success messages
- ℹ Information updates
- ✗ Error notifications
- 💤 Sleep/wait states
- 📊 Statistics updates

## Discord Notifications

Each job alert includes:
- 📋 Job title with direct SEEK link
- 🏢 Company name and logo
- 📍 Location details
- 💼 Employment type
- 💰 Salary information (when available)
- 📝 Job description preview
- 🔑 Key bullet points
- ⏰ Posting date and time
- 🏷️ Relevant tags

## Database

The bot uses SQLite (`jobs.db`) to:
- Prevent duplicate job alerts
- Track processed job listings
- Maintain posting history
- Generate job statistics
- Track company activity

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details. 