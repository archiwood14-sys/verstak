# Задание для Claude на Mac — запустить бота «АРХИВУД Документы»

Скопируйте весь текст ниже в новый чат Claude в папке archiwood_proekty.

---

Нужно СЕЙЧАС запустить Telegram-бота для поиска документов. Код уже написан и проверен (26 тестов): репозиторий archiwood14-sys/verstak, ветка claude/busy-clarke-bwpvj4, папка instrumenty/dokumenty-bot. Пиши мне коротко.

1. Через наш Telegram-доступ на этом Mac (~/archiwood_proekty/telegram) отправь @BotFather /mybots, получи список ботов. Сверь, какие используются на Mac (SBORSERVER/1_dvizhok/bot, launchd, процессы; ключи не показывать). Пришли короткую таблицу: бот — для чего — занят/свободен, предложи свободного и дождись моего выбора.
2. git clone --depth 1 -b claude/busy-clarke-bwpvj4 https://github.com/archiwood14-sys/verstak.git во временную папку, скопируй instrumenty/dokumenty-bot/* в ~/archiwood_proekty/dokumenty/. Токен выбранного бота возьми у @BotFather (/mybots → бот → API Token) и запиши в ~/archiwood_proekty/dokumenty/.klyuch_bota, chmod 600. Токен не выводи в чат и логи.
3. Проверь пути korni в nastroyki.json (корень ~/archiwood_proekty/Проекты на Google Диске). Запусти /opt/homebrew/bin/python3 katalog.py, потом katalog.py --otchet. Если много в «Прочее»/«Общее» — поправь правила и пересобери (--zanovo).
4. Запусти бота, установи launchd из ustanovka/*.plist (бот всегда, каталог раз в час). Напиши боту /start с моего аккаунта, впиши мой номер в nastroyki.json → Мансур. Проверь меню и поиск «договор раздоры».
5. Номера Юлии, Игоря Михайловича и Ольги впиши, когда они напишут боту /start (бот шлёт уведомление).
6. Итог мне — 3–4 строки: имя бота, что работает, как пользоваться.
