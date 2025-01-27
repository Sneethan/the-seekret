import os
import json
import asyncio
import aiosqlite
import requests
import signal
from datetime import datetime, timedelta
from discord_webhook import DiscordWebhook, DiscordEmbed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ASCII Logo
LOGO = '''
                   (                                
  *   )   )        )\ )             )            )  
` )  /(( /(   (   (()/(   (   (  ( /((     (  ( /(  
 ( )(_))\()) ))\   /(_)) ))\ ))\ )\())(   ))\ )\()) 
(_(_()|(_)\ /((_) (_))  /((_)((_|(_)(()\ /((_|_))/  
|_   _| |(_|_))   / __|(_))(_)) | |(_|(_|_)) | |_   
  | | | ' \/ -_)  \__ \/ -_) -_)| / / '_/ -_)|  _|  
  |_| |_||_\___|  |___/\___\___||_\_\_| \___| \__|  
                                                    
'''

# Configuration
WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '300'))  # Default 5 minutes

# Use environment variable for database path with fallback to local path
DATABASE_PATH = os.getenv('DATABASE_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs.db'))
print(f"📂 Using database at: {DATABASE_PATH}")

# Global flag for shutdown
shutdown_flag = False

# Custom Discord Emotes (can be configured in .env)
EMOTE_COMPANY = os.getenv('EMOTE_COMPANY', '🏢')  # Fallback to unicode emoji if not set
EMOTE_LOCATION = os.getenv('EMOTE_LOCATION', '📍')
EMOTE_WORK_TYPE = os.getenv('EMOTE_WORK_TYPE', '💼')
EMOTE_SALARY = os.getenv('EMOTE_SALARY', '💰')
EMOTE_DESCRIPTION = os.getenv('EMOTE_DESCRIPTION', 'ℹ️')
EMOTE_KEY_POINTS = os.getenv('EMOTE_KEY_POINTS', '🔑')

def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_flag
    if not shutdown_flag:
        print("\n🛑 Shutdown signal received. Cleaning up...")
        shutdown_flag = True
    else:
        print("\n⚠ Force quitting... (Press Ctrl+C again to force exit)")
        os._exit(1)

# Register signal handlers
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Job filtering configuration
SALARY_MIN = float(os.getenv('SALARY_MIN', '0'))  # Minimum salary to include
EXCLUDED_COMPANIES = set(filter(None, os.getenv('EXCLUDED_COMPANIES', '').split(',')))
REQUIRED_KEYWORDS = set(filter(None, os.getenv('REQUIRED_KEYWORDS', '').split(',')))
EXCLUDED_KEYWORDS = set(filter(None, os.getenv('EXCLUDED_KEYWORDS', '').split(',')))

# SEEK API configuration
SEEK_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9,en-AU;q=0.8",
    "priority": "u=1, i",
    "sec-ch-ua": "\"Microsoft Edge\";v=\"131\", \"Chromium\";v=\"131\", \"Not_A Brand\";v=\"24\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "seek-request-brand": "seek",
    "seek-request-country": "AU",
    "x-seek-site": "Chalice"
}

SEEK_URL = "https://www.seek.com.au/api/jobsearch/v5/search"

