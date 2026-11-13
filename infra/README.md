# Развёртывание Sponsorship

Обновлено 2026-11-13. Docker Compose, HTTPS через Caddy и отдельный ASGI-сервер с учётными записями. Это конфигурация для пилота одной организации. Локальный запуск Docker проверен 2026-11-13 (см. «Проверка 2026-11-13»); на целевом сервере с публичным доменом не проверялось. Публикация не выполнялась.

Проверено локально: синтаксис Python/JavaScript, валидация основной и объединённой Compose-конфигурации, шесть тестов аутентификации/доступа (анонимный доступ, Host, вход и отзыв, запрет записи viewer, CSRF, Origin). Браузерный проход нового входа не выполнен из-за ограничения времени; результат не объявляется готовым публичным релизом.

## Сервер с Docker

Нужны Linux-сервер, Docker Engine с Compose, домен с A/AAAA на сервер и доступные порты 80/443. Не оставляйте AAAA, если IPv6 не настроен. Обычный статический хостинг не подходит: нужны Python-процесс и постоянные тома SQLite. Подойдут VPS или контейнерный хостинг с постоянным диском. Один экземпляр API; для масштабирования потребуется отдельный проект миграции БД.

Из корня проекта на сервере:

```sh
cp .env.example .env
# Отредактировать DOMAIN в .env
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps api python deploy.py user-add admin --role admin
# Пароль вводится скрыто, минимум 15 символов; пароля по умолчанию нет.
docker compose up -d
docker compose ps
```

Открыть `https://ВАШ-ДОМЕН/`. Caddy получает сертификат и перенаправляет HTTP на HTTPS. Наружу опубликован только Caddy; API не имеет host-порта. Контейнер API работает от UID 10001, с read-only корнем, без capabilities, с лимитами памяти/процессов. Не запускать `sponsor.py serve` как публичный сервер: это прежний режим только для localhost.

Перед реальным размещением проверить выдачу сертификата, вход/выход, запрет анонимного доступа, каждую роль, сохранение после перезапуска и восстановление копии. Образы `python:3.12-slim` и `caddy:2-alpine` плавающие; после проверенной сборки закрепить их digest для повторяемого релиза. Зависимости Python закреплены в `requirements-server.txt`.

## Роли

| Роль | Полномочия |
| --- | --- |
| viewer | Чтение всех исследований и экспортов организации |
| researcher | Подготовка брифа, источников, кандидатов, пакетов, задач и результатов; без утверждения риска/сделки |
| reviewer | Возможности исследователя, ручной отбор, проверка риска, оценка и приёмка задач |
| approver | Возможности проверяющего, веса, решения C-level, переходы, запуск и закрытие кампании |
| admin | Все бизнес-действия; управление аккаунтами выполняет оператор через CLI |

Это роли приложения, а не роли LLM. Данные общие внутри одной организации; изоляции разных клиентов/тенантов и сокрытия финансов от viewer нет. Пароли Argon2id; непрозрачные серверные сессии с HttpOnly/Secure/SameSite=Strict, сроком 8 часов. Изменения требуют Origin и CSRF. Автор изменений берётся из сессии, поле actor клиента игнорируется. Первичное создание исследования дополнительно фиксируется в auth-аудите; исторический domain-create пока имеет старую метку owner.

```sh
docker compose exec api python deploy.py user-add analyst --role researcher
docker compose exec api python deploy.py user-role analyst --role reviewer
docker compose exec api python deploy.py user-password analyst
docker compose exec api python deploy.py user-disable analyst
```

Смена роли/пароля и отключение отзывают сессии. Последнего активного admin отключить нельзя. CLI доступен только оператору сервера; не давать пользователям Docker/socket/SSH ради управления аккаунтами. SSO/MFA пока не реализованы; для рабочего пилота ограничить доступ доверенной сетью/VPN. В защищённом режиме создание демо и прямой импорт подписанного партнёрства через веб пока не подключены; существующие исследования читаются, стандартное создание и изменения работают. Некоторые кнопки видимы всем: реальные ограничения проверяет сервер.

