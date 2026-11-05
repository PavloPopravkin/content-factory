# WWG WOW как коммерческий tenant №1 (исследование 2026-11-05)

Режим: только чтение. Ничего не публиковал, не перезапускал, секретов не печатал. Считалось на S2.
Метки: [проверено] = видел файл/ответ сам; [не проверено] = вывод или чужая запись.

## 0. Главное

1. **Движок для WWG уже есть и уже запущен, и он не Postiz.** `server-root/DECISIONS.md:18-22` (2026-11-04): посты клиентов ведёт `server-root/scripts/autopost/` (engine.py, meta.py, gbp.py), WWG клиент №1; Postiz там прямо **отвергнут** (advisories, токены всех клиентов в одной веб-системе). Крон `*/10 engine.py wwg tick` стоит у pavel на S2 [проверено, `crontab -l`]. Это расходится с новым словом Pavel'я "всё через Postiz" и с `content-factory/DECISIONS.md` 2026-10-25 ("Postiz исполнителем за своим сервисом"). Нужен явный выбор Pavel'я (см. §7).
2. **Первый пост (одобренная карусель) уже в плане на сегодня:** `WWG-first-bathroom` 2026-11-05 11:00 Chicago, каналы fb+ig+gbp, 7 файлов, одобрение записано `grant by Pavel` 2026-11-04 08:49 (`~/autopost/wwg/approvals.json`, `engine.log`) с пометкой "Женя одобрил 04.11" в note слота [проверено]. Публиковать руками ещё раз нельзя: будет дубль.
3. **GBP-публикатор ADS стоит с 03.11** на неизвестном исходе POST: `publish.py` пишет `gbp-intent` и падает каждые 15 мин "unknown GBP POST outcome still unresolved: ads-2026-q4-03" (journal, 93 раза с 03.11) [проверено]. Тот же OAuth Pavel'я и тот же GBP-аккаунт `accounts/101549147125802464539` использует WWG `gbp.py`. Причина сбоя POST не залогирована (код намеренно не печатает тела, `publish.py:418`) [не проверено]. Риск: GBP-часть сегодняшнего поста WWG упадёт по той же причине.
4. **Шабат-гарды в двух движках разные.** ADS: консервативно "пятница с 09:30 Chicago и вся суббота" (`publish.py:96-108`). autopost: `steward.in_shabbat`, окно 06.11 начинается 16:28 UTC = 10:28 Chicago [проверено расчётом]. Слот `WWG-1106-sink` (рилс) стоит на пт 06.11 10:00 Chicago, запас 28 мин; по правилу ADS он был бы запрещён. CLAUDE.md: Pavel в Испании, город не указан, закат не угадывать.
5. **Число отзывов противоречиво.** `approved-business-facts.json` разрешает "100+ reviews across platforms" и запрещает "200+ reviews"; live-сайт отдаёт `aggregateRating reviewCount "200"` [проверено curl]; правило nikita#8 (`wwgwow/MANIFEST.md:27`) велит брать число из aggregateRating сайта; GBP имеет 45 отзывов (PLAN-SOCIAL-CONTENT.md, шаг 0). В текстах число отзывов пока не ставить.

## 1. Что уже согласовано (источники)