async def setup_database():
    """Initialize the database."""
    print(f"🗄️ Setting up database at: {DATABASE_PATH}")
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Create jobs table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    company_id TEXT,
                    location TEXT,
                    salary TEXT,
                    work_type TEXT,
                    work_arrangement TEXT,
                    classification TEXT,
                    subclassification TEXT,
                    description TEXT,
                    bullet_points TEXT,
                    posted_date TEXT,
                    processed_date TEXT,
                    display_type TEXT,
                    is_featured INTEGER,
                    tags TEXT
                )
            ''')
            await db.commit()
            print("✓ Jobs table initialized")
    except Exception as e:
        print(f"❌ Error setting up database: {str(e)}")
        raise  # Re-raise to ensure the error is not silently caught

async def is_job_processed(db, job_id):
    """Check if a job has already been processed."""
    async with db.execute('SELECT id FROM jobs WHERE id = ?', (job_id,)) as cursor:
        return await cursor.fetchone() is not None

async def save_job(db, job):
    """Save a job to the database."""
    # Get company name from advertiser description if available
    company_name = job.get('advertiser', {}).get('description') or job.get('companyName', 'Unknown Company')
    company_id = job.get('advertiser', {}).get('id', '')
    
    # Get classification info
    classification = job.get('classifications', [{}])[0].get('classification', {}).get('description', 'Not Specified')
    subclassification = job.get('classifications', [{}])[0].get('subclassification', {}).get('description', 'Not Specified')
    
    # Get work type and arrangement
    work_types = job.get('workTypes', ['Not Specified'])
    work_type = ' & '.join(work_types) if work_types else 'Not Specified'
    
    # Get work arrangement from displayText if available, otherwise construct from data
    work_arrangement = job.get('workArrangements', {}).get('displayText', None)
    if not work_arrangement:
        arrangements = [arr.get('label', {}).get('text') for arr in job.get('workArrangements', {}).get('data', [])]
        work_arrangement = ', '.join(arrangements) if arrangements else 'Not Specified'
    
    # Convert bullet points and tags to JSON strings
    bullet_points = json.dumps(job.get('bulletPoints', [])) if job.get('bulletPoints') else None
    tags = json.dumps([tag['label'] for tag in job.get('tags', [])]) if job.get('tags') else None
    
    await db.execute('''
        INSERT INTO jobs (
            id, title, company, company_id, location, salary, work_type,
            work_arrangement, classification, subclassification, description,
            bullet_points, posted_date, processed_date, display_type,
            is_featured, tags
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        job['id'],
        job['title'],
        company_name,
        company_id,
        job['locations'][0]['label'],
        job.get('salaryLabel', ''),
        work_type,
        work_arrangement,
        classification,
        subclassification,
        job.get('teaser', ''),
        bullet_points,
        job['listingDate'],
        datetime.now().isoformat(),
        job.get('displayType', ''),
        1 if job.get('isFeatured', False) else 0,
        tags
    ))
    await db.commit()

