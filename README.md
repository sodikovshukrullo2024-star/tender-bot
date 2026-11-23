# Tender Bot 🤖

Watches **xarid.uzex.uz** auctions every 30 minutes and sends a Telegram
message when a robotics-related lot appears (robot, Arduino, LEGO, 3D printer, drone, …).

Runs for free on GitHub Actions. Your computer can be off.

## How it works
1. GitHub starts `tender_bot.py` every 30 minutes (`.github/workflows/check.yml`).
2. The bot opens the public auction list and reads new lots.
3. If a lot's products match a word in `KEYWORDS`, it messages you on Telegram.
4. It saves which lots it already checked in `seen_lots.json`, so it never repeats.

## Change what it looks for
Edit `KEYWORDS` near the top of `tender_bot.py` on github.com (pencil icon → Commit).

## Run it by hand / test
Actions tab → **Check tenders** → **Run workflow** (tick "test" to get only a test message).

## Secrets (Settings → Secrets and variables → Actions)
- `TELEGRAM_TOKEN`: bot token from @BotFather (required)
- `TELEGRAM_CHAT_ID`: optional; found automatically after you press Start in the bot
