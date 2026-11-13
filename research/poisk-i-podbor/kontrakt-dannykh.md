# Контракт данных исследовательского прототипа

Дата: 2026-09-30. Версия schema_version: 1.0. Проверки структуры и значимых ограничений выполняются инструментом; это не окончательная модель данных приложения.

## Бриф

См. заполненный [безопасный пример](primery/brif-chili-demo.json).

| Поле | Смысл |
| --- | --- |
| id, schema_version, kind | Версия запроса; synthetic явно отделён от реального брифа |
| company, goal, audience | Контекст; исследователь извлекает темы и формулирует гипотезы |
| geo | Целевые страны/территории по двум буквам; произвольную новую страну сначала добавить в GEO-пакеты |
| budget.amount/currency/months | Потолок с валютой и периодом; сумма > 0, период > 0 |
| budget.scope | all_in или fee_only; не смешивать |
| budget.non_fee_costs | Известные затраты сверх гонорара или null; неизвестное не ноль |
| topics.direct/audience | Канонические тематические теги для поиска и проверки связи |
| topics.adjacent | term + reason; гипотеза моста, а не факт аудитории |
| advanced | min_followers, follower_gate_kinds, metric_max_age_days, max_search_calls, max_pages, num_results |
| restrictions | Условия брифа для ручной проверки; произвольный текст автоматически кодом не исполняется |

## Реестр источников

Одна evidence-запись: id, url, excerpt, summary, source_class, independence_group, access, retrieved_on, published_on, event_on, connector, connector_version, retrieval_freshness.

- access для использованного доказательства — page_read. Сниппет сохраняется в журнале обнаружения, а не как подтверждение.
- published_on и event_on могут быть null; retrieved_on их не заменяет.
- Один сайт/автор может дать несколько страниц; independence_group сохраняет зависимость источников.
- connector_version и возраст кэша не выдумываются, если инструмент их не вернул.
- Краткая цитата помогает найти фрагмент; резюме на русском отделено от буквального текста.

## Досье и конкретная возможность

Каждый candidate содержит id, name, kind, entity_key, official_url, topic_claims, geo_context, scale, metrics, platform_scan_complete, audience_geo, risk, availability, opportunities, open_questions.

Типы: influencer, streamer, athlete, musician, expert, team, club, league, federation, tournament, event, race, podcast. Необходимый новый тип добавляется в проверяемый контракт с объяснением правила; общественные организации и локальные сообщества пока сохраняют прежнее исключение.

У topic_claims: term + evidence_ids. Это ручная классификация проверенного содержания, не утверждение о покупательском поведении.

У metric: platform, account_url, followers, precision, observed_on, evidence_ids; при округлении lower_bound/upper_bound допустимы только с основанием. Все значения подписчиков — целые неотрицательные числа либо null. Последнее наблюдение аккаунта имеет приоритет; конфликт одного аккаунта/даты блокирует решение.

У audience_geo: basis = unknown/proxy/provider_estimate/reported, countries, evidence_ids и measured_on. Прототип не валидирует количественную долю/размер ЦА; для полного отбора дополнительно нужны определение, знаменатель, период и метод измерения. nationality и country профиля относятся к geo_context.

У risk: not_checked/flagged/reviewed/confirmed_block; confirmed_block требует источника и human_reviewed=true. Код не классифицирует правонарушения и не делает юридических выводов. У availability: unknown либо reported с источником; это не гарантия доступности.

У opportunity:

- id, description, territory, event_on: гипотеза активации; прошедшая дата требует новой редакции события.
- scope: limited_nonexclusive/annual_nonexclusive/global_exclusive.
- cost.status: unknown/estimate/published. При unknown low/high — только null.
- Численная цена требует low/high, currency, months, cost_basis, source_price_kind, scope_match, evidence_ids, valid_on, valid_until.
- source_price_kind: sponsorship_package/creator_activation/ambassadorship/appearance/rights_license. Билеты, курсы и товарные цены отвергаются.
- estimate дополнительно требует derivation. scope_match — вывод исследователя о сопоставимости состава, территории, прав и периода; он требует ручной проверки. valid_until — срок пригодности наблюдения с основанием из источника или явно принятой политики исследования.
- budget_hypothesis, если есть: assessment (plausible/unlikely/unknown), brief_id, budget_amount, currency, months, budget_scope, reason, assumptions. Изменение контекста инвалидирует гипотезу; диапазон цены из неё не выводится.

## Выход и журнал

plan: scheduled и deferred с ID ячеек, аргументами инструмента, GEO, языком, направлением и углом. network_executed=false означает, что генерация JSON не выполнила поиск.

review: status=preliminary_research_queue; rows по объекту и пакету, раздельные fit/followers/audience_geo/budget/risk, missing и evidence_ids. human_moderation_required=true. Итоговая цена/прогноз не создаются из пропусков.

execution_log: ID реально выполненных ячеек, поставщик, запросы, число выдач/прочитанных страниц, ошибки, повторы, затраты и оставшиеся направления. Если нет привязки к ID плана, planned_search_coverage=not_assessed. Фактические расходы — null, если провайдер их не передал.
