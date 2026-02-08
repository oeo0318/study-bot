# Study Bot

A Discord bot for studying with AI-powered quiz generation and learning support.

## Features

- 📝 AI-generated quiz questions with explanations
- 📅 Study planning and homework management
- 💬 Supportive chat for study-related stress
- 📚 Knowledge base integration (JSON/PDF support)

## Requirements

- Python 3.13+
- Discord Bot Token
- OpenRouter API Key

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_discord_token
   OPENROUTER_API_KEY=your_openrouter_key
   ```

## Usage

Start the bot:
```bash
python ./bot/study.py
```

Start upload webui:
```bash
streamlit run ./upload/app.py
```

## Project Structure

```
bot/           # Bot source code
json_knowledge/ # Knowledge base files
upload/        # File upload handling
```