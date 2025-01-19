![JobBot Banner](https://pub-8017706c57924d50b414b3be7f36d1aa.r2.dev/seekret_banner.png)

# The Seekret - SEEK Job Monitor

A versatile job monitoring solution that watches SEEK.com.au for new job postings and notifies you through Discord. Available in two flavors:

1. **CLI Version**: A lightweight command-line tool that monitors jobs and sends notifications via Discord webhooks
2. **Bot Version**: A full Discord bot implementation with interactive commands and rich features

## 🚀 Quick Start

1. Clone this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy the appropriate `.env.example` file from either `cli/` or `bot/` directory to create your `.env`
4. Run the desired version:
   ```bash
   # For CLI version
   python run.py cli
   
   # For Bot version
   python run.py bot
   ```

## 📂 Project Structure

```
jobbot/
├── run.py              # Central runner script
├── requirements.txt    # Combined dependencies
├── cli/               # CLI Implementation
│   ├── .env.example
│   ├── README.md
│   └── seek_jobs_monitor.py
└── bot/               # Bot Implementation
    ├── .env.example
    ├── README.md
    ├── bot.py
    └── seek_jobs_monitor.py
```

## 🔧 Configuration

Each version has its own configuration requirements. Please refer to the README.md in the respective directories:

- [CLI Version Documentation](cli/README.md)
- [Bot Version Documentation](bot/README.md)

## 🌟 Features

### CLI Version
- Lightweight and efficient
- Discord webhook notifications
- Job filtering capabilities
- Local SQLite database for job tracking

### Bot Version
- Full Discord bot integration
- Interactive commands
- Rich embed messages
- Advanced job filtering
- Customizable notifications
- Database persistence

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 