# АРХИВУД Проекты — приложение (прототип 1, 03.11.2026)

Опубликовано: https://claude.ai/artifact/8WwDpTnsgdqTh3hSGr6TBV (владелец доволен).
Один файл `index.html`, данные встроены.

## Сборка
```
cd build
python3 data.py karkas.json data.json   # karkas.json — разметка каталога Диска (1964 файла → 605 документов)
python3 build.py                        # → ../index.html
```
Проверка: `node test/run.mjs` (Playwright, скриншоты 1440 и 390 px).

## Источники
- `dokumenty/specifikaciya-prilozheniya.md` — процесс, модель данных, 9 экранов, 10 правил (по журналам Диска).
- `dokumenty/issledovanie-prilozhenie.md` — как это делают Procore/ACC/ISO 19650.
- `dokumenty/inventar-diska.md` — инвентаризация Диска.
- Цифры и расхождения (партии, сроки платежей, статус договора) вписаны в `build/body.html`/`data.py` из журналов на 03.11 — их нужно сверять с журналами.

## Ограничения прототипа
Состояние в памяти страницы (сбрасывается), «Отправить» ничего не шлёт, содержимого файлов нет, позиции неполные, статусы по правилам имён.
