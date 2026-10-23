# Фотографии для сайта

Файл собирается автоматически (`node sayt/build.mjs`).

**Как добавить фото.** Положите файл в папку `sayt/foto/` по нужному пути (.jpg, .jpeg, .png или .webp), затем:

```
python3 sayt/tools/foto.py && node sayt/build.mjs
```

Фото уменьшится и сожмется в WebP в нескольких размерах. Присылайте исходники в максимальном качестве, длинная сторона от 2400 px.

**Галерея проекта** — папка `sayt/foto/proekty/<проект>/galereya/`. Сколько файлов положите, столько кадров будет на странице проекта, по порядку имен. Как только в папке появляется хотя бы одно фото, у проекта появляется своя страница.

## Проекты

| Проект | Папка | Кадров | Страница |
|---|---|---|---|
| Квартира на Плющихе | `foto/proekty/plushiha/galereya/` | 43 | ✅ есть |
| Квартира на Ильинке | `foto/proekty/ilinka/galereya/` | 33 | ✅ есть |
| Частная резиденция в Завидово | `foto/proekty/zavidovo/galereya/` | 0 | 🔴 нужны фото |
| ЖК Маленькая Франция | `foto/proekty/france/galereya/` | 0 | 🔴 нужны фото |
| Ресторан Sobremesa (Дубай) | `foto/proekty/dubai/galereya/` | 0 | 🔴 нужны фото |
| Загородная резиденция в Репино | `foto/proekty/repino1/galereya/` | 0 | 🔴 нужны фото |
| ЖК Фамилия | `foto/proekty/familia/galereya/` | 0 | 🔴 нужны фото |
| ЖК Диадема | `foto/proekty/diadema/galereya/` | 0 | 🔴 нужны фото |
| ЖК Hovard House | `foto/proekty/fontanka/galereya/` | 0 | 🔴 нужны фото |
| Ресторан INNER | `foto/proekty/inner/galereya/` | 0 | 🔴 нужны фото |
| Частная резиденция в Комарово | `foto/proekty/komarovo/galereya/` | 0 | 🔴 нужны фото |
| Ресторан Il Capitas | `foto/proekty/capitas/galereya/` | 0 | 🔴 нужны фото |
| Квартира в Москве | `foto/proekty/rymor/galereya/` | 0 | 🔴 нужны фото |
| Загородный дом в Оголатово | `foto/proekty/ogolatovo/galereya/` | 0 | 🔴 нужны фото |
| Частная резиденция в Озерках | `foto/proekty/ozerki/galereya/` | 0 | ⚪ после съемки |
| Частная резиденция в Репино (2) | `foto/proekty/repino2/galereya/` | 0 | ⚪ после съемки |
| Офис на Захарьевской | `foto/proekty/zahar/galereya/` | 0 | ⚪ после съемки |
| Квартира на Тружеников | `foto/proekty/truzhenikov/galereya/` | 0 | ⚪ после съемки |
| Частная резиденция в Репино (3) | `foto/proekty/repino3/galereya/` | 0 | ⚪ после съемки |
| ЖК Лотос | `foto/proekty/lotos/galereya/` | 0 | ⚪ после съемки |
| ЖК Октавия | `foto/proekty/oktavia/galereya/` | 0 | ⚪ после съемки |

## Общие места сайта

Кадры для первого экрана, меню, контактов и страницы «Мастерская» задаются в `content/site.mjs` → `site.photos`, для раздела «Что мы делаем» — в `crafts`. Сейчас там стоят визуализации Плющихи и Ильинки.
