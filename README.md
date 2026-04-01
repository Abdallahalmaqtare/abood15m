# Aboud Trading Bot v1.0

## 🤖 Pocket Option Signal Bot for Telegram

A complete automated trading signal system that:
- Generates CALL/PUT signals using TradingView indicators
- Sends signals to a Telegram channel before trade entry
- Implements 2-minute signal confirmation logic
- Automatically checks trade results after 15 minutes
- Maintains Win/Loss statistics
- Sends daily performance reports
- Includes admin control panel

## Architecture

```
TradingView (Pine Script)
    ↓ Webhook Alert
Render Server (Python/Flask)
    ↓ Signal Manager (2-min confirmation)
    ↓ Price Service (result checking)
Telegram Channel
    ↓ Signals + Results + Reports
```

## Trading Strategy

- **Pairs:** EURUSD, USDJPY, USDCHF
- **Timeframe:** 15 minutes
- **Indicators:**
  - EMA 20/50 (Trend Direction)
  - RSI 14 (Momentum)
  - Supertrend 10,3 (Trend Confirmation)
  - ADX 14 (Trend Strength)
  - ATR Candle Quality Filter

## Setup Instructions

### 1. TradingView Setup
1. Open TradingView chart for EURUSD (15-minute)
2. Go to Pine Editor → paste `pinescript_indicator.pine`
3. Click "Add to Chart"
4. Set up Alert:
   - Click "Alerts" → "Create Alert"
   - Condition: "Aboud Trading 15M Signal Generator"
   - Select: "Any alert() function call"
   - Webhook URL: `https://your-render-app.onrender.com/webhook`
   - Click "Create"
5. Repeat for USDJPY and USDCHF charts

### 2. Render Deployment
1. Push code to GitHub
2. Connect GitHub repo to Render
3. Set environment variables in Render dashboard
4. Deploy

### 3. Environment Variables (Render)
| Variable | Description |
|----------|-------------|
| TELEGRAM_BOT_TOKEN | Bot token from @BotFather |
| TELEGRAM_CHAT_ID | Channel ID (starts with -100) |
| ADMIN_USER_IDS | Your Telegram user ID |
| WEBHOOK_SECRET | Must match Pine Script |
| PORT | 10000 (default) |

## Admin Commands

| Command | Description |
|---------|-------------|
| /start | Initialize bot |
| /help | Show all commands |
| /stats | View statistics |
| /daily | Today's report |
| /enable | Enable signals |
| /disable | Disable signals |
| /reset | Reset all stats |
| /status | Bot status |
| /pairs | Active pairs |

## Files Structure

```
aboud-trading-bot/
├── main.py                  # Main entry point
├── config.py                # Configuration
├── database.py              # SQLite operations
├── signal_manager.py        # Signal confirmation logic
├── telegram_sender.py       # Telegram message sender
├── admin_bot.py             # Admin control commands
├── messages.py              # Message formatting
├── price_service.py         # Forex price fetching
├── pinescript_indicator.pine # TradingView indicator
├── requirements.txt         # Python dependencies
├── render.yaml              # Render deployment config
├── .env.example             # Environment template
└── README.md                # This file
```
