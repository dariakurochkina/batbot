"""BIOMED AI: independent Telegram CABT study assistant.
Original AI-generated questions based on the AAMI CABT public content outline.
Not affiliated with or endorsed by AAMI. No official exam questions.
"""
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger('biomed-ai')
# Avoid printing Telegram API URLs, which contain the bot token.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '').strip()
MODEL = os.getenv('OPENAI_MODEL', 'gpt-4.1-mini').strip()
DB_PATH = os.getenv('DATABASE_PATH', '/data/biomed.sqlite' if Path('/data').is_dir() else 'biomed.sqlite')

# Official AAMI CABT 2026 content outline percentages (approximate).
DOMAINS = {
    'reason': ('Reasoning & Problem Solving', 24, ['metric conversions', 'read tables and graphs', 'waveform readings', 'tolerances and measurements', 'service manuals and troubleshooting flowcharts', 'process of elimination']),
    'devices': ('Medical Devices & Patient Care', 23, ['ECG and EKG', 'pulse oximetry and EtCO2', 'noninvasive blood pressure monitors', 'infusion and syringe pumps', 'defibrillators', 'diagnostic tools', 'patient warming and cooling', 'hand tools', 'multimeters and biomedical test equipment']),
    'safety': ('Safety in Healthcare', 16, ['lockout/tagout', 'safety data sheets', 'microshock and macroshock', 'electrical hazards', 'infection prevention', 'PPE and universal precautions', 'defibrillator and imaging safety', 'medical gas and hazard symbols']),
    'electric': ('Electricity & Electronics', 14, ['Ohm law and calculations', 'series and parallel simple circuits', 'alternating and direct current', 'fuses and circuit breakers', 'capacitors and transformers', 'ground and electrical safety', 'ESD and basic wiring', 'open and short circuits']),
    'it': ('Healthcare Information Technology', 13, ['computer hardware and operating systems', 'USB and network connectors', 'LAN WAN VPN VLAN', 'Wi-Fi and Bluetooth', 'network troubleshooting', 'HIPAA and protected health information', 'phishing and cybersecurity', 'EMR device integration']),
    'anatomy': ('Anatomy & Physiology', 10, ['heart and circulation', 'respiratory system', 'brain and nervous system', 'kidneys', 'skin and blood', 'interaction of organ systems']),
}
ORDER = list(DOMAINS)
MAIN = Markup([
    [Button('📚 Study a Topic', callback_data='topics'), Button('🧠 Quick Quiz', callback_data='quick')],
    [Button('🎯 Weak Areas', callback_data='weak'), Button('🔁 Review Mistakes', callback_data='review')],
    [Button('⏱ 100-Question Mock Exam', callback_data='mock'), Button('📊 My Progress', callback_data='stats')],
    [Button('💬 Ask AI Tutor', callback_data='tutor'), Button('🗃 Question Bank', callback_data='bank')],
])

def database():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, domain TEXT, topic TEXT, stem TEXT, options TEXT, correct INTEGER, explanation TEXT, signature TEXT UNIQUE, created INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, uid INTEGER, qid INTEGER, correct INTEGER, created INTEGER)')
    c.execute('CREATE INDEX IF NOT EXISTS attempts_uid ON attempts(uid, qid)')
    c.execute('CREATE TABLE IF NOT EXISTS sessions (uid INTEGER PRIMARY KEY, mode TEXT, ids TEXT, pos INTEGER, score INTEGER, started INTEGER, deadline INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS user_state (uid INTEGER PRIMARY KEY, mode TEXT, topic TEXT)')
    c.commit()
    return c

def keyboard(rows):
    return Markup([[Button(label, callback_data=key) for label, key in row] for row in rows])

def safe_json(s):
    s = s.strip()
    s = re.sub(r'^```(?:json)?\s*|\s*```$', '', s)
    return json.loads(s)

async def ai(system, content, max_tokens=1300, temperature=.55):
    if not OPENAI_KEY:
        raise RuntimeError('OPENAI_API_KEY is missing from Railway Variables')
    payload = {'model': MODEL, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}], 'temperature': temperature, 'max_tokens': max_tokens}
    async with httpx.AsyncClient(timeout=httpx.Timeout(85, connect=12)) as client:
        response = await client.post('https://api.openai.com/v1/chat/completions', json=payload, headers={'Authorization': 'Bearer ' + OPENAI_KEY})
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()