## LLM и инструменты

**Приложение и расчёты работают без API-ключей.** Основной чатовый ресёрч по-прежнему выполняется через Codex. Добавлены серверные адаптеры OpenAI Responses, Anthropic Messages и Exa Search, а также очередь черновиков. **Создание заданий из веб-интерфейса ещё не подключено; одни ключи не включают автономный поиск.** Адаптеры не проверялись платными запросами.

Для будущего/операторского worker используется дополнительный файл `infra/compose.worker.yaml`:

| Назначение | Файл секрета на сервере | Переменная внутри worker |
| --- | --- | --- |
| OpenAI | `secrets/openai_api_key` | `OPENAI_API_KEY_FILE=/run/secrets/openai_api_key` |
| Anthropic | `secrets/anthropic_api_key` | `ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_api_key` |
| Exa | `secrets/exa_api_key` | `EXA_API_KEY_FILE=/run/secrets/exa_api_key` |

Создать каталог `secrets` с доступом только владельцу. Заполнить файлы через редактор/менеджер секретов, без ключей в командах, Git, браузере и логах. Неиспользуемые файлы могут быть пустыми: текущий Compose ожидает наличие всех трёх. На Linux файлы должны читаться UID 10001 внутри контейнера; родительский каталог на хосте оставить 0700. Compose file secrets — файловые монтирования, не зашифрованное хранилище; защиту диска и копий обеспечивает оператор. Ключи монтируются только worker, API их не получает.

Настройки, не секреты:

```sh
SPONSOR_LLM_PROVIDER=openai       # либо anthropic, либо disabled
SPONSOR_LLM_MODEL=ВАШ_API_MODEL_ID
```

Укажите точный model ID, доступный в API вашего аккаунта. Подписка на чат не заменяет API-ключ и API-биллинг. Для запуска подготовленного worker: `docker compose -f compose.yaml -f infra/compose.worker.yaml up -d worker`. Без созданных оператором заданий он ничего не отправляет. Не включайте его как доказательство работающего автономного ресёрча.

Нужен один LLM для черновиков; Exa — дополнительный поиск кандидатов. Выдача Exa пока сохраняется как leads: чтение первичных страниц, создание доказательств и импорт в исследование требуют отдельного исполнения/проверки. Creator analytics, парсеры и CRM не обязательны для запуска; их адаптеры не реализованы. Не выдавать поисковый сниппет за источник или LLM-ответ за факт.

Очередь имеет idempotency, резерв запросов, лимит заданий, отмену до старта и отсутствие автоматического повтора после ошибки/неизвестного исхода. Лимит запросов/токенов не гарантирует денежный потолок: выставить бюджет/alerts у провайдера. Ответы — текстовые черновики, не исполняемые команды. Они не изменяют исследования. Секреты и закрытые материалы не отправлять в модель без разрешённого для организации режима обработки данных. `store=false` у OpenAI не является обещанием полного отсутствия хранения у поставщика.

## Копии и восстановление

Постоянные тома: `research` (исследования), `auth` (пользователи, сессии, аудит), `caddy_data` (сертификаты), при подключении worker — `jobs`. Перед обновлением остановить запись: `docker compose stop api`; затем сохранить тома средствами хостинга или `sqlite3.Connection.backup` в отдельные зашифрованные копии. Не копировать работающий SQLite простым cp. Восстанавливать в отдельное тестовое окружение с той же версией кода; проверить историю и вход, отозвать старые сессии. Только после проверки переключать рабочий экземпляр. `docker compose down -v` удаляет данные — не использовать для обычного обновления.

Проверенная последовательность (`/backup` — каталог хоста, примонтированный только на время операции; [sqlite_copy.py](sqlite_copy.py) делает `sqlite3.Connection.backup` и `pragma integrity_check`):

```sh
docker compose stop api
docker compose run --rm --no-deps -v "$PWD/backups/ДАТА:/backup" -v "$PWD/infra/sqlite_copy.py:/tool/sqlite_copy.py:ro" api sh -c   'python /tool/sqlite_copy.py /data/research/workspace.sqlite3 /backup/research.sqlite3 &&
   python /tool/sqlite_copy.py /data/auth/auth.sqlite3 /backup/auth.sqlite3'
docker compose up -d --wait
# Восстановление: те же команды с обратным порядком аргументов и монтированием :ro
```

Восстановленная `auth` возвращает учётные записи и **сессии на момент копии**: отключённые позже пользователи снова активны. После восстановления сменить пароль/повторно отключить такие учётные записи (это отзывает их сессии); отдельной команды отзыва всех сессий пока нет.

Хранить копии отдельно от сервера; задать срок хранения, проверять восстановление. Секреты не включать в образ, репозиторий или публичный архив. В мини-ПК передавать только синтетические данные и выполнять правила AGENTS.md; в этой сессии mini-PC не развёртывался.

## Проверка 2026-11-13

Локально, Windows + Docker Desktop (Engine 29.8.2), `DOMAIN=localhost`, только синтетические учётные записи и исследования с пометкой SYNTHETIC; тома удалены после проверки.

| Проверка | Результат |
| --- | --- |
| `docker compose config --quiet`, `build` | OK после исправления: `.dockerignore` исключал `requirements-pdf.txt`, который копирует Dockerfile |
| `deploy.py user-add` для admin, viewer, researcher | OK; пароль через stdin (`-T`) |
| `up -d`, healthcheck API, Caddy | healthy; API без host-порта |
| HTTP → HTTPS | 308; `/` без сессии → 303 `/login`; `/api/research` без сессии → 401 |
| TLS | для `localhost` Caddy выдаёт сертификат внутреннего CA; цепочка проверена curl с `root.crt` из тома `caddy_data` |
| Cookie | `__Host-sponsor; HttpOnly; Secure; SameSite=strict; Max-Age=28800` |
| Браузер (тот же образ и тома, режим `SPONSOR_ALLOW_INSECURE_LOCAL` на 127.0.0.1:8180, т.к. браузер не доверяет внутреннему CA) | неверный пароль — ошибка; вход viewer → кабинет; запись viewer → 403; «Выйти» → `/login`, `/auth/me` 401; вход admin и создание исследования через форму |
| Роли по HTTPS | researcher создаёт исследование 201; viewer 403; без CSRF 403; чужой Origin 403 |
| Перезапуск | исследования и сессии сохраняются |
| Копия/восстановление | копия обеих БД → новое исследование и отключение viewer → восстановление: исследование исчезло, viewer снова входит, история читается |

Не проверено: публичный сертификат ACME, реальный домен/сервер, роли reviewer/approver в браузере, PDF-экспорт, worker.

## Проверка без Docker

```sh
python -m venv .venv-server
# Активировать окружение, затем:
pip install -r requirements-server.txt
python -m unittest discover -s tests -p test_hosted.py -v
```

Для локального защищённого режима задать `SPONSOR_PUBLIC_URL=http://127.0.0.1:8180`, `SPONSOR_ALLOW_INSECURE_LOCAL=1`, пути `SPONSOR_DATABASE`, `SPONSOR_AUTH_DATABASE`, `SPONSOR_JOBS_DATABASE` в отдельной тестовой папке. Создать пользователя командой `deploy.py`, запустить `python -m uvicorn apps.api.hosted:create_app --factory --host 127.0.0.1 --port 8180`. В публичном окружении HTTP-исключение запрещено конфигурацией.

## Основания

Проверены 2026-10-04: [Docker Compose secrets](https://docs.docker.com/reference/compose-file/secrets/), [настройки контейнеров](https://docs.docker.com/reference/compose-file/services/), [OWASP: пароли](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [OWASP: сессии](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [Uvicorn](https://www.uvicorn.org/settings/), [OpenAI Responses](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create), [Exa Search](https://exa.ai/docs/reference/search). Это основания реализации, не независимый аудит безопасности.
