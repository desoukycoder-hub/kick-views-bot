# 🎯 Kick Views Bot - Discord Bot

Discord bot for boosting Kick clips & videos views with credits system.

## Features
- 🎬 Boost Kick clip views
- 🎥 Boost Kick video views
- 💳 Credits system with ticket requests
- 📊 Real-time progress tracking
- ⚡ High-speed boost engine (350+ requests/second)
- 🛡️ Admin panel (add/remove credits, ban users)
- 🎫 Ticket system for credit requests

## Quick Setup

### Option 1: Auto Setup (Windows)
1. Download `setup.bat`
2. Double-click to run
3. It will install Python, libraries, and create config
4. Edit `config.json` with your bot token
5. Run `start.bat`

### Option 2: Manual Setup
```bash
# Install dependencies
pip install discord.py curl_cffi

# Edit config with your bot token
# Then run
python bot.py
python TEST.py
```

## Configuration

Edit `config.json`:
```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "server_name": "Your Server",
  "panel_channel_id": 0,
  "admin_ids": [123456789],
  "ticket_staff_roles": ["Staff", "Admin"]
}
```

## Project Structure
```
├── bot.py              # Main bot (panel + tickets)
├── TEST.py             # Boost bot (clips + videos)
├── credits.py          # Shared data manager
├── config.json         # Configuration (not in git)
├── config.example.json # Config template
├── rest_panel.py       # REST panel poster (market)
├── rest_test_panel.py  # REST panel poster (clips)
├── rest_videos_panel.py# REST panel poster (videos)
├── setup.bat           # Auto installer
├── start.bat           # Start both bots
├── stop.bat            # Stop both bots
└── .gitignore
```

## Requirements
- Python 3.12+
- discord.py
- curl_cffi

## License
Private project