- План: `wwgwow/PLAN-SOCIAL-CONTENT.md` (30.10). Вариант B "один autopost на несколько клиентов" выбран и реализован 04.11. Темп: FB+IG 1 пост/день + 2 сторис, GBP 2/нед; окно 9-19 Chicago; шабат с day-1; сводка Жене раз в неделю (не сделана, `server-root/DEBT.md:5`).
- Факты: `wwgwow/.planning/facebook-pilot/approved-business-facts.json` (одобрил Yevhen Vechkanov 2026-09-11, tg msg 1257933/1257942). Разрешено: 5.0, "100+ reviews across platforms", 33 зоны, fully insured, background-checked, ID-verified, pay after clean, free re-clean 24 ч; цены от: standard $175, deep $255, move-in/out $255, recurring $125; телефон (224) 813-3131, `/book/`. Запрещено: "200+ reviews", "bonded", "31 cities", "deep from $175", "recurring from $123". Визуальные правила: без кепок, без джинсов, проф. инструмент, до/после без ретуши и в паре.
- Доп. правила (`wwgwow/MANIFEST.md:20-45`): до/после только одно место, одна точка, одна дистанция, доказательство к SHA (nikita#8, 03.11); баннеры с лицами одним вызовом от исходника; "99.99% bacteria" запрещено (`DEBT.md:137-141`).
- Одобренный первый пост: `wwgwow/outputs/social-first-post-20261030/` - `carousel/out/01-07.jpg` (1080x1350, `build.py`: 6 фото ванной + CTA-слайд с ценами $175/$255 и 6 пунктами), тексты `fb.txt`, `ig.txt`, `gbp.txt` (GBP без телефона, кнопка BOOK с `utm_source=google&utm_campaign=gbp`). Превью уходили Pavel'ю через @croscor_bot (`tg-sent.jsonl`, msg 60904-60930) [проверено].

## 2. Доступы (только имена)

| Что | Где | Статус |
|---|---|---|
| FB page 779251798602600 "wwG-wow Cleaning Services" | `META_ACCESS_TOKEN` (server-root .env), page-токен выводится в рантайме (`autopost/meta.py:135`) | GET работает [проверено]: 61 подписчик |
| IG 17841466335113394 @wwg_wow_cleaning_services | тот же page-токен | GET работает: 38 подписчиков, 62 медиа |
| GBP `locations/16157209681531178473` | `GOOGLE_PAVLO_OAUTH_CLIENT_ID/_CLIENT_SECRET/_REFRESH_TOKEN` (+`_REFRESH_TOKEN_PREV`); копия в `/secure/automation/ads-gbp-reviews/secret/gbp-oauth.env` | verified, 45 отзывов 5.0, постов 0 на 30.10 (план) [не перепроверял] |
| Meta app | `META_APP_ID`, `META_APP_SECRET`, `META_BUSINESS_ID` | есть |
| Postiz S2 | `POSTIZ_CROSCOR_API_KEY` | в Postiz S2 одна организация "Your Help UA", 3 канала (2 FB, 1 IG); **WWG в Postiz нет** [проверено SQL read-only] |
| Боты | `TG_CROSCOR_BOT_TOKEN` (@croscor_bot); токен @wwgwow_bot живёт в prod `.env` lead-engine | `FB_WWG_PAGE_ACCESS_TOKEN` нигде нет и не нужен |

## 3. Медиатека iCloud (`/secure/automation/wwg-content/icloud-20261104/originals/manifest.json`)

[проверено] 607 записей, все файлы на месте, 19.09 GB, даты 2022-06-01 ... 2026-10-22.

| Тип | Шт | Объём |
|---|---|---|
| JPEG | 235 | 0.59 GB |
| HEIC | 67 | 0.12 GB |
| PNG (скриншоты/баннеры) | 9 | 0.02 GB |
| MOV | 287 | 18.0 GB |
| MP4 | 9 | 0.37 GB |

- Итого 311 фото, 296 видео. По годам (фото/видео): 2022 62/1, 2023 14/3, 2024 157/122, 2025 76/115, 2026 2/55. Свежих фото 2026 почти нет, свежие видео есть.
- Ориентация: видео 277 вертикальных, 19 горизонтальных; фото 153 верт., 151 гориз., 7 квадрат. Видео 273 шт. 1920 по длинной стороне.
- ffprobe 10 случайных видео: 9.3-92.9 с, среднее 32.6 с; 9 x H.264 1080p (30 или 59.94 fps, AAC, 5-8 потоков с метаданными iPhone), 1 x HEVC 720x1280 с хэш-именем (похоже скачан из соцсети) [проверено]. Для рилсов нужен перекод (H.264 yuv420p, faststart, SAR 1:1) и обрезка до 15-60 с.
- Нет метаданных согласия, лиц, адресов клиентов. Сборщик autopost уже отсеивает вручную: лица/селфи, флаеры CHCH и "скидка 20%", джинсы, AI-ролик с роботом, коллажи (`~/autopost/wwg/build-last.log`).
- Копия для движка: `config.json` archive = `~/media/wwg/icloud-20261104` (есть на S2).

## 4. Видео из их FB/IG/TikTok

[проверено, Graph API GET] IG: 41 REELS, 7 CAROUSEL_ALBUM, 15 IMAGE; по годам 2024 4, 2025 29, 2026 30. FB: первая страница `/videos` 44 ролика (средняя длина 31.3 с, последние 2026-07), `/posts` 58 (2025 24, 2026 34). Последний пост страницы 17.07.2026 (план).
- Переиспользование через API своих же медиа: IG `media_url` у VIDEO, FB video `source` [не проверено, поля не запрашивал]. Это законный путь без скрейпинга. Часть из них, вероятно, дубли iCloud (HEVC 720x1280 в архиве).
- TikTok: хэндл не найден ни в репо, ни на сайте. На главной сайта нет ни одной ссылки на соцсети (нет `sameAs`) [проверено curl]. Нужен хэндл от Жени; скачивание своих роликов TikTok - yt-dlp по правилу CLAUDE.md.
- Перед повтором старого видео прогонять через те же правила фактов: в архиве уже был `1256948.mp4` с "99.99% bacteria" (`DEBT.md:141`).

## 5. Google Business: как публикуется и как "прокачать"

Как устроено сейчас:
- ADS: `publish.py:227-230` POST `mybusiness.googleapis.com/v4/{account}/{location}/localPosts`, `topicType STANDARD`, CTA `LEARN_MORE`, одно фото `sourceUrl`; OAuth refresh-token Pavel'я (`publish.py:152-164`); перед POST и после ищет такой же пост (summary + url), неизвестный исход не повторяет (`publish.py:233-247, 315`). Длина 80-1400 (`:87`). Таймер `ads-content-publisher.timer` каждые 15 мин до 2027-01-20.
- WWG: `autopost/gbp.py:70-83` тот же паттерн, CTA `BOOK`, лимит 1500.
- Postiz v2.25.3 имеет провайдер `gmb` (`libraries/nestjs-libraries/src/integrations/social/gmb.provider.ts`): scope `business.manage` (:47-50), одна картинка, видео запрещено (:62-75), до 1500 знаков, OAuth клиент `GOOGLE_GMB_CLIENT_ID || YOUTUBE_CLIENT_ID` (:24-27). В контейнере задан только `YOUTUBE_CLIENT_ID` [проверено, имя env]. Одобрен ли Business Profile API для GCP-проекта YouTube-клиента Postiz - [не проверено]; Basic Access одобрен на проекте Pavel'я (план, шаг 0).

Что даст росту Google (рекомендации, порядок по отдаче):
1. Регулярные посты 2-3/нед (сейчас 0) с BOOK и UTM; типы STANDARD и OFFER (без "скидок", GBP режет агрессивные офферы и телефон в тексте, PLAN §5).
2. Фото в профиль (вкладка Photos, отдельно от постов) по категориям AT_WORK/INTERIOR/TEAM из 311 фото архива через v4 `media` [не проверено, API не вызывал].
3. Отзывы: 45 на GBP против 393 клиентов базы; воронка отзыва уже есть в lead-engine (DECISIONS 2026-09-23 "приглашение к отзыву одно для всех"). Ответы на отзывы через API, как `ads-gbp-reviews-sync` у ADS.
4. `sameAs` на сайте и ссылки на FB/IG/TikTok в шапке/подвале (сейчас ноль).
5. Видео в GBP: Postiz запрещает, v4 localPosts видео в посте [не проверено]; видео лучше грузить в Photos/Videos профиля.

## 6. Одобрение Жени: какой бот

- @croscor_bot (помощник `yevhen`): уже подключено. `team.json` members/yevhen `{"role":"manager","projects":["wwgwow"],"social":["wwg"]}`; `team_outbox.py:35-38, 89-109` маршрутизирует `team-tool social plan|now|cancel|text|igtext|gbptext|send|approve|preview` в `autopost/engine.py wwg`. Превью с картинками приходят Жене туда (`engine.py:172, 450-471`), одобрение привязано к отпечатку слота (`engine.py:141-153`), правка текста снимает одобрение. 4 слота 06-10.11 уже показаны (`previews.json`), не одобрены.
- @wwgwow_bot (lead-engine CRM): кода соцсетей нет. Годится для еженедельной сводки (охват + заявки с `utm_campaign=autopost` из CRM), не для одобрения.
- Рекомендация: одобрение остаётся в @croscor_bot, сводка в @wwgwow_bot. Если переезжаем на Postiz/фабрику, бот одобрения тот же, меняется только движок за `team-tool social`.

## 7. Конфликт архитектуры и рекомендация

Три движка на один класс задачи: `yourhelp/autopost/slots.py` (фонд, крон root), `server-root/scripts/autopost` (WWG, с 04.11), `content-factory` (phase-1 ядро, Postiz-адаптер, не в проде). DEBT уже признаёт дублирование шабата и дублей (`server-root/DEBT.md:2`).

Hotfix = ничего не менять, WWG живёт на autopost. Архитектурно правильнее одна система:
- План, одобрение, шабат, факты = content-factory (её модель Tenant/Slot/Delivery уже это описывает, `ARCHITECTURE.md`).
- Исполнитель FB/IG = Postiz по API "опубликовать сейчас" (организация "WWG WOW" в Postiz, каналы подключить OAuth Pavel'я, у него MANAGE на странице). FB Reels напрямую, т.к. Postiz шлёт в `/videos` (`ARCHITECTURE.md`, "Прямые адаптеры").
- GBP = прямой адаптер, перенесённый из `autopost/gbp.py` (дедуп до и после POST), пока не доказан Postiz `gmb` на одобренном GCP-клиенте.
- Бот = @croscor_bot помощник, админка = Postiz UI для календаря + админка фабрики для одобрений.
Рекомендую: WWG не переносить до 2 недель стабильной работы autopost; формат `tenants/wwg/config.json` маппить в `tenant.yaml` фабрики; переезд одним шагом вместе с YourHelp. Решение о Postiz требует новой записи в `server-root/DECISIONS.md`, т.к. 04.11 он отвергнут.

## 8. Риски, которые видны сейчас

- ADS GBP застрял (п.0.3): надо `publish.py --reconcile` и найти класс ошибки до 11:00 Chicago сегодня, иначе GBP-часть WWG может так же уйти в unknown.
- Рилс 06.11 10:00 Chicago в 28 мин от шабата (п.0.4). Публикация рилса (resumable upload, `meta.py:74-80`) может длиться минуты.
- `media_host` = scp на wwg-prod в `wp-content/uploads/autopost` (`engine.py:272-292`): клиентские медиа становятся публичными и остаются там; чистки после выхода нет [не проверено].
- Рилсы без лого и музыки, clip-engine не подключён (`server-root/DEBT.md:4`).
- Сборщик - headless Claude на подписке Жени (`payer: yevhen`), лимит 70% (CLAUDE.md).
- Атрибуция: UTM на live `/book/` - DEBT 2026-09-11 говорил, что live сохраняет только gclid [не перепроверял].

## 9. Открытые вопросы

1. Pavel: Postiz становится движком для WWG сейчас или после 2 недель autopost? (конфликт с DECISIONS 04.11)
2. Pavel: единое консервативное окно шабата для всех движков (как ADS: пт с 09:30 Chicago)? Сдвинуть рилс 06.11?
3. Pavel: кто разбирает застрявший ADS GBP пост и запускает reconcile?
4. Женя: хэндл TikTok; что нельзя показывать (черновик 30.10); какое число отзывов писать.
5. Pavel: GCP-клиент для Postiz `gmb` (`GOOGLE_GMB_CLIENT_ID`) = одобренный проект Pavel'я? Нужен redirect URI и перезапуск контейнера (с его разрешения).
