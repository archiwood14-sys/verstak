# Задание для Claude на Mac — запустить бота «АРХИВУД Документы»

Скопируйте весь текст ниже в новый чат Claude в папке archiwood_proekty.

---

Нужно запустить Telegram-бота для поиска документов. Код уже написан и проверен (67 тестов): репозиторий archiwood14-sys/verstak, ветка claude/busy-clarke-bwpvj4, папка instrumenty/dokumenty-bot. Пиши мне коротко.

1. **Сначала только список — и ждать.** Через наш Telegram-доступ на этом Mac (~/archiwood_proekty/telegram) отправь @BotFather /mybots, получи список ботов. Сверь, какие используются на Mac (SBORSERVER/1_dvizhok/bot, launchd, процессы; ключи не показывать). Пришли мне короткую таблицу: бот — для чего — занят/свободен. **Дальше не продолжай, пока я не отвечу, какого бота заменить.** Сам не выбирай.
2. После моего выбора: git clone --depth 1 -b claude/busy-clarke-bwpvj4 https://github.com/archiwood14-sys/verstak.git во временную папку, скопируй instrumenty/dokumenty-bot/* в ~/archiwood_proekty/dokumenty/. Прогони тесты: `cd ~/archiwood_proekty/dokumenty && /opt/homebrew/bin/python3 -m unittest test_bot` — все должны пройти. Токен выбранного бота возьми у @BotFather (/mybots → бот → API Token) и запиши в ~/archiwood_proekty/dokumenty/.klyuch_bota, chmod 600. Токен не выводи в чат и логи. Если этот бот раньше работал где-то ещё на Mac — останови тот процесс/launchd, иначе два опроса getUpdates будут мешать друг другу.
3. Проверь пути korni в nastroyki.json (корень ~/archiwood_proekty/Проекты на Google Диске). Запусти /opt/homebrew/bin/python3 katalog.py, потом katalog.py --otchet. Если много в «Прочее»/«Общее» — поправь правила и пересобери (--zanovo).
4. Установи launchd из ustanovka/: ru.archiwood.dokumenty.bot.plist (бот, всегда), ru.archiwood.dokumenty.katalog.plist (каталог, раз в час). Пути в plist — под пользователя этого Mac (проверь `echo $HOME`).
5. Составитель черновиков (кнопка «📝 Составить документ»): ustanovka/ru.archiwood.dokumenty.sostavitel.plist — раз в минуту запускает sostavitel.py, тот вызывает `claude -p`.
   - Найди `which claude` и проверь, что эта папка есть в PATH внутри plist (EnvironmentVariables → PATH); если нет — допиши.
   - Проверь, что claude залогинен и работает без терминала: `env -i HOME=$HOME PATH=<PATH из plist> claude -p "ответь одним словом: ок"` должен ответить «ок» (без запроса входа). Если просит логин — `claude` в терминале → /login, потом повтори.
   - Установи: cp в ~/Library/LaunchAgents/, `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ru.archiwood.dokumenty.sostavitel.plist`, проверь `launchctl print gui/$(id -u)/ru.archiwood.dokumenty.sostavitel` и sostavitel.err.log.
6. Напиши боту /start с моего аккаунта, впиши мой номер в nastroyki.json → Мансур. Проверь меню, поиск «договор раздоры», получение файла и «📝 Составить документ» (тестовая заявка → черновик должен прийти в чат).
7. Режим «одно окно»: бот сам удаляет прежние ответы и мои сообщения — в чате всегда только текущий экран и присланный файл; черновик остаётся до кнопки «✅ Готово — закрыть». Файлы приходят документами прямо в Telegram (повторно — мгновенно, по file_id). Проверь: два запроса подряд — в чате остаётся только последний ответ. Служебные okna.json и telegram_faily.json лежат рядом с katalog.db — не удалять.
8. Номера Юлии Евгеньевны и Игоря Михайловича впиши, когда они напишут боту /start (бот шлёт мне уведомление с номером). Больше никого не добавлять.
9. Итог мне — 3–4 строки: имя бота, что работает (поиск, файлы, составитель), как пользоваться.
