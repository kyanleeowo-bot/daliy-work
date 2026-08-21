# 排程機器人

用 Telegram 傳訊息記事,晚上固定時間讓 Gemini 幫你排出隔天行程並推播回來。

## 本機測試(可選,不會就跳過直接部署)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=你的token
export GEMINI_API_KEY=你的key
python bot.py
```

## 部署到 Railway

1. 到 [railway.app](https://railway.app) 新建一個 Project,選擇「Deploy from GitHub repo」
   （要先把這個資料夾推到你自己的 GitHub repo，或用 Railway 的「Empty Project」手動上傳也行）
2. 進入 Project 的 Variables 分頁，加入：
   - `TELEGRAM_BOT_TOKEN`
   - `GEMINI_API_KEY`
   - `PUSH_HOUR`（選填，預設 21，代表晚上9點）
3. 部署完成後，Railway 會自動安裝 requirements.txt 並執行 `python bot.py`
   （如果沒自動偵測，手動設定 Start Command 為 `python bot.py`）

## 第一次使用

1. 部署成功後，去 Telegram 找到你的 bot，傳 `/start`
2. Bot 會回覆你的 chat id，例如 `123456789`
3. 回到 Railway 的 Variables，新增一個 `CHAT_ID`，填入剛剛拿到的數字
4. 重新部署一次（讓新的環境變數生效）
5. 之後直接傳訊息給 bot 就會加入待辦事項，晚上會自動收到隔天排程

## 常用指令

- 直接傳文字 → 加入待辦事項
- `/list` → 看目前所有未完成事項
- `/done 3` → 把編號 3 標記完成
- `/plan` → 不用等到晚上，立刻要求重新排程一次

## 之後想擴充的方向

- 把 SQLite 換成 Railway 內建的 Postgres（重新部署後 SQLite 檔案可能會被清空，正式長期用建議換）
- 加入「刪除事項」指令
- 讓 Gemini 的 prompt 記住過去幾天完成了什麼，排程會更準
