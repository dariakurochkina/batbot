# BIOMED AI — CABT Telegram study bot

An independent study companion for the **AAMI Certified Associate in Biomedical Technology (CABT)** exam. It makes **original AI-generated practice questions** based on AAMI's published content outline. It is not affiliated with AAMI, and does not contain official, leaked, or verified exam questions.

## What it does

- Six exam domains, with full 100-question, 120-minute mock exam distributed **24 / 23 / 16 / 14 / 13 / 10** according to the approximate 2026 CABT outline.
- 5, 10, or 20-question quizzes. Domain-specific 10-question practice.
- Questions stored in SQLite; `/seed 300`, `/seed 1000`, etc. expands the reusable bank (each generation uses billed OpenAI API requests).
- Detailed feedback after each practice answer; mock answers remain hidden until completion.
- AI mini-lessons, ask-anything tutor, mistake review, weak domains, and performance by domain.
- Open to anyone who finds the bot; progress is tracked separately for each Telegram user.

## Step-by-step setup

### 1. Create a NEW Telegram bot

1. In Telegram open **@BotFather**.
2. Send `/newbot`.
3. Choose a display name such as `BIOMED AI | CABT Tutor`.
4. Choose a unique username ending in `bot`, such as `biomed_fahim_study_bot` if available.
5. Copy the new **bot token** privately. Do not paste it into chat or commit it to GitHub.

### 2. Obtain an OpenAI API key

1. Open https://platform.openai.com/api-keys.
2. Create an API key in the appropriate project.
3. Add API billing/credits as needed at https://platform.openai.com/settings/organization/billing.
4. API usage is **not included** in ChatGPT Plus or Railway's hosting subscription.
5. Store the key only in Railway Variables, never inside files.

A separate key for this bot is recommended, so API usage and spending can be tracked separately. Set billing limits / alerts in OpenAI's platform.

### 3. Create a new GitHub repository

1. Go to https://github.com/new.
2. Name it `biomed-ai-cabt`, and choose **Private**.
3. Create the repository.
4. Upload `bot.py`, `requirements.txt`, `Procfile`, and `README.md` from this folder. **Do not upload .env with actual secrets.**
5. Commit the files.

### 4. Deploy as a new Railway project

1. Open https://railway.com/dashboard and select **New Project** → **Deploy from GitHub Repo**.
2. Authorize GitHub if prompted and select `biomed-ai-cabt`.
3. Set the service **Start Command** to `python bot.py` if Railway does not pick up the Procfile automatically.
4. Under **Variables**, create:

   | Name | Value |
   | --- | --- |
   | `TELEGRAM_BOT_TOKEN` | Your **new** BotFather token |
   | `OPENAI_API_KEY` | Your OpenAI API key |
   | `OPENAI_MODEL` | `gpt-4.1-mini` |
   | `DATABASE_PATH` | `/data/biomed.sqlite` (after attaching a persistent Railway volume at `/data`) |

5. **Attach a Railway Volume to the bot service, mounted at `/data`**, before starting to accumulate questions. This is essential for retaining the question bank, attempts, and progress across redeploys. If you cannot attach a volume yet, omit `DATABASE_PATH` temporarily; data then live on ephemeral disk and may disappear when redeployed.
6. Apply/Deploy the variables. Under **Deployments**, check for a successful, running service; under **Logs**, look for errors.

**Only one instance/replica of the polling bot should run at a time** for a given Telegram token.

### 5. Use it on Telegram

1. Open your new bot and send `/start`.
2. Press **📚 Study a Topic** for mini-lessons or **🧠 Quick Quiz** to begin immediately.
3. For a large bank, send `/seed 300`. Wait for it to finish. You can later use `/seed 1000` to target 1,000 total cached questions. The bot can continue adding new questions on demand.
4. Press **⏱ 100-Question Mock Exam** when the bank is sufficiently populated.
5. Use **🎯 Weak Areas**, **🔁 Review Mistakes**, and **📊 My Progress** after practice.
6. Send `/resume` to return to an interrupted quiz (provided the mock's 120 minutes have not expired).

## Troubleshooting

- **No response**: check Railway **Deploy Logs** and the Telegram token; verify the service is running, one instance only,.
- **OpenAI error / no questions**: verify `OPENAI_API_KEY`, API credit/billing, model access, and Railway logs.
- **Data disappears after deploy**: attach a persistent Railway Volume mounted at `/data` and set `DATABASE_PATH=/data/biomed.sqlite`.
- **Large seed runs cost money**: questions are generated with paid API calls. Start with `/seed 300` and monitor consumption. Generating a large bank can take a while; allow it to complete without starting another seed run.

**Public access and costs:** Anyone who finds the bot can use it, including the AI tutor and `/seed` command. Usage can incur OpenAI charges. Set spending alerts and monitor the API project.

## Safety and quality

AI-generated questions and explanations can contain factual or ambiguous errors. They are suitable for study practice **but are not authoritative**. For clinical safety and electrical testing, consult official AAMI resources, applicable regulations, and manufacturer guidance. The mock score is not a validated prediction of passing the certification exam.

AAMI exam: https://aami.org/certifications/cabt/
AAMI certifications / candidate handbook: https://aami.org/certifications/