def question_signature(stem):
    stem = ' '.join(re.findall(r'[a-z0-9]+', stem.lower()))
    return hashlib.sha256(stem.encode('utf-8')).hexdigest()

async def generate(domain, amount=8):
    """Generate, validate structure, and cache original practice questions."""
    name, _, topics = DOMAINS[domain]
    with database() as c:
        previous = [r['stem'][:110] for r in c.execute('SELECT stem FROM questions WHERE domain=? ORDER BY id DESC LIMIT 35', (domain,))]
    topic = random.choice(topics)
    sys_prompt = (
        'You are a meticulous instructor creating ORIGINAL entry-level CABT biomedical technology practice questions. '
        'Align only to the public AAMI CABT content outline. DO NOT claim questions are official, copied, or licensed AAMI exam items. '
        'Generate clinically and electrically correct, unambiguous, self-contained four-choice multiple-choice questions. '
        'Do NOT invent standards, regulatory thresholds, or device model specifications. '
        'Include some calculations and plausible troubleshooting scenarios when relevant. '
        'One and only one correct answer. No all/none-of-the-above. No diagrams, pictures, external passages, or unspecified tables. '
        'Return ONLY JSON: {"questions":[{"question":"...","options":["...","...","...","..."],"correct":0,"explanation":"Why the answer is correct and why common alternative is wrong."}]}. '
        'correct is a zero-based integer 0..3. Keep every explanation concise but technically solid.'
    )
    request = json.dumps({'domain': name, 'topic_focus': topic, 'count': amount, 'previous_to_avoid': previous, 'difficulty': 'mix of foundational, applied, and moderate'}, ensure_ascii=False)
    raw = await ai(sys_prompt, request, max_tokens=min(5500, 400 + amount * 480), temperature=.75)
    obj = safe_json(raw)
    added = 0
    for entry in obj.get('questions', []):
        try:
            stem = str(entry['question']).strip()
            opts = entry['options']
            index = entry['correct']
            explanation = str(entry['explanation']).strip()
            if not isinstance(opts, list) or len(opts) != 4 or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 4:
                continue
            opts = [str(o).strip() for o in opts]
            if not (25 <= len(stem) <= 1200 and 15 <= len(explanation) <= 1600 and all(1 <= len(o) <= 350 for o in opts) and len(set(o.lower() for o in opts)) == 4):
                continue
            correct_text = opts[index]
            random.shuffle(opts)
            index = opts.index(correct_text)
            with database() as c:
                result = c.execute('INSERT OR IGNORE INTO questions(domain,topic,stem,options,correct,explanation,signature,created) VALUES(?,?,?,?,?,?,?,?)', (domain, topic, stem, json.dumps(opts), index, explanation, question_signature(stem), int(time.time())))
                added += result.rowcount
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            LOG.exception('Discarding invalid question')
    return added

async def ensure_questions(domain, count):
    with database() as c:
        have = c.execute('SELECT COUNT(*) FROM questions WHERE domain=?', (domain,)).fetchone()[0]
    # Max 4 attempts to fill normal quizzes; seed command handles bulk generation.
    for _ in range(4):
        if have >= count:
            break
        n = await generate(domain, min(10, max(5, count-have)))
        have += n
        if n == 0:
            break
    return have

def select_questions(uid, domain, n, exclude=()):
    blocked = set(exclude)
    with database() as c:
        rows = c.execute('''SELECT q.id, COUNT(a.id) AS views FROM questions q
            LEFT JOIN attempts a ON a.qid=q.id AND a.uid=?
            WHERE q.domain=? GROUP BY q.id ORDER BY views ASC, RANDOM()''', (uid, domain)).fetchall()
    return [r['id'] for r in rows if r['id'] not in blocked][:n]

def get_session(uid):
    with database() as c:
        return c.execute('SELECT * FROM sessions WHERE uid=?', (uid,)).fetchone()

def set_state(uid, mode, topic=''):
    with database() as c:
        c.execute('INSERT OR REPLACE INTO user_state VALUES (?,?,?)', (uid, mode, topic))

def state(uid):
    with database() as c:
        return c.execute('SELECT mode,topic FROM user_state WHERE uid=?', (uid,)).fetchone()

async def send_text(chat, text, markup=None):
    if len(text) <= 4000:
        return await chat.send_message(text, reply_markup=markup)
    for i in range(0, len(text), 4000):
        await chat.send_message(text[i:i+4000], reply_markup=markup if i+4000 >= len(text) else None)

async def show_question(uid, chat):
    s = get_session(uid)
    if not s:
        return await send_text(chat, 'No active quiz. Choose a study mode.', MAIN)
    if s['deadline'] and int(time.time()) >= s['deadline']:
        return await finish(uid, chat, timed_out=True)
    ids = json.loads(s['ids'])
    if s['pos'] >= len(ids):
        return await finish(uid, chat)
    with database() as c:
        q = c.execute('SELECT * FROM questions WHERE id=?', (ids[s['pos']],)).fetchone()
    if q is None:
        return await finish(uid, chat)
    options = json.loads(q['options'])
    prefix = f"{'⏱ MOCK EXAM' if s['mode']=='mock' else '🧠 PRACTICE'} — {s['pos']+1}/{len(ids)}\n{DOMAINS[q['domain']][0]}"
    if s['mode'] == 'mock':
        remaining = max(0, (s['deadline'] - int(time.time())) // 60)
        prefix += f'\nAbout {remaining} min remaining'
    question = prefix + '\n\n' + q['stem'] + '\n\n' + '\n'.join(f'{chr(65+i)}. {option}' for i, option in enumerate(options))
    await send_text(chat, question, keyboard([[(chr(65+i), f'ans:{s["pos"]}:{i}') for i in range(4)], [('🏠 Exit / Main Menu', 'home')]]))

async def begin(uid, chat, kind, domain=None, n=10):
    await send_text(chat, 'Preparing your questions…')
    try:
        if kind == 'review':
            with database() as c:
                ids = [r[0] for r in c.execute('''SELECT qid FROM attempts WHERE uid=? AND correct=0 GROUP BY qid ORDER BY MAX(created) DESC LIMIT ?''', (uid, n))]
            if not ids:
                return await send_text(chat, 'No missed questions saved yet. Try a quiz first.', MAIN)
        else:
            target = {key: (DOMAINS[key][1] if kind == 'mock' else (n if domain == key else 0)) for key in ORDER}
            if kind in ('quick', 'mixed'):
                target = {key: 0 for key in ORDER}
                for _ in range(n):
                    key = random.choices(ORDER, weights=[DOMAINS[k][1] for k in ORDER])[0]
                    target[key] += 1
            ids = []
            for key, needed in target.items():
                if not needed:
                    continue
                await ensure_questions(key, needed)
                selection = select_questions(uid, key, needed, ids)
                if len(selection) < needed:
                    if kind == 'mock':
                        return await send_text(chat, f'Only {len(selection)}/{needed} questions available in {DOMAINS[key][0]}. Run /seed 300 to expand the bank, then start the full mock exam.', MAIN)
                    LOG.warning('Only %d/%d available for %s', len(selection), needed, key)
                ids.extend(selection)
            random.shuffle(ids)
        if not ids:
            return await send_text(chat, 'No questions are available. Check the OpenAI key and Railway logs.', MAIN)
        now = int(time.time())
        deadline = now + 7200 if kind == 'mock' else 0
        with database() as c:
            c.execute('INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?)', (uid, kind, json.dumps(ids), 0, 0, now, deadline))
        set_state(uid, '')
        await show_question(uid, chat)
    except Exception:
        LOG.exception('Cannot start quiz')
        await send_text(chat, 'Question generation failed. Verify OPENAI_API_KEY, billing, and Railway logs.', MAIN)

async def answer(uid, chat, pos, choice):
    s = get_session(uid)
    if not s or s['pos'] != pos or not 0 <= choice <= 3:
        return await send_text(chat, 'That question is no longer active. Use /resume.', MAIN)
    if s['deadline'] and time.time() >= s['deadline']:
        return await finish(uid, chat, timed_out=True)
    ids = json.loads(s['ids'])
    with database() as c:
        q = c.execute('SELECT * FROM questions WHERE id=?', (ids[pos],)).fetchone()
        right = int(choice == q['correct'])
        c.execute('INSERT INTO attempts(uid,qid,correct,created) VALUES (?,?,?,?)', (uid, q['id'], right, int(time.time())))
        c.execute('UPDATE sessions SET pos=pos+1,score=score+? WHERE uid=?', (right, uid))
    if s['mode'] == 'mock':
        # No answer feedback until mock exam completes.
        return await show_question(uid, chat)
    explanation = ('✅ Correct!' if right else f'❌ Not quite. Correct answer: {chr(65+q["correct"])} — {json.loads(q["options"])[q["correct"]]}')
    explanation += '\n\n' + q['explanation']
    await send_text(chat, explanation, keyboard([[('➡️ Next Question', 'next')], [('💬 Explain More', f'explain:{q["id"]}')], [('🏠 Main Menu', 'home')]]))

async def finish(uid, chat, timed_out=False):
    s = get_session(uid)
    if not s:
        return await send_text(chat, 'No active session.', MAIN)
    ids = json.loads(s['ids'])
    total_answered = s['pos']
    result = f"{'⏱ Time expired! ' if timed_out else ''}Session complete!\nScore: {s['score']}/{len(ids)} ({s['score'] / len(ids):.0%})\nAnswered: {total_answered}/{len(ids)}"
    if s['mode'] == 'mock':
        result += '\n\nThis is an original practice exam, not an official AAMI test or an official pass prediction.'
    with database() as c:
        c.execute('DELETE FROM sessions WHERE uid=?', (uid,))
    await send_text(chat, result, MAIN)

async def progress(uid, chat):
    with database() as c:
        total = c.execute('SELECT COUNT(*) FROM attempts WHERE uid=?', (uid,)).fetchone()[0]
        lines = ['📊 YOUR PROGRESS', f'Questions answered: {total}', '']
        for code, (name, _, _) in DOMAINS.items():
            row = c.execute('''SELECT COUNT(*), COALESCE(SUM(a.correct),0) FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.uid=? AND q.domain=?''', (uid, code)).fetchone()
            lines.append(f'{name}: {row[1]}/{row[0]} ({row[1]/row[0]:.0%})' if row[0] else f'{name}: not practiced yet')
    await send_text(chat, '\n'.join(lines) + '\n\nAccuracy reflects practice attempts, not an official AAMI passing score.', MAIN)

async def weak(uid, chat):
    with database() as c:
        rows = c.execute('''SELECT q.domain, COUNT(*) AS n, SUM(a.correct) AS hits FROM attempts a JOIN questions q ON q.id=a.qid WHERE a.uid=? GROUP BY q.domain HAVING COUNT(*)>=3 ORDER BY (1.0*SUM(a.correct)/COUNT(*)) ASC''', (uid,)).fetchall()
    if not rows:
        return await send_text(chat, 'Complete a few quizzes first so I can identify weak areas.', MAIN)
    rows = list(rows)
    buttons = [[(f'{DOMAINS[r["domain"]][0]} — {r["hits"]}/{r["n"]}', f'domain:{r["domain"]}')] for r in rows]
    buttons.append([('🏠 Home', 'home')])
    await send_text(chat, '🎯 Weak areas first. Tap a domain to practice:', keyboard(buttons))

async def lesson(uid, chat, domain):
    set_state(uid, 'lesson', domain)
    await send_text(chat, 'Creating a focused lesson…')
    name, _, topics = DOMAINS[domain]
    try:
        content = await ai('You are an accurate CABT exam-prep teacher. Create a concise, practical beginner-friendly lesson. Use specific biomedical equipment examples. Emphasize basic principles and safe practice, not unsourced standards or numerical safety limits. No diagnosis, patient-specific advice, or risky repair instructions. Finish with 3 quick recall points. Write in clear English.', f'Domain: {name}. Select one important focus from: {", ".join(topics)}. 350-500 words.', 1100)
        await send_text(chat, '📚 ' + name + '\n\n' + content, keyboard([[('🧠 Practice This Domain', f'domain:{domain}')], [('📚 Other Topics', 'topics')], [('🏠 Home', 'home')]]))
    except Exception:
        LOG.exception('Lesson failed')
        await send_text(chat, 'Could not load the lesson. Check API settings.', MAIN)

async def tutor(uid, chat, question):
    history_context = ''
    try:
        result = await ai('You are BIOMED AI, a patient and technically precise English-language tutor for AAMI CABT exam preparation. Explain basic biomedical technology, not medical treatment. Keep explanations accurate, concise, and grounded in introductory biomedical practices. When unsure, say so, and recommend verifying against AAMI content outlines or equipment manufacturer instructions. Never claim access to real AAMI examination questions. Include a small conceptual example when useful.', question + history_context, 900)
        await send_text(chat, '💬 ' + result + '\n\nAsk another question, or /start for the menu.')
    except Exception:
        LOG.exception('Tutor failed')
        await send_text(chat, 'AI tutor is unavailable. Check your OpenAI API key and billing.', MAIN)

async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log metadata only, never message content or API credentials."""
    LOG.info('Incoming Telegram update: id=%s kind=%s', update.update_id,
             'message' if update.effective_message else 'callback/other')


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('✅ BIOMED AI is online. Telegram commands work. Version: diagnostic-2')


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    LOG.error('Unhandled Telegram error: %s', context.error, exc_info=context.error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    LOG.info('Start command received from user ID %s', uid)
    set_state(uid, '')
    await send_text(update.effective_chat, '👋 Welcome to BIOMED AI!\n\nStudy for the AAMI CABT exam with original practice questions, focused lessons, unlimited bank expansion, and an AI tutor.\n\nNo placement test required. Choose where to start.\n\nNot affiliated with AAMI.', MAIN)

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(f'Your Telegram user ID: {update.effective_user.id}')

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_question(update.effective_user.id, update.effective_chat)

async def seed(uid, chat, target):
    if not OPENAI_KEY:
        return await send_text(chat, 'Add OPENAI_API_KEY in Railway Variables first.')
    with database() as c:
        current = c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    if current >= target:
        return await send_text(chat, f'Question bank already has {current} questions.', MAIN)
    await send_text(chat, f'🗃 Expanding the bank from {current} toward {target} original questions. This uses paid OpenAI API tokens. I will report progress here.')
    try:
        # Balanced supply according to AAMI's approximate domain weights.
        stalled = 0
        for cycle in range(max(20, (target-current)//5 + 30)):
            with database() as c:
                counts = {k: c.execute('SELECT COUNT(*) FROM questions WHERE domain=?', (k,)).fetchone()[0] for k in ORDER}
            total = sum(counts.values())
            if total >= target:
                break
            domain = max(ORDER, key=lambda k: target * DOMAINS[k][1] / 100 - counts[k])
            gained = await generate(domain, min(10, max(5, target-total)))
            stalled = stalled+1 if gained == 0 else 0
            if cycle % 5 == 4:
                await send_text(chat, f'Question bank: {total+gained}/{target}. Still generating…')
            if stalled >= 3:
                break
        with database() as c:
            total = c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
        await send_text(chat, f'✅ Question bank now contains {total} questions. AI-generated content should be checked for accuracy. You can run /seed 500 later to add more.', MAIN)
    except Exception:
        LOG.exception('Seeding failed')
        await send_text(chat, 'Question generation stopped due to an API or formatting error. Existing questions were saved. Check Railway logs and API credits.', MAIN)

async def seed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        target = int(context.args[0]) if context.args else 300
    except ValueError:
        return await send_text(update.effective_chat, 'Usage: /seed 300 (target total question count)')
    if not 20 <= target <= 20000:
        return await send_text(update.effective_chat, 'Choose a target between 20 and 20000, e.g. /seed 300. Higher targets use more paid API tokens.')
    if context.application.bot_data.get('seeding'):
        return await send_text(update.effective_chat, 'Question bank expansion is already running.')
    context.application.bot_data['seeding'] = True
    async def runner():
        try:
            await seed(uid, update.effective_chat, target)
        finally:
            context.application.bot_data['seeding'] = False
    context.application.create_task(runner())

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    chat = q.message.chat
    key = q.data
    try:
        if key == 'home':
            with database() as c:
                c.execute('DELETE FROM sessions WHERE uid=?', (uid,))
            set_state(uid, '')
            return await send_text(chat, 'Choose a study mode:', MAIN)
        if key == 'topics':
            return await send_text(chat, '📚 Choose a CABT domain:', keyboard([[(DOMAINS[d][0], f'lesson:{d}')] for d in ORDER] + [[('🏠 Home', 'home')]]))
        if key.startswith('lesson:'):
            return await lesson(uid, chat, key.partition(':')[2])
        if key.startswith('domain:'):
            return await begin(uid, chat, 'domain', key.partition(':')[2], 10)
        if key == 'quick':
            return await send_text(chat, '🧠 Choose quiz length:', keyboard([[('5 questions', 'quiz:5'), ('10 questions', 'quiz:10')], [('20 questions', 'quiz:20')], [('🏠 Home', 'home')]]))
        if key.startswith('quiz:'):
            return await begin(uid, chat, 'quick', n=int(key.split(':')[1]))
        if key == 'mock':
            return await send_text(chat, '⏱ FULL CABT PRACTICE EXAM\n100 original multiple-choice questions, 120 minutes, domain-weighted. Feedback appears at the end.\n\nPrepare at least 100 cached questions with /seed 300 for a smoother start.\n\nReady?', keyboard([[('Start 100-Question Exam', 'mock:start')], [('Cancel', 'home')]]))
        if key == 'mock:start':
            return await begin(uid, chat, 'mock')
        if key == 'review':
            return await begin(uid, chat, 'review', n=10)
        if key == 'weak':
            return await weak(uid, chat)
        if key == 'stats':
            return await progress(uid, chat)
        if key == 'bank':
            with database() as c:
                lines = [f'{DOMAINS[d][0]}: {c.execute("SELECT COUNT(*) FROM questions WHERE domain=?", (d,)).fetchone()[0]}' for d in ORDER]
            return await send_text(chat, '🗃 CACHED QUESTION BANK\n\n' + '\n'.join(lines) + '\n\nUse /seed 300 to build the first 300 questions. /seed 1000 expands toward 1,000 (paid API usage).', MAIN)
        if key == 'tutor':
            set_state(uid, 'tutor')
            return await send_text(chat, '💬 Ask me anything about CABT topics. For example: “Explain microshock vs macroshock” or “Teach me Ohm’s law.”\n\nUse /start to exit.')
        if key.startswith('ans:'):
            _, pos, choice = key.split(':')
            return await answer(uid, chat, int(pos), int(choice))
        if key == 'next':
            return await show_question(uid, chat)
        if key.startswith('explain:'):
            qid = int(key.partition(':')[2])
            with database() as c:
                question = c.execute('SELECT stem,options,correct,explanation FROM questions WHERE id=?', (qid,)).fetchone()
            if not question:
                return await send_text(chat, 'Could not find that question.', MAIN)
            await tutor(uid, chat, f'Explain in more depth why this answer is correct, with a relevant biomedical example. Question: {question["stem"]}. Options: {question["options"]}. Correct index: {question["correct"]}. Existing explanation: {question["explanation"]}')
            return await send_text(chat, 'Continue:', keyboard([[('➡️ Next Question', 'next')], [('🏠 Main Menu', 'home')]]))
    except Exception:
        LOG.exception('Callback error')
        await send_text(chat, 'Something went wrong. Please try /start and check Railway logs.', MAIN)

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    current = state(uid)
    if current and current['mode'] == 'tutor':
        return await tutor(uid, update.effective_chat, update.message.text[:2000])
    await send_text(update.effective_chat, 'Choose an option from the menu or tap Ask AI Tutor.', MAIN)

def main():
    if not TOKEN:
        raise RuntimeError('TELEGRAM_BOT_TOKEN missing')
    with database():
        pass
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, log_update), group=-1)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('ping', ping))
    app.add_handler(CommandHandler('id', id_command))
    app.add_handler(CommandHandler('resume', resume))
    app.add_handler(CommandHandler('seed', seed_command))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))
    app.add_error_handler(error_handler)
    LOG.info('BIOMED AI diagnostic-2: starting Telegram polling')
    app.run_polling(drop_pending_updates=False)

if __name__ == '__main__':
    main()