async def get_job_stats():
    """Get statistics about processed jobs."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        stats = {}
        
        # Get total jobs count
        async with db.execute('SELECT COUNT(*) as count FROM jobs') as cursor:
            row = await cursor.fetchone()
            stats['total_jobs'] = row['count']
        
        # Get jobs by classification (handle NULL values)
        async with db.execute('''
            SELECT COALESCE(classification, 'Unspecified') as classification, COUNT(*) as count 
            FROM jobs 
            GROUP BY classification 
            ORDER BY count DESC 
            LIMIT 5
        ''') as cursor:
            stats['top_classifications'] = await cursor.fetchall()
        
        # Get jobs by company
        async with db.execute('''
            SELECT company, COUNT(*) as count 
            FROM jobs 
            GROUP BY company 
            ORDER BY count DESC 
            LIMIT 5
        ''') as cursor:
            stats['top_companies'] = await cursor.fetchall()
        
        # Get recent job count
        one_day_ago = (datetime.now() - timedelta(days=1)).isoformat()
        async with db.execute(
            'SELECT COUNT(*) as count FROM jobs WHERE posted_date > ?', 
            (one_day_ago,)
        ) as cursor:
            row = await cursor.fetchone()
            stats['jobs_last_24h'] = row['count']
        
        # Get work type distribution
        async with db.execute('''
            SELECT COALESCE(work_type, 'Unspecified') as work_type, COUNT(*) as count 
            FROM jobs 
            GROUP BY work_type 
            ORDER BY count DESC 
            LIMIT 5
        ''') as cursor:
            stats['work_types'] = await cursor.fetchall()
        
        return stats

def create_job_embed(job):
    """Create a Discord embed for a job listing."""
    embed = DiscordEmbed(
        title=job['title'],
        url=f"https://www.seek.com.au/job/{job['id']}",
        color='fd0585'
    )
    
    # Get company name from advertiser description if available, fallback to companyName
    company_name = job.get('advertiser', {}).get('description') or job.get('companyName', 'Unknown Company')
    
    # Add company logo if available
    if logo_url := job.get('branding', {}).get('serpLogoUrl'):
        embed.set_thumbnail(url=logo_url)
    
    # Add fields with custom emotes
    embed.add_embed_field(name=f"{EMOTE_COMPANY} Company", value=company_name, inline=True)
    embed.add_embed_field(name=f"{EMOTE_LOCATION} Location", value=job['locations'][0]['label'], inline=True)
    
    # Add work type and arrangement
    work_types = ' & '.join(job.get('workTypes', ['Not specified']))
    work_arrangements = job.get('workArrangements', {}).get('displayText', 'On-site')
    embed.add_embed_field(name=f"{EMOTE_WORK_TYPE} Work Type", value=f"{work_types} ({work_arrangements})", inline=True)
    
    if job.get('salaryLabel'):
        embed.add_embed_field(name=f"{EMOTE_SALARY} Salary", value=job['salaryLabel'], inline=False)
    
    if job.get('teaser'):
        embed.add_embed_field(name=f"{EMOTE_DESCRIPTION} Description", value=job['teaser'], inline=False)
    
    # Add bullet points if available
    if job.get('bulletPoints'):
        bullet_points = '\n• ' + '\n• '.join(job['bulletPoints'])
        embed.add_embed_field(name=f"{EMOTE_KEY_POINTS} Key Points", value=bullet_points, inline=False)
    
    # Add footer with posting time and any tags
    footer_text = f"Posted {job['listingDateDisplay']}"
    if job.get('tags'):
        tags = [tag['label'] for tag in job['tags']]
        footer_text += f" | {', '.join(tags)}"
    embed.set_footer(text=footer_text, icon_url="https://cdn.getminted.cc/seek.png")
    
    return embed

async def send_webhook(job, max_retries=3):
    """Send a Discord webhook with the job information."""
    for attempt in range(max_retries):
        try:
            webhook = DiscordWebhook(url=WEBHOOK_URL, content="", silent=True)
            embed = create_job_embed(job)
            webhook.add_embed(embed)
            response = webhook.execute()
            if response.status_code == 200:
                return True
            elif response.status_code == 429:  # Rate limit
                retry_after = int(response.headers.get('Retry-After', 5))
                print(f"⚠ Rate limited, waiting {retry_after} seconds...")
                await asyncio.sleep(retry_after)
                continue
            else:
                print(f"⚠ Webhook failed with status {response.status_code}")
        except Exception as e:
            print(f"⚠ Webhook error (attempt {attempt + 1}/{max_retries}): {str(e)}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    
    return False

async def fetch_jobs():
    """Fetch jobs from SEEK API."""
    params = {
        "siteKey": "AU-Main",
        "sourcesystem": "houston",
        "where": "Hobart TAS 7000",
        "page": "1",
        "sortmode": "ListedDate",  # Ensure we get newest listings first
        "pageSize": "22",
        "include": "seodata,joracrosslink,gptTargeting",
        "locale": "en-AU"
    }
    
    try:
        response = requests.get(SEEK_URL, headers=SEEK_HEADERS, params=params)
        response.raise_for_status()
        return response.json()['data']
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        return []

async def process_jobs():
    """Main job processing function."""
    print(f"⚡ Starting job check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    jobs = await fetch_jobs()
    if not jobs:
        print("✗ No jobs fetched or error occurred")
        return
    
    print(f"ℹ Found {len(jobs)} jobs")
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        new_jobs = 0
        filtered_jobs = 0
        for job in jobs:
            if not await is_job_processed(db, job['id']):
                if not should_process_job(job):
                    filtered_jobs += 1
                    continue
                    
                if await send_webhook(job):
                    await save_job(db, job)
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
            stats = await get_job_stats()
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
            # Print the full error traceback for debugging
            import traceback
            print(traceback.format_exc())

async def cleanup():
    """Perform cleanup operations."""
    print("✓ Cleanup completed")

async def main():
    """Main function."""
    global shutdown_flag
    
    print("\033[96m" + LOGO + "\033[0m")  # Print logo in cyan color
    print("🚀 Powering up The Seekret")
    print("ℹ Press Ctrl+C to exit gracefully")
    await setup_database()
    
    try:
        while not shutdown_flag:
            await process_jobs()
            
            # Break into smaller sleep intervals to check shutdown_flag more frequently
            for _ in range(CHECK_INTERVAL):
                if shutdown_flag:
                    break
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"\n❌ Error in main loop: {str(e)}")
    finally:
        await cleanup()
        print("👋 Goodbye!")

def should_process_job(job):
    """Determine if a job should be processed based on filters."""
    # Get company name from advertiser description if available
    company_name = job.get('advertiser', {}).get('description') or job.get('companyName', '')
    
    # Check excluded companies
    if company_name in EXCLUDED_COMPANIES:
        return False
    
    # Check salary if available
    if job.get('salaryLabel'):
        # Extract first number from salary string as a rough estimate
        import re
        salary_numbers = re.findall(r'\d+\.?\d*', job.get('salaryLabel', '0'))
        if salary_numbers and float(salary_numbers[0]) < SALARY_MIN:
            return False
    
    # Combine title and description for keyword checking
    text_to_check = f"{job['title']} {job.get('teaser', '')}".lower()
    
    # Check required keywords
    if REQUIRED_KEYWORDS and not any(keyword.lower() in text_to_check for keyword in REQUIRED_KEYWORDS):
        return False
    
    # Check excluded keywords
    if any(keyword.lower() in text_to_check for keyword in EXCLUDED_KEYWORDS):
        return False
    
    return True

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Handle Ctrl+C gracefully 