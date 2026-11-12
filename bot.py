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
