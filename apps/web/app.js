"use strict";

let meta, research = null, researches = [], tab = "brief", busy = false, fieldSequence = 0;
const dialogStack = [];
const $ = selector => document.querySelector(selector);
const savedTheme = (() => {try {return localStorage.getItem("sponsor-theme");} catch {return null;}})();
document.documentElement.dataset.theme = savedTheme === "dark" ? "dark" : "light";
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num = value => value == null ? "—" : new Intl.NumberFormat("ru-RU", {maximumFractionDigits:2}).format(value);
const day = () => new Date().toLocaleDateString("en-CA", {timeZone:"Europe/Riga"});
const metricNames = {qualified_impressions:"Показы в целевой аудитории",branded_impressions:"Брендированные показы",unique_reach:"Уникальный охват",clicks:"Переходы",registrations:"Регистрации",full_cost:"Полные затраты"};
Object.assign(metricNames, {brand_recall_rate:"Запоминание бренда, %",brand_association_rate:"Связь бренда с партнёром, %",brand_trust_rate:"Доверие бренду, %"});
const kindNames = {influencer:"Инфлюенсер",streamer:"Стример",athlete:"Спортсмен",expert:"Эксперт",musician:"Музыкант",actor:"Актёр",team:"Команда",club:"Клуб",league:"Лига",federation:"Федерация",tournament:"Турнир",event:"Событие",race:"Гонка",podcast:"Подкаст",media:"Медиа",esports:"Киберспорт"};
const queueNames = {priority:"Приоритетный",alternative:"Альтернатива",needs_data:"Нужны данные",excluded:"Исключён"};
const riskNames = {not_checked:"Риск не проверен",reviewed:"Проверка выполнена",flagged:"Есть сигнал",confirmed_block:"Исключён по риску"};
const taskNames = {planned:"Запланировано",in_progress:"В работе",blocked:"Заблокировано",submitted:"На приёмке",accepted:"Принято",waived:"Снято с причиной"};
const gateNames = {brief_changed:"Бриф изменился",excluded:"Исключён",risk_review:"Нужна проверка риска",followers_pending:"Нужен счётчик",followers_fail:"Ниже порога",not_selected:"Не выбран",missing_criteria:"Недостаточно данных"};
const searchCategories = {creators:"Авторы / эксперты",athletes:"Спортсмены",music:"Музыка / артисты",teams:"Команды / клубы / лиги",events:"События",gaming_media:"Игры / медиа"};
const searchFormats = {content_series:"Контентная серия / пилот",ambassador:"Регулярное амбассадорство",event_activation:"Спонсорство события",season_program:"Программа сезона",licensed_content:"Контент с платным продвижением"};
const capabilityNames = {content_owner:"Ответственный за контент",ongoing_owner:"Ресурс на регулярную работу",event_team:"Команда офлайн-активации",paid_media:"Ресурс платного продвижения",conversion_tracking:"Измерение целевого действия",brand_measurement:"Измерение брендового результата"};
Object.assign(gateNames, {over_budget:"Выше бюджета",currency_mismatch:"Несопоставимая валюта",period_mismatch:"Несопоставимый период",territory_mismatch:"Территория не покрывает бриф"});

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json",...(window.sponsorSession ? {"X-CSRF-Token":window.sponsorSession.csrf} : {})},body:JSON.stringify(body)});
  if (response.status === 401) {location.assign('/login');throw new Error('Требуется вход');}
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Не удалось выполнить действие");
  return result;
}
function toast(message, error = false) {
  if (error && $("#dialog").open) {
    let feedback = $("#dialog-body .form-error");
    if (!feedback) {
      feedback = document.createElement("p");
      feedback.className = "form-error";
      feedback.setAttribute("role", "alert");
      const footer = $("#dialog-body .form-footer");
      if (footer) footer.before(feedback);
      else $("#dialog-body").appendChild(feedback);
    }
    feedback.textContent = message;
    feedback.scrollIntoView({block:"nearest"});
  }
  $("#toast").textContent = message;
  $("#toast").className = error ? "error" : "";
  $("#toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {$("#toast").hidden = true;}, error ? 10000 : 4500);
}
async function refreshList() { researches = await api("/api/research"); }
async function openResearch(id) {
  research = await api("/api/research/" + encodeURIComponent(id));
  tab = research.stage;
  await refreshList();
  render();
  window.scrollTo(0,0);
}
async function act(action, payload, message = "Сохранено") {
  research = await api("/api/research/" + encodeURIComponent(research.id) + "/actions",
    {revision:research.revision,action,payload});
  await refreshList();
  render();
  toast(message);
}
function field(label, name, value = "", type = "text", extra = "", hint = "") {
  const domId = name + "-" + (++fieldSequence);
  return '<div class="field"><label for="' + domId + '">' + esc(label) + '</label><input id="' + domId + '" name="' + name +
    '" type="' + type + '" value="' + esc(value) + '" ' + extra + '>' + (hint ? '<small>' + esc(hint) + '</small>' : "") + '</div>';
}
function area(label, name, value = "", required = false, hint = "") {
  const domId = name + "-" + (++fieldSequence);
  return '<div class="field wide"><label for="' + domId + '">' + esc(label) + '</label><textarea id="' + domId + '" name="' + name +
    '" ' + (required ? "required" : "") + '>' + esc(value) + '</textarea>' + (hint ? '<small>' + esc(hint) + '</small>' : "") + '</div>';
}
function options(values, value = "") {
  return Object.entries(values).map(([key,label]) => '<option value="' + esc(key) + '" ' + (key === value ? "selected" : "") + '>' + esc(label) + '</option>').join("");
}
function select(label, name, values, value = "", extra = "") {
  const domId = name + "-" + (++fieldSequence);
  return '<div class="field"><label for="' + domId + '">' + esc(label) + '</label><select id="' + domId + '" name="' + name + '" ' +
    extra + '>' + options(values,value) + '</select></div>';
}
function multiSelect(label, name, values, selected = []) {
  const domId = name + "-" + (++fieldSequence);
  return '<div class="field"><label for="' + domId + '">' + esc(label) + '</label><select id="' + domId + '" name="' + name + '" multiple size="3">' +
    Object.entries(values).map(([key,value]) => '<option value="' + esc(key) + '" ' + (selected.includes(key) ? "selected" : "") + '>' + esc(value) + '</option>').join("") + '</select></div>';
}
function sourcesField(selected = [], name = "source_ids", multiple = true) {
  const domId = name + "-" + (++fieldSequence);
  return '<div class="field wide"><label for="' + domId + '">Материалы и основания</label><select id="' + domId + '" name="' + name +
    '" ' + (multiple ? 'multiple size="3"' : "") + '>' + (!multiple ? '<option value="">Выберите материал</option>' : "") +
    research.sources.filter(s => s.access !== "search_lead").map(s => '<option value="' + esc(s.id) + '" ' +
      (selected.includes(s.id) ? "selected" : "") + '>' + esc(s.title) + '</option>').join("") +
    '</select><small>Используйте прочитанные источники или предоставленные материалы. <button type="button" class="quiet" data-action="source">Добавить материал</button></small></div>';
}
function sourceIds(form, name = "source_ids") { return form.getAll(name).filter(Boolean); }
function numeric(form, name) { const value = form.get(name); return value === "" || value == null ? null : Number(value); }
function listText(value) { return String(value || "").split(",").map(v => v.trim()).filter(Boolean); }
function disabled(stages) { return research.case || !stages.includes(research.stage) ? "disabled" : ""; }
function badge(value, tone = "") { return '<span class="badge ' + tone + '">' + esc(value) + '</span>'; }
function empty(title, body = "") { return '<div class="empty">' + esc(title) + (body ? '<p>' + esc(body) + '</p>' : "") + '</div>'; }
function sourceLink(source) { return source.url ? '<a href="' + esc(source.url) + '" target="_blank" rel="noreferrer">' + esc(source.title) + '</a>' : esc(source.title); }
function range(values, currency) { return values ? num(values[0]) + (values[0] !== values[1] ? "–" + num(values[1]) : "") + " " + esc(currency || "") : "Неизвестно"; }
function packageLabel(p) { return (research.candidates.find(c => c.id === p.candidate_id)?.name || "") + " · " + p.name; }
function showDialog(title, content, nested = false) {
  if (nested && $("#dialog").open) {
    const fragment = document.createDocumentFragment();
    while ($("#dialog-body").firstChild) fragment.appendChild($("#dialog-body").firstChild);
    dialogStack.push(fragment);
  }
  $("#dialog-body").innerHTML = '<div class="dialog-heading"><h2>' + esc(title) + '</h2><button class="close" data-action="close" aria-label="Закрыть">×</button></div>' + content;
  if (!$("#dialog").open) $("#dialog").showModal();
}
function closeDialog() {
  if (dialogStack.length) {
    $("#dialog-body").replaceChildren(dialogStack.pop());
    for (const selector of $("#dialog-body").querySelectorAll('select[name="source_ids"],select[name^="assessment_sources_"]')) {
      const selected = [...selector.selectedOptions].map(option => option.value);
      const newest = research.sources.at(-1)?.id;
      selector.innerHTML = research.sources.filter(source => source.access !== "search_lead").map(source =>
        '<option value="' + esc(source.id) + '" ' + (selected.includes(source.id) || source.id === newest ? "selected" : "") +
        '>' + esc(source.title) + '</option>').join("");
    }
  } else $("#dialog").close();
}

function render() {
  $("#sidebar").innerHTML = '<div class="sidebar-label">Исследования · ' + researches.length + '</div>' +
    researches.map(item => '<button class="research-link ' + (research?.id === item.id ? "active" : "") + '" data-action="open" data-id="' +
      esc(item.id) + '"><strong>' + esc(item.title) + '</strong><small>' + esc(meta.stages.find(s => s[0] === item.stage)[1]) +
      (item.kind === "synthetic" ? " · демо" : "") + (item.closed ? " · завершено" : "") + '</small></button>').join("") +
    '<div class="sidebar-footer">От брифа до результата.<br>Решения и основания сохраняются.</div>';
  if (!research) return renderHome();
  const roleLinks = meta.roles.filter(role => role.stages.includes(research.stage)).map(role => '<a class="role-link" href="/api/research/' +
    encodeURIComponent(research.id) + '/agent/' + role.id + '">Контекст: ' + esc(role.name) + '</a>').join("");
  $("#main").innerHTML =
    '<div class="page-heading"><div><div class="kicker"><span class="eyebrow">Исследование / версия брифа ' + research.brief_version +
    '</span>' + badge(research.case ? "Кейс завершён" : meta.stages.find(s => s[0] === research.stage)[1], "dark") + '</div><h1>' +
    esc(research.title) + '</h1><p>' + esc(research.brief.company || "Компания ещё не задана") + ' · ' +
    esc(research.brief.geo.join(", ") || "GEO не задано") + ' · ' + esc(meta.goals[research.brief.goal] || "Цель не выбрана") + '</p></div>' +
    '<div class="actions"><a class="role-link" href="/api/research/' + encodeURIComponent(research.id) + '/export.pdf">Скачать отчёт PDF</a>' +
    '<a class="role-link" href="/api/research/' + encodeURIComponent(research.id) + '/export">Отчёт MD</a>' +
    '<a class="role-link" target="_blank" rel="noopener" href="/api/research/' + encodeURIComponent(research.id) + '/strategy">Профиль партнёра и формат</a>' +
    '<a class="role-link" href="/api/research/' + encodeURIComponent(research.id) + '/handoff.pdf">Пакет для отделов PDF</a>' +
    '<a class="role-link" href="/api/research/' + encodeURIComponent(research.id) + '/handoff">Пакет для отделов MD</a>' +
    '<button data-action="history">История</button>' + (!research.case && !["negotiate","report"].includes(research.stage) ?
      '<button class="primary" data-action="advance">Следующий этап →</button>' : "") + '</div></div>' +
    (research.kind === "synthetic" ? '<div class="notice demo"><strong>Учебное исследование.</strong> ' +
      (research.sources.some(s => s.kind !== "synthetic") ? "Бриф условный. Происхождение сведений о кандидатах указано в материалах; этот пример не является готовым подбором для бренда." :
        "Все кандидаты, цены и результаты вымышлены. Этот пример проверяет работу процесса.") + '</div>' : "") +
    '<nav class="stagebar" aria-label="Этапы исследования">' + meta.stages.map(([id,label],index) => '<button class="stage-button ' +
      (tab === id ? "active " : "") + (research.stage === id ? "current" : "") + '" data-action="tab" data-tab="' + id +
      '"><span>' + (index + 1) + '</span>' + esc(label) + '</button>').join("") + '</nav>' +
    '<div class="review-toolbar"><button data-action="tab" data-tab="ready" class="' + (tab === "ready" ? "primary" : "") + '">Проверка и запросы · ' + research.readiness.requests.length + '</button><span class="hint">Доказательства, измерение и самостоятельные оценки</span></div>' +
    ({brief:renderBrief,screen:renderScreen,deep:renderDeep,negotiate:renderOffers,deliver:renderTasks,report:renderReport,ready:renderReady}[tab])() +
    (roleLinks && !research.case ? '<details><summary>Продолжить исследование в чате</summary><p>Передайте контекст роли в Codex. Выполненные действия импортируются с проверкой данных и версии. Подготовка контекста сохраняет задание; сетевой поиск выполняется в чате.</p><div class="role-links">' + roleLinks + '</div></details>' : "");
}
function renderHome() {
  $("#main").innerHTML = '<section class="hero"><div class="eyebrow">Рабочее пространство / Sponsorship Activation</div><h1>От задачи бренда<br>к обоснованному выбору.</h1><p class="lede">Исследуйте кандидатов, сравнивайте конкретные пакеты и сохраняйте решения. После согласования — ведите обязательства и сопоставляйте прогноз с результатом.</p><div class="actions"><button class="primary" data-action="new">Создать исследование</button><button data-action="demo">Открыть демонстрацию</button></div></section>' +
    '<div class="notice"><button data-action="signed">Открыть подписанное партнёрство</button> <span>Для исполнения уже заключённого договора.</span></div>' +
    '<div class="grid three">' + [["01–02","Бриф и широкий поиск","Цель, аудитория, бюджет. Источники и причины первичного отбора."],
      ["03–04","Сравнение и условия","Выбранный пул, пакеты, риск, цена. Передача менеджерам и повторная оценка."],
      ["05–06","Исполнение и результаты","Ответственные и сроки. План / факт и выводы для следующих кампаний."]].map(([n,title,body]) =>
      '<div class="card"><div class="eyebrow">' + n + '</div><h3>' + title + '</h3><p>' + body + '</p></div>').join("") + '</div>' +
    (researches.length ? '<section class="panel"><h2>Последние исследования</h2><div class="grid two">' +
      researches.slice(0,4).map(item => '<div class="card"><div class="card-top"><h3>' + esc(item.title) + '</h3>' +
        (item.kind === "synthetic" ? badge("Демо") : "") + '</div><p>' + item.candidates + ' кандидатов · ' + item.selected +
        ' выбрано</p><button data-action="open" data-id="' + esc(item.id) + '">Продолжить →</button></div>').join("") + '</div></section>' : "");
}
function briefFields(brief = {}) {
  const budget = brief.budget || {};
  const prefs = brief.search_preferences || {};
  return field("Компания / бренд","company",brief.company) + field("Продукт","product",brief.product) +
    select("Основная цель","goal",{"":"Выберите цель",...meta.goals},brief.goal) +
    field("География аудитории","geo",(brief.geo || []).join(", "), "text", 'placeholder="CL"', "Коды стран через запятую") +
    area("Целевая аудитория","audience",brief.audience,false,"Сегмент и гипотезы. Возраст и GEO подтверждаются данными.") +
    field("Бюджет","budget_amount",budget.amount,"number",'min="0.01" step="0.01"') +
    field("Валюта","budget_currency",budget.currency,"text",'maxlength="3" placeholder="USD"') +
    field("Бюджет за период, месяцев","budget_months",budget.months,"number",'min="1" step="1"', "1 — месяц; 12 — год. Сумма относится к этому периоду.") +
    select("Состав бюджета","budget_scope",{"":"Уточните состав",all_in:"Все расходы",fee_only:"Только гонорар / права"},budget.scope) +
    field("Первичная метрика результата","primary_metric",brief.primary_metric) +
    field("Ориентир показов в ЦА","delivery_target",brief.delivery_target,"number",'min="1"', "Ориентир доставки; запоминание бренда измеряется отдельно.") +
    area("Ограничения и обязательные условия","restrictions",brief.restrictions) +
    area("Предоставленные сведения о бренде / лицензии","licence_note",brief.licence_note,false,"Сведения владельца сохраняются с их статусом.") +
    '<details class="field wide"><summary>Параметры исследования</summary><div class="form-grid">' +
    field("Минимум подписчиков одной платформы","min_followers",brief.min_followers ?? 100000,"number",'min="0"') +
    field("Свежесть счётчика, дней","metric_max_age_days",brief.metric_max_age_days ?? 7,"number",'min="1"') +
    field("Лимит поисковых вызовов","max_search_calls",brief.max_search_calls ?? 18,"number",'min="0"') +
    field("Лимит прочитанных страниц","max_pages",brief.max_pages ?? 24,"number",'min="0"') +
    field("Прямые темы поиска","topics_direct",(brief.topics?.direct || []).join(", "),"text",'placeholder="football, running"') +
    field("Темы аудитории","topics_audience",(brief.topics?.audience || []).join(", ")) +
    area("Косвенные темы и основания","topics_adjacent",(brief.topics?.adjacent || []).map(v => v.term + " | " + v.reason).join("\n"),false,"По одной теме на строку: тема | почему её аудитория может быть нам полезна. Это гипотезы для проверки.") +
    multiSelect("Категории партнёров","search_categories",searchCategories,prefs.categories || Object.keys(searchCategories)) +
    multiSelect("Углы поиска","search_lanes",{direct:"Прямая связь",audience:"Интересы аудитории",adjacent:"Косвенная связь"},prefs.lanes || ["direct","audience","adjacent"]) +
    multiSelect("Форматы для проработки","search_formats",searchFormats,prefs.formats || Object.keys(searchFormats)) +
    multiSelect("Языки поиска","search_languages",{es:"Испанский",pt:"Португальский",en:"Английский"},prefs.languages || []) +
    '<p class="hint wide">Языки не выбраны — используется пакет страны. Выбор формата задаёт гипотезу, а не утверждает сделку. Для выбора нескольких пунктов удерживайте Ctrl / Cmd.</p>' +
    select("Распределение запросов","search_order",{balanced:"Равномерно по направлениям",focused:"Сначала первые выбранные направления"},prefs.order || "balanced") +
    field("Сколько профилей показать","search_max_profiles",prefs.max_profiles ?? 3,"number",'min="1" max="5" step="1"') +
    Object.entries(capabilityNames).map(([key,label]) => select(label,"cap_" + key,{unknown:"Не подтверждено",yes:"Ресурс есть",no:"Ресурса нет"},prefs.capabilities?.[key] === true ? "yes" : prefs.capabilities?.[key] === false ? "no" : "unknown")).join("") +
    '</div></details>';
}
function readBrief(form) {
  return {
    ...(research?.brief || {}),company:form.get("company"),product:form.get("product"),goal:form.get("goal"),
    geo:listText(form.get("geo")).map(v => v.toUpperCase()),audience:form.get("audience"),
    primary_metric:form.get("primary_metric"),delivery_target:numeric(form,"delivery_target"),
    restrictions:form.get("restrictions"),licence_note:form.get("licence_note"),
    budget:{amount:numeric(form,"budget_amount"),currency:String(form.get("budget_currency") || "").toUpperCase(),
      months:numeric(form,"budget_months"),scope:form.get("budget_scope")},
    min_followers:numeric(form,"min_followers"),metric_max_age_days:numeric(form,"metric_max_age_days"),
    max_search_calls:numeric(form,"max_search_calls"),max_pages:numeric(form,"max_pages"),
    search_preferences:{categories:form.getAll("search_categories"),lanes:form.getAll("search_lanes"),formats:form.getAll("search_formats"),
      languages:form.getAll("search_languages"),order:form.get("search_order"),max_profiles:numeric(form,"search_max_profiles"),
      capabilities:Object.fromEntries(Object.keys(capabilityNames).map(key => [key,form.get("cap_" + key) === "yes" ? true : form.get("cap_" + key) === "no" ? false : null]))},
    topics:{direct:listText(form.get("topics_direct")),audience:listText(form.get("topics_audience")),
      adjacent:String(form.get("topics_adjacent") || "").split("\n").filter(v => v.trim()).map(line => {
        const split = line.indexOf("|");
        if (split < 1 || !line.slice(split+1).trim()) throw new Error("Для каждой косвенной темы укажите: тема | основание связи");
        return {term:line.slice(0,split).trim(),reason:line.slice(split+1).trim()};
      })}
  };
}
function renderBrief() {
  return (research.missing_brief.length ? '<div class="notice">Для перехода к первичному отбору уточните: ' +
    esc(research.missing_brief.join(", ")) + '.</div>' : '<div class="notice success">Основные поля заполнены. Можно перейти к первичному отбору.</div>') +
    (research.request ? '<blockquote class="request-quote">' + esc(research.request) + '</blockquote>' : "") +
    '<section class="panel"><h2>Задача бренда</h2><form id="brief-form"><fieldset ' + (research.case ? "disabled" : "") +
    '><div class="form-grid">' + briefFields(research.brief) + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить бриф</button><span class="hint">Изменения создают новую версию и требуют пересмотра прежних оценок.</span></div></fieldset></form></section>';
}
function renderScreen() {
  return '<section class="panel"><div class="panel-header"><h2>Пул кандидатов <span class="muted">· ' + research.candidates.length +
    '</span></h2><div class="actions"><button data-action="source" ' + (research.case ? "disabled" : "") + '>Добавить материал</button><button class="primary" data-action="candidate" ' +
    (research.case ? "disabled" : "") + '>Добавить кандидата</button></div></div><p class="section-copy">Первичный список сохраняет основания и пробелы. Выберите пул для глубокого анализа.</p>' +
    (research.candidates.length ? '<div class="grid three">' + research.candidates.map(c => '<div class="card"><div class="card-top"><span class="eyebrow">' +
      esc(kindNames[c.kind]) + '</span>' + badge(c.selected ? "Выбран" : queueNames[c.queue],c.selected ? "dark" : c.queue === "excluded" ? "danger" : "") +
      '</div><h3>' + esc(c.name) + '</h3><p>' + esc(c.rationale || "Соответствие ещё не изучено") + '</p><div class="card-meta">' +
      badge(riskNames[c.risk.status], c.risk.status === "reviewed" ? "" : "warning") + '<span class="hint">' + c.source_ids.length +
      ' материалов</span></div>' + (c.metrics.length ? '<div class="hint">' + esc(c.metrics.at(-1).platform) + ' · ' +
      num(c.metrics.at(-1).followers) + ' подписчиков · ' + esc(c.metrics.at(-1).observed_on) + '</div>' : '<div class="hint">Счётчики не получены</div>') +
      '<div class="actions"><button data-action="select" data-id="' + esc(c.id) + '" ' + disabled(["screen","deep"]) + '>' +
      (c.selected ? "Убрать из пула" : "Выбрать для анализа") + '</button><button class="quiet" data-action="candidate" data-id="' + esc(c.id) +
      '" ' + (research.case ? "disabled" : "") + '>Карточка</button></div></div>').join("") + '</div>' : empty("Список пока пуст","Добавьте кандидатов из исследования в чате или заполните карточку.")) +
    '</section>' + renderSources();
}
function renderSources() {
  return '<section class="panel"><div class="panel-header"><h2>Материалы и основания</h2><button data-action="source" ' +
    (research.case ? "disabled" : "") + '>Добавить</button></div>' + (research.sources.length ? '<div class="source-list">' +
      research.sources.map(s => '<div class="source">' + sourceLink(s) + '<small>' + esc(s.id) + ' · ' + esc(s.retrieved_on) + ' · ' +
        esc({public:"Публичный источник",owner_material:"Предоставленный материал",provider_estimate:"Оценка поставщика",synthetic:"Синтетический материал"}[s.kind]) +
        (s.access === "search_lead" ? " · требует чтения" : "") + '</small><blockquote>' + esc(s.excerpt) + '</blockquote></div>').join("") +
      '</div>' : empty("Материалы ещё не добавлены")) + '</section>';
}
function renderDeep() {
  const selected = research.candidates.filter(c => c.selected);
  return '<section class="panel"><div class="panel-header"><h2>Пакеты и сравнение</h2><button class="primary" data-action="package" ' +
    (selected.length ? disabled(["deep","negotiate"]) : "disabled") + '>Добавить пакет</button></div>' +
    '<p class="section-copy">Единица сравнения: кандидат, пакет, территория и срок под текущий бриф. Веса и шкалы — рабочая методика, требующая проверки на кампаниях.</p>' +
    (research.comparison.length ? '<div class="grid two">' + research.comparison.map(row => {
      const e = row.evaluation, p = row.package;
      return '<div class="card"><div class="card-top"><div><div class="eyebrow">' + esc(row.candidate.name) + '</div><h3>' + esc(p.name) +
        '</h3></div>' + badge(row.rank ? "№ " + row.rank : "Предварительно",row.rank ? "dark" : "warning") + '</div><p>' + esc(p.deliverables) +
        '</p><div class="score-grid"><div><div class="score-label">Пригодность / 100</div><div class="stat">' +
        (e.score == null ? num(e.interval[0]) + '–' + num(e.interval[1]) : num(e.score)) +
        '</div><div class="hint">' + (e.score == null ? "Границы возможного балла" : "Предварительная оценка") +
        '</div></div><div><div class="score-label">Покрытие критериев</div><div class="stat">' + num(e.coverage * 100) +
        '<small>%</small></div><div class="hint">' + esc(riskNames[e.risk]) + '</div></div></div><div class="score-grid"><div><div class="score-label">Полные затраты</div><div class="score-small">' +
        range(e.economics.full_cost_range,e.economics.currency) + '</div></div><div><div class="score-label">Базовый сценарий</div><div class="score-small">' +
        (e.forecast ? num(e.forecast.base) : "Не рассчитан") + '</div><div class="hint">' + esc(metricNames[e.forecast?.metric] || "") +
        '</div></div></div><p>' + esc(e.economics.reason) + '</p><div class="card-meta">' +
        e.gates.map(g => badge(gateNames[g] || g,"warning")).join("") + '</div><details><summary>Основания и чувствительность</summary><div class="table-wrap"><table><thead><tr><th>Критерий</th><th>Оценка</th><th>Вес</th><th>Основание</th></tr></thead><tbody>' +
        Object.entries(e.criteria).map(([key,c]) => '<tr><td>' + esc(meta.criteria[key]) + '</td><td>' + (c.usable ? num(c.value) : "—") +
          '</td><td>' + num(c.weight * 100) + '%</td><td>' + esc(c.reason) + '<div class="row-sub">' + esc(c.source_ids.join(", ")) +
          '</div></td></tr>').join("") + '</tbody></table></div><p>Другие рабочие приоритеты: ' +
        Object.entries(row.sensitivity).map(([key,value]) => esc(meta.goals[key]) + ' ' + num(value)).join(" · ") +
        '</p><p>Права и отчётность: ' + esc(p.rights || "не установлены") + '</p></details><div class="actions"><button data-action="package" data-id="' +
        esc(p.id) + '" ' + disabled(["deep","negotiate"]) + '>Редактировать</button><button data-action="continue" data-id="' + esc(p.id) +
        '" ' + disabled(["deep","negotiate"]) + '>Решение C-level</button></div></div>';
    }).join("") + '</div>' : empty("Пакеты ещё не сформированы",selected.length ? "Подготовьте пакет для выбранного кандидата." : "Сначала выберите пул на этапе первичного отбора.")) +
    '<details><summary>Приоритеты скоринга</summary><p class="muted">Стандартные веса профиля цели: ' + esc(meta.weights_status || "не утверждены") + '. Владелец может изменить их для этого исследования.</p><form id="weights-form"><fieldset ' + (research.case ? "disabled" : "") + '><div class="weight-inputs">' +
    Object.entries(meta.criteria).map(([key,label]) => field(label,key,research.weights[key]*100,"number",'min="0" max="100" step="0.01" required')).join("") +
    '</div>' + area("Основание изменения весов","weight_reason","",true,"Сумма — 100%. Риск, качество данных и цена показываются отдельно.") +
    '<div class="form-footer"><button type="submit">Сохранить приоритеты</button></div></fieldset></form></details></section>';
}
function decisionCurrent(d,p) {
  return d && d.brief_version === research.brief_version && d.weights_version === research.weights_version && d.package_version === (p.package_version || 1);
}
function renderOffers() {
  const eligible = research.packages.filter(p => research.decisions.some(d => d.kind === "c_level_continue" && d.package_id === p.id && decisionCurrent(d,p)));
  const approved = research.offers.filter(o => {
    const p = research.packages.find(p => p.id === o.package_id);
    const d = research.decisions.filter(d => ["approve_offer","decline_offer"].includes(d.kind) && d.offer_id === o.id).at(-1);
    return d?.kind === "approve_offer" && decisionCurrent(d,p);
  });
  return '<section class="panel"><div class="panel-header"><h2>Полученные условия</h2><button class="primary" data-action="offer" ' +
    (eligible.length ? disabled(["negotiate"]) : "disabled") + '>Записать предложение</button></div><p class="section-copy">Менеджер выясняет цену и доступность. Каждый ответ создаёт новую версию пакета. Изменённые права или активации требуют новой оценки.</p>' +
    (research.offers.length ? '<div class="grid two">' + research.offers.map(o => {
      const p = research.packages.find(p => p.id === o.package_id);
      const decision = research.decisions.filter(d => d.offer_id === o.id).at(-1);
      return '<div class="card"><div class="card-top"><h3>' + esc(p.name) + '</h3>' +
        badge(decision && !decisionCurrent(decision,p) ? "Нужно новое решение" : decision?.kind === "approve_offer" ? "Утверждено" : decision?.kind === "decline_offer" ? "Отказ" : "На рассмотрении") +
        '</div><p>' + esc(o.representative) + ' · ' + esc(o.note) + '</p><div class="stat">' + range([o.fee.low,o.fee.high],o.fee.currency) +
        '</div><div class="hint">' + p.months + ' месяцев · ' + esc(p.territory.join(", ")) + '</div><div class="actions"><button data-action="approve" data-id="' +
        esc(o.id) + '" ' + disabled(["negotiate"]) + '>Утвердить</button><button class="quiet danger" data-action="decline" data-id="' + esc(o.id) +
        '" ' + disabled(["negotiate"]) + '>Отказаться</button></div></div>';
    }).join("") + '</div>' : empty("Реальных предложений пока нет","Сначала зафиксируйте разрешение на проработку пакета в глубоком анализе.")) + '</section>' +
    (!research.campaign ? '<section class="panel"><h2>Начать исполнение</h2><form id="campaign-form"><fieldset ' +
      (approved.length ? disabled(["negotiate"]) : "disabled") + '><div class="form-grid">' +
      select("Утверждённое предложение","offer_id",Object.fromEntries(approved.map(o => [o.id,research.packages.find(p => p.id === o.package_id).name]))) +
      field("Начало кампании","campaign_start",day(),"date","required") + field("Конец кампании","campaign_end","","date","required") +
      area("Согласованные обязательства","agreement_note","",true,"Коммерческие условия и подтверждение команды. Юридическое оформление выполняет профильный специалист.") +
      sourcesField() + '</div><div class="form-footer"><button class="primary" type="submit">Начать кампанию</button><span class="hint">Пакет, бриф, веса и прогноз сохранятся как исходный план.</span></div></fieldset></form></section>' :
      '<div class="notice success">Кампания начата. Исходный план сохранён: ' + esc(research.campaign.start) + ' — ' + esc(research.campaign.end) + '.</div>') +
    '<section class="panel"><h2>Решения и основания</h2>' + (research.decisions.length ? research.decisions.map(d =>
      '<div class="source"><strong>' + esc(d.decision_maker) + '</strong> · ' + esc({c_level_continue:"Продолжить проработку",approve_offer:"Утвердить предложение",decline_offer:"Отказаться"}[d.kind]) +
      '<small>Версия брифа ' + d.brief_version + '</small>' + esc(d.reason) + '</div>').join("") : empty("Решения ещё не записаны")) + '</section>';
}
function renderTasks() {
  if (!research.campaign) return empty("Исполнение ещё не начато","Получите условия, зафиксируйте утверждение и согласованные обязательства.");
  const w = research.weekly;
  return renderActivation() + '<div class="progress-summary">' + [[w.overdue.length,"Просрочено"],[w.next_seven_days.length,"В ближайшие 7 дней"],[w.awaiting_acceptance.length,"На приёмке"],[w.blocked.length,"Заблокировано"]].map(([n,label]) =>
    '<div><div class="score-label">' + label + '</div><div class="stat">' + n + '</div></div>').join("") + '</div>' +
    '<section class="panel"><div class="panel-header"><h2>Обязательства и задачи</h2><button data-action="source" ' +
    (research.case ? "disabled" : "") + '>Добавить подтверждение</button></div>' +
    (research.tasks.length ? '<div class="table-wrap"><table><thead><tr><th>Задача</th><th>Ответственный</th><th>Срок</th><th>Статус</th><th>Следующий шаг</th><th></th></tr></thead><tbody>' +
      research.tasks.map(t => '<tr><td class="row-name">' + esc(t.title) + '</td><td>' + esc(t.owner) + '</td><td>' + esc(t.due) +
        '</td><td>' + badge(taskNames[t.status],w.overdue.some(x => x.id === t.id) ? "warning" : "") + '</td><td>' + esc(t.next_action) +
        '<small class="row-sub">' + esc((research.readiness.activation.task_blockers[t.id] || []).join("; ")) + '</small></td><td><div class="actions"><button data-action="task-status" data-id="' + esc(t.id) + '" ' +
        (research.case || ["accepted","waived"].includes(t.status) ? "disabled" : "") + '>Статус</button>' +
        (!["accepted","waived"].includes(t.status) && !research.case ? '<button data-action="task-edit" data-id="' + esc(t.id) + '">Изменить</button>' +
        (t.requires_ack && !t.acknowledgement ? '<button data-action="task-ack" data-id="' + esc(t.id) + '">Подтверждение</button>' : "") : "") + '</div></td></tr>').join("") +
      '</tbody></table></div>' : empty("Добавьте обязательства из согласованного пакета")) +
    '</section><section class="panel"><h2>Новая задача</h2><form id="task-form"><fieldset ' + disabled(["deliver","report"]) +
    '><div class="form-grid">' + taskFields() + '</div><div class="form-footer"><button class="primary" type="submit">Добавить задачу</button></div></fieldset></form></section>';
}

function renderReady() {
  const r = research.readiness, m = r.measurement, p = m.plan || {}, groups = [...new Set(r.requests.map(x => x.department))];
  return '<div class="notice">Рабочая методика требует проверки на реальных кейсах. Запросы ниже — черновики для передачи: исполнители и сроки ещё не назначены.</div>' +
    '<div class="grid three readiness-stats">' + [[r.requests.length,"Открытых запросов"],[r.search.covered + " / " + r.search.scheduled,"Запросов плана отражено в журнале"],[r.search.remaining_calls,"Осталось поисковых вызовов"]].map(([v,label]) =>
      '<div class="card"><div class="score-label">' + esc(label) + '</div><div class="stat">' + esc(v) + '</div></div>').join("") + '</div>' +
    '<section class="panel"><div class="panel-header"><h2>Что нужно проверить</h2><a class="role-link" href="/api/research/' + encodeURIComponent(research.id) + '/handoff">Скачать поручения</a></div>' +
    '<p class="section-copy">Каждый запрос содержит вопрос и ожидаемый результат. Названия отделов обозначают функции; состав команды определяет владелец.</p>' +
    groups.map(group => '<details><summary>' + esc(group) + ' · ' + r.requests.filter(x => x.department === group).length + '</summary><div class="source-list">' +
      r.requests.filter(x => x.department === group).map(x => '<div class="source"><strong>' + esc(x.title) + '</strong> ' + badge(x.priority,x.priority === "P0" ? "warning" : "") +
      '<small>Объект: ' + esc(x.entity) + '</small><p>' + esc(x.question) + '</p><p><strong>Ожидаемый результат:</strong> ' + esc(x.acceptance) + '</p></div>').join("") + '</div></details>').join("") +
    (!r.requests.length ? empty("Структурных пробелов не найдено","Истинность материалов и валидность методики проверяются отдельно.") : "") + '</section>' +
    '<section class="panel"><h2>План измерения</h2><p class="section-copy">Сначала определите, что нужно подтвердить: исполнение прав, наблюдаемое изменение или причинную добавочность. Опросные доли, показы и переходы — разные показатели. Новая запись сохраняет прежний план в истории.</p>' +
    '<div class="notice"><strong>Уровень вывода:</strong> ' + esc(m.claim_scope) + '</div>' +
    '<div class="notice">' + esc(m.missing.length ? "Нужно уточнить: " + m.missing.join(", ") : "Поля заполнены; аналитик должен проверить дизайн и применимость.") + '</div>' +
    '<form id="measurement-form"><fieldset ' + (research.case ? "disabled" : "") + '><div class="form-grid">' +
    select("Основная метрика","measurement_metric",{...Object.fromEntries(meta.metrics.map(k => [k,metricNames[k]])),...(p.metric && !metricNames[p.metric] ? {[p.metric]:p.metric} : {})},p.metric || "brand_recall_rate") +
    field("Единица измерения","measurement_unit",p.unit || "","text","required", "Например: доля опрошенных, %; подтверждённые переходы") +
    field("Целевое значение, если определено","measurement_target",p.target,"number",'min="0" step="any"') + field("Владелец сбора","measurement_owner",p.owner) +
    field("Начало окна","measurement_start",p.start || research.campaign?.start || "","date") + field("Конец окна","measurement_end",p.end || research.campaign?.end || "","date") +
    area("Популяция и выборка","measurement_population",p.population) + area("Источник и порядок сбора","measurement_collection",p.collection) +
    select("Дизайн измерения","measurement_method",meta.measurement_methods,p.method || "descriptive") +
    area("Доступ к данным и допустимое использование","measurement_data_access",p.data_access) +
    area("Учёт пересечений аудитории","measurement_deduplication",p.deduplication) +
    area("Ограничения выводов","measurement_limitations",p.limitations) +
    '<details class="field wide"><summary>Причинная проверка и финансовые данные</summary><p>Эти поля описывают будущую проверку. Заполнение не рассчитывает добавочный эффект или ROI.</p><div class="form-grid">' +
    [["baseline","Исходный уровень и сопоставимость"],["control","Контрольная группа или рынок"],["assignment","Распределение групп и перетекание"],["confounders","Другие кампании, сезонность и внешние факторы"],
      ["analysis","Метод анализа эффекта"],["uncertainty","Практически значимый эффект, обнаружимость, выборка и неопределённость"],["cost_scope","Состав полных затрат"],["margin_definition","Определение маржинальной прибыли"]].map(([key,label]) => area(label,"measurement_"+key,p[key])).join("") +
    '</div></details>' + sourcesField(p.source_ids || []) + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить версию плана</button><span class="hint">Версий: ' + m.historical_versions + '</span></div></fieldset></form></section>' +
    '<section class="panel"><div class="panel-header"><h2>Самостоятельные оценки</h2><button data-action="assessment" ' + (research.case || !research.packages.some(p => p.brief_version === research.brief_version) ? "disabled" : "") + '>Записать оценку человека</button></div><p class="section-copy">Два оценщика используют одну рубрику и версию пакета. Разногласия обсуждаются; рабочий скоринг не заменяется автоматически.</p>' +
    (r.assessments.length ? r.assessments.map(a => '<details><summary>' + esc(packageLabel(research.packages.find(p => p.id === a.package_id))) + ' · оценщиков: ' + a.assessor_count + '</summary>' +
      '<p>' + esc(a.status === "needs_second_assessor" ? "Нужен второй оценщик" : a.status === "rubric_mismatch" ? "Рубрики различаются; числа не сопоставляются" : "Оценки готовы к обсуждению") + '</p>' +
      '<div class="table-wrap"><table><thead><tr><th>Критерий</th><th>Диапазон</th><th>Разница</th></tr></thead><tbody>' + Object.entries(a.criteria).map(([key,c]) =>
        '<tr><td>' + esc(meta.criteria[key]) + '</td><td>' + (c.range ? c.range.map(num).join(" — ") : "Нет сопоставимых оценок") + '</td><td>' + num(c.spread) + '</td></tr>').join("") +
      '</tbody></table></div>' + a.assessments.map(x => '<p><strong>' + esc(x.assessor) + '</strong> · ' + esc(x.rubric_version) + '<br>' + esc(x.independence_note) + '</p>').join("") + '</details>').join("") : empty("Для оценок нужен конкретный пакет")) + '</section>';
}

function assessmentDialog() {
  showDialog("Записать самостоятельную оценку", '<form id="assessment-form"><div class="form-grid">' +
    select("Пакет","assessment_package",Object.fromEntries(research.packages.filter(p => p.brief_version === research.brief_version).map(p => [p.id,packageLabel(p)]))) +
    field("Оценщик","assessor","","text","required") + field("Версия общей рубрики","rubric_version","","text","required", "Оба оценщика указывают одну версию правил оценки") +
    area("Как выполнена самостоятельная оценка","independence_note","",true) + Object.entries(meta.criteria).map(([key,label]) =>
      field(label,"assessment_"+key,"","number",'min="0" max="100" step="any"') + area("Основание или причина пропуска: " + label,"assessment_reason_"+key,"",true) +
      sourcesField([],"assessment_sources_"+key)).join("") + '<label class="check field wide"><input type="checkbox" name="replace_assessment">Явно заменить мою предыдущую оценку этой версии; прежняя запись сохранится</label>' +
    '</div><div class="form-footer"><button class="primary" type="submit">Сохранить оценку отдельно</button></div></form>');
}

function renderActivation() {
  const a = research.readiness.activation;
  return '<section class="panel"><div class="panel-header"><h2>Права и обязательства</h2><div class="actions"><button data-action="entry" ' + (research.case ? "disabled" : "") + '>Добавить пункт</button><button data-action="register-review" ' + (!a.register.length || research.case ? "disabled" : "") + '>Сверка с договором</button></div></div>' +
    '<p class="section-copy">Объём распределяется по задачам в единицах конкретного пункта. Внутренний план требует подтверждения партнёром. ' + (a.register_review_current ? "Текущая версия реестра сверена человеком." : "Полнота текущего реестра ещё не подтверждена.") + '</p>' +
    (a.register.length ? '<div class="table-wrap"><table><thead><tr><th>Пункт / период</th><th>Объём</th><th>В задачах</th><th>Принято</th><th>Остаток</th><th></th></tr></thead><tbody>' + a.register.map(e =>
      '<tr><td><strong>' + esc(e.title) + '</strong><small class="row-sub">' + esc(e.clause) + ' · ' + esc(e.start) + ' — ' + esc(e.end) + '</small>' +
      (e.expired ? badge("Срок истёк","warning") : "") + (e.waiver ? badge("Снято с основанием") : "") + '</td><td>' + num(e.quantity) + ' ' + esc(e.unit) + '</td><td>' + num(e.reserved_quantity) +
      '</td><td>' + num(e.accepted_quantity) + '</td><td>' + num(e.unallocated_quantity) + '</td><td>' + (!e.waiver && !research.case ? '<button data-action="entry" data-id="' + esc(e.id) + '">Изменить</button> <button data-action="entry-waive" data-id="' + esc(e.id) + '">Снять с основанием</button>' : "") + '</td></tr>').join("") + '</tbody></table></div>' : empty("Реестр пока пуст","Добавьте пункты текущего договора с источниками и периодами.")) + '</section>' +
    '<section class="panel"><div class="panel-header"><h2>Применимость пулов</h2><button data-action="pool" ' + (research.case ? "disabled" : "") + '>Записать проверку</button></div><p class="section-copy">Проверьте все 16 пулов. Шаблоны помогают составить задачи; людей, сроки и объёмы задаёт команда.</p>' +
    a.pools.map(p => '<details><summary>' + esc(p.id + " · " + p.title) + ' — ' + esc({applies:"Применяется",not_applicable:"Не применяется",needs_clarification:"Нужно уточнить"}[p.review?.status] || "Не проверен") + '</summary>' +
      (p.review ? '<p>' + esc(p.review.reason + " · " + p.review.reviewer) + '</p>' : "") + p.templates.map(t => '<div class="source"><strong>' + esc(t.title) + '</strong><p>' + esc(t.acceptance) + '</p>' +
      (p.review?.status === "applies" && !research.case ? '<button data-action="template-task" data-id="' + esc(t.id) + '">Подготовить задачу</button>' : "") + '</div>').join("") + '</details>').join("") + '</section>';
}

function entryDialog(id) {
  const e = research.readiness.activation.register.find(e => e.id === id) || {};
  showDialog("Пункт реестра", '<form id="entry-form"><input type="hidden" name="entry_id" value="' + esc(e.id) + '"><div class="form-grid">' +
    select("Тип","entry_type",{right:"Доступное право",obligation:"Обязательство"},e.type || "obligation") + field("Пункт / актив","entry_title",e.title,"text","required") +
    field("Версия договора / приложения","contract_version",e.contract_version,"text","required") + field("Номер или ссылка на условие","clause",e.clause,"text","required") +
    field("Ответственный за пункт","entry_owner",e.owner,"text","required") + field("Единица","entry_unit",e.unit,"text","required") +
    field("Доступный объём","entry_quantity",e.quantity,"number",'min="0.000001" step="any"',"Неизвестный объём оставьте пустым") +
    field("Запросить до","request_by",e.request_by,"date") + field("Начало периода","entry_start",e.start || research.campaign.start,"date","required") +
    field("Конец периода","entry_end",e.end || research.campaign.end,"date","required") + sourcesField(e.source_ids || []) +
    '</div><div class="form-footer"><button class="primary" type="submit">Сохранить пункт</button></div></form>');
}

function taskFields(t = {}, template = null) {
  const entry = t.allocations?.[0] || {};
  return '<input type="hidden" name="task_id" value="' + esc(t.id) + '">' +
    (template ? '<input type="hidden" name="template_id" value="' + esc(template.id) + '"><p class="field wide">' + esc(template.title) + '</p>' : field("Обязательство / задача","task_title",t.title,"text","required")) +
    field("Ответственный","task_owner",t.owner,"text","required") + field("Срок","task_due",t.due || day(),"date","required") +
    field("Следующее действие","task_next",t.next_action) +
    (template ? '<p class="field wide hint">' + esc(template.acceptance) + '</p>' : area("Критерий приёмки","task_acceptance",t.acceptance)) +
    select("Пул, если применимо","task_pool",{"":"Без пула",...Object.fromEntries(meta.activation_catalog.map(p => [p.id,p.title]))},template ? meta.activation_catalog.find(p => p.templates.some(x => x.id === template.id)).id : t.pool_id || "",template ? "disabled" : "") +
    multiSelect("Предшествующие задачи","task_dependencies",Object.fromEntries(research.tasks.filter(x => x.id !== t.id).map(x => [x.id,x.title])),t.depends_on || []) +
    select("Право / обязательство для распределения","task_entry",{"":"Без распределения",...Object.fromEntries((research.register || []).filter(e => !e.waiver).map(e => [e.id,e.title + " · " + e.unit]))},entry.entry_id || "") +
    field("Объём этой задачи","task_quantity",entry.quantity,"number",'min="0.000001" step="any"') +
    '<label class="check field wide"><input type="checkbox" name="task_requires_ack" ' + (t.requires_ack !== false ? "checked" : "") + '>Нужно фактическое подтверждение назначения исполнителем</label>';
}

function signedDialog() {
  showDialog("Исполнение подписанного партнёрства", '<form id="signed-form"><div class="form-grid">' +
    field("Название кампании","signed_title","","text","required") + field("Бренд","signed_company") +
    field("Партнёр","signed_partner","","text","required") + field("Валюта учёта затрат","signed_currency","","text",'required maxlength="3" placeholder="USD"') +
    field("Начало партнёрства","signed_start","","date","required") + field("Окончание партнёрства","signed_end","","date","required") +
    area("Подписанные обязательства и ограничения","signed_note","",true) + field("Название материала договора","signed_source_title","","text","required") +
    field("Ссылка или описание материала","signed_reference","","text","required") + field("Дата получения","signed_source_date",day(),"date","required") +
    area("Фрагмент, подтверждающий подписанное партнёрство","signed_excerpt","",true) +
    '<label class="check field wide"><input type="checkbox" name="signed_synthetic">Учебная карточка: все условия и материалы вымышлены</label>' +
    '</div><div class="form-footer"><button class="primary" type="submit">Открыть исполнение</button><span class="hint">Источник сохраняется как предоставленный материал. Поиск и прежние решения не создаются.</span></div></form>');
}
function renderReport() {
  if (!research.campaign) return empty("Кампания ещё не начата","Результаты будут сопоставляться с сохранённым исходным планом.");
  const report = research.report;
  return '<section class="panel"><h2>План и факт</h2><p class="section-copy">Прогноз сохранён при старте кампании. Сравнение использует итог за тот же период и в тех же единицах; частичные наблюдения сохраняются отдельно.</p>' +
    (report.metrics.length ? '<div class="table-wrap"><table><thead><tr><th>Показатель</th><th>Низкий / базовый / высокий</th><th>Факт</th><th>Отклонение от базового</th></tr></thead><tbody>' +
      report.metrics.map(r => '<tr><td>' + esc(metricNames[r.metric]) + '</td><td class="numeric">' +
        (r.forecast ? [r.forecast.low,r.forecast.base,r.forecast.high].map(num).join(" / ") : "Не прогнозировался") +
        '</td><td class="numeric">' + (r.actual ? num(r.actual.value) : "Не получен") + '</td><td class="numeric">' +
        num(r.delta) + '</td></tr>').join("") + '</tbody></table></div>' : empty("Итоговые результаты ещё не получены")) +
    '<p class="section-copy">Фактические полные затраты: ' + (report.actual_full_cost ? num(report.actual_full_cost.value) + " " +
      esc(report.actual_full_cost.currency) : "не установлены") + '. Частичных наблюдений: ' + report.partial_observations.length +
    '. Финансовый ROI: нужны добавочная маржа и подходящий способ сравнения.</p></section>' +
    '<section class="panel"><h2>Добавить фактический показатель</h2><form id="outcome-form"><fieldset ' + disabled(["deliver","report"]) +
    '><div class="form-grid">' + select("Метрика","outcome_metric",metricNames) + field("Значение","outcome_value","","number",'min="0" step="any" required') +
    field("Начало периода","outcome_start",research.campaign.start,"date","required") + field("Конец периода","outcome_end",day(),"date","required") +
    select("Объём результата","outcome_scope",{partial:"Частичное наблюдение",campaign_total:"Итог за всю кампанию"},"partial") +
    field("Валюта для полных затрат","outcome_currency",research.campaign.baseline.package.fee.currency) +
    area("Метод учёта пересечений для уникального охвата","deduplication") + sourcesField() +
    '</div><div class="form-footer"><button class="primary" type="submit">Сохранить результат</button></div></fieldset></form></section>' +
    '<section class="panel"><h2>Выводы и дальнейшее сотрудничество</h2>' + (research.case ?
      '<div class="notice success">Кейс завершён: ' + esc({renew:"Продлевать",change:"Изменить пакет",stop:"Завершить сотрудничество"}[research.case.recommendation]) +
      '.</div><p>' + esc(research.case.lessons) + '</p>' :
      '<form id="case-form"><fieldset ' + disabled(["report"]) + '><div class="form-grid">' +
      select("Рекомендация","recommendation",{renew:"Продлевать",change:"Изменить пакет",stop:"Завершить сотрудничество"},"change") +
      area("Что сработало, причины расхождений и выводы","lessons","",true) +
      '</div><div class="form-footer"><button class="primary" type="submit">Завершить и сохранить кейс</button><span class="hint">Сначала завершите приёмку обязательств. Сохранённый кейс остаётся доступным для чтения.</span></div></fieldset></form>') + '</section>';
}

function newDialog() {
  showDialog("Новое исследование", '<form id="create-form"><div class="form-grid">' + field("Название исследования","research_title","","text","required") +
    area("Исходный запрос","request","",false,"Сохраните задачу обычным текстом; ключевые условия заполните ниже или уточните с ассистентом.") +
    briefFields() + '</div><div class="form-footer"><button class="primary" type="submit">Создать исследование</button><span class="hint">Незаполненные условия сохраняются как вопросы.</span></div></form>');
}
function sourceDialog() {
  showDialog("Добавить материал", '<form id="source-form"><div class="form-grid">' + field("Название","source_title","","text","required") +
    field("Ссылка на источник","source_url","","url") + field("Предоставленный материал","source_reference","","text",'placeholder="Медиакит, письмо или отчёт"') +
    field("Дата получения / чтения","source_date",day(),"date","required") +
    select("Происхождение","source_kind",{public:"Публичный источник",owner_material:"Предоставленный материал",provider_estimate:"Оценка поставщика",...(research.kind === "synthetic" ? {synthetic:"Синтетический материал"} : {})},"owner_material") +
    select("Статус чтения","source_access",{provided_material:"Материал предоставлен",page_read:"Страница прочитана",search_lead:"Только поисковая находка"},"provided_material") +
    area("Фрагмент или содержание, подтверждающее сведения","source_excerpt","",true) +
    '</div><div class="form-footer"><button class="primary" type="submit">Сохранить материал</button></div></form>', true);
}
function candidateDialog(id) {
  const c = research.candidates.find(c => c.id === id) || {};
  const metric = c.metrics?.at(-1) || {};
  showDialog(id ? "Карточка кандидата" : "Новый кандидат", '<form id="candidate-form"><input type="hidden" name="candidate_id" value="' +
    esc(c.id) + '"><div class="form-grid">' + field("Имя / название","candidate_name",c.name,"text","required") +
    select("Тип","candidate_kind",kindNames,c.kind || "influencer") + field("Официальная ссылка","candidate_url",c.official_url,"url") +
    select("Очередь","candidate_queue",queueNames,c.queue || "needs_data") + area("Почему кандидат связан с задачей бренда","rationale",c.rationale) +
    area("Причина исключения, если применимо","exclusion_reason",c.exclusion_reason) +
    select("Репутационный статус","risk_status",riskNames,c.risk?.status || "not_checked") +
    area("Основание рискового сигнала / проверки","risk_reason",c.risk?.reason) +
    '<label class="check field wide"><input type="checkbox" name="human_reviewed" ' + (c.risk?.human_reviewed ? "checked" : "") + '>Подтверждённое исключение проверено человеком</label>' +
    field("Платформа счётчика","metric_platform",metric.platform,"text",'placeholder="YouTube"') +
    field("Подписчики на одной платформе","followers",metric.followers,"number",'min="0" step="1"') +
    field("Дата наблюдения счётчика","metric_date",metric.observed_on || day(),"date") +
    select("Точность счётчика","metric_precision",{exact:"Точное число",rounded:"Округлённое",hidden:"Скрыто"},metric.precision || "exact") +
    '<label class="check field wide"><input type="checkbox" name="scan_complete" ' + (c.platform_scan_complete ? "checked" : "") + '>Завершена проверка платформ для решения о пороге</label>' +
    sourcesField(c.source_ids || []) + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить карточку</button></div></form>');
}
function packageDialog(id) {
  const p = research.packages.find(p => p.id === id) || {};
  const candidates = Object.fromEntries(research.candidates.filter(c => c.selected).map(c => [c.id,c.name]));
  const f = p.forecast || {}, fee = p.fee || {}, extras = p.extra_costs || {};
  showDialog(id ? "Оценка пакета" : "Новый пакет", '<form id="package-form"><input type="hidden" name="package_id" value="' + esc(p.id) +
    '"><div class="form-grid">' + field("Название пакета","package_name",p.name,"text","required") +
    select("Кандидат","package_candidate",candidates,p.candidate_id) + field("Период, месяцев","package_months",p.months || research.brief.budget.months,"number",'min="1" required') +
    field("Территория прав","package_territory",(p.territory || research.brief.geo).join(", "),"text","required") +
    area("Активации и объём обязательств","deliverables",p.deliverables,true) + area("Права, условия исполнения и отчётность","rights",p.rights) +
    '<div class="subsection"><h3>Оценки под текущий бриф</h3><p class="hint">0–100 по каждому критерию. Пропуск сохраняется как неизвестное. Каждому числу нужно основание.</p></div>' +
    Object.entries(meta.criteria).map(([key,label]) => field(label,"criterion_" + key,p.criteria?.[key]?.value,"number",'min="0" max="100" step="any"') +
      area("Основание: " + label,"reason_" + key,p.criteria?.[key]?.reason)).join("") +
    '<div class="subsection"><h3>Цена и полные затраты</h3></div>' +
    select("Статус гонорара","fee_status",{unknown:"Неизвестен",estimate:"Обоснованная оценка",reported:"Получено от стороны",published:"Опубликован"} ,fee.status || "unknown") +
    field("Валюта","fee_currency",fee.currency || research.brief.budget.currency) +
    field("Гонорар / права, нижняя сумма","fee_low",fee.low,"number",'min="0" step="any"') +
    field("Гонорар / права, верхняя сумма","fee_high",fee.high,"number",'min="0" step="any"') +
    field("Дата цены","fee_date",fee.valid_on || day(),"date") + area("Основание переноса цены для оценки","fee_derivation",fee.derivation) +
    field("Расходы сверх гонорара, минимум","extras_low",extras.low,"number",'min="0" step="any"') +
    field("Расходы сверх гонорара, максимум","extras_high",extras.high,"number",'min="0" step="any"') +
    '<label class="check field wide"><input type="checkbox" name="extras_complete" ' + (extras.complete ? "checked" : "") + '>Все существенные расходы сверх гонорара учтены</label>' +
    area("Состав и основание полноты расходов","extras_reason",extras.reason) +
    '<div class="subsection"><h3>Сценарий результата пакета</h3><p class="hint">Заполняйте при наличии подходящей истории и обоснования. Подписчики не подставляются как показы.</p></div>' +
    select("Метрика","forecast_metric",Object.fromEntries(meta.metrics.map(k => [k,metricNames[k]])),f.metric || "qualified_impressions") +
    field("Низкий сценарий","forecast_low",f.low,"number",'min="0" step="any"') +
    field("Базовый сценарий","forecast_base",f.base,"number",'min="0" step="any"') +
    field("Высокий сценарий","forecast_high",f.high,"number",'min="0" step="any"') +
    area("Основание сценариев","forecast_basis",f.basis) + area("Метод уникального охвата, если применимо","forecast_deduplication",f.deduplication) +
    sourcesField(p.source_ids || []) + area("Основание повторной оценки под текущий бриф","reassessment_reason","Оценки и условия проверены под текущую версию брифа",true) +
    '</div><div class="form-footer"><button class="primary" type="submit">Сохранить пакет и оценки</button></div></form>');
}
function decisionDialog(kind, id) {
  const title = {c_level_continue:"Разрешение на проработку",approve_offer:"Утверждение предложения",decline_offer:"Отказ от предложения"}[kind];
  showDialog(title,'<form id="decision-form"><input type="hidden" name="decision_kind" value="' + kind + '"><input type="hidden" name="target_id" value="' +
    esc(id) + '"><div class="form-grid">' + field("Кто принял решение","decision_maker","","text","required") +
    area("Решение и его основание","decision_reason","",true,"Зафиксируйте фактическое решение человека.") +
    '</div><div class="form-footer"><button class="primary" type="submit">Зафиксировать решение</button></div></form>');
}
function offerDialog() {
  const eligible = research.packages.filter(p => research.decisions.some(d => d.kind === "c_level_continue" && d.package_id === p.id && decisionCurrent(d,p)));
  showDialog("Полученное предложение",'<form id="offer-form"><div class="form-grid">' +
    select("Проработанный пакет","offer_package",Object.fromEntries(eligible.map(p => [p.id,p.name]))) +
    field("Представитель / источник ответа","representative","","text","required") + field("Цена, нижняя сумма","offer_low","","number",'min="0" step="any" required') +
    field("Цена, верхняя сумма","offer_high","","number",'min="0" step="any" required') +
    field("Валюта","offer_currency",research.brief.budget.currency,"text","required") + field("Дата условий","offer_date",day(),"date","required") +
    area("Ответ, доступность и прочие условия","offer_note","",true) + area("Изменённые права, если отличаются","offer_rights","",false,"Пустое поле сохраняет прежние права. Изменение прав обнулит прежнюю оценку и прогноз для пересмотра.") +
    sourcesField() + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить полученные условия</button></div></form>');
}

document.addEventListener("click", async event => {
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled || busy) return;
  try {
    const action = button.dataset.action, id = button.dataset.id;
    if (action === "theme") {
      const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = theme;
      button.textContent = theme === "dark" ? "☀" : "☾";
      button.setAttribute("aria-label", theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему");
      button.title = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
      try {localStorage.setItem("sponsor-theme", theme);} catch {}
    }
    else if (action === "new") newDialog();
    else if (action === "signed") signedDialog();
    else if (action === "close") closeDialog();
    else if (action === "home") {research = null;render();}
    else if (action === "open") await openResearch(id);
    else if (action === "tab") {tab = button.dataset.tab;render();window.scrollTo(0,0);}
    else if (action === "demo") {research = await api("/api/demo",{});tab = research.stage;await refreshList();render();}
    else if (action === "advance") {await act("advance",{},"Этап изменён");tab = research.stage;render();}
    else if (action === "source") sourceDialog();
    else if (action === "candidate") candidateDialog(id);
    else if (action === "package") packageDialog(id);
    else if (action === "continue") decisionDialog("c_level_continue",id);
    else if (action === "approve") decisionDialog("approve_offer",id);
    else if (action === "decline") decisionDialog("decline_offer",id);
    else if (action === "offer") offerDialog();
    else if (action === "assessment") assessmentDialog();
    else if (action === "entry") entryDialog(id);
    else if (action === "task-edit") {
      const t = research.tasks.find(t => t.id === id);
      showDialog("Изменить задачу", '<form id="task-form"><div class="form-grid">' + taskFields(t) + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить новую версию</button><span class="hint">Назначение нужно подтвердить повторно.</span></div></form>');
    } else if (action === "template-task") {
      const template = meta.activation_catalog.flatMap(p => p.templates).find(t => t.id === id);
      showDialog("Задача из шаблона", '<form id="task-form"><div class="form-grid">' + taskFields({},template) + '</div><div class="form-footer"><button class="primary" type="submit">Создать задачу</button></div></form>');
    } else if (action === "task-ack") {
      showDialog("Подтверждение назначения", '<form id="ack-form"><input type="hidden" name="task_id" value="' + esc(id) + '"><div class="form-grid">' +
        field("Кто подтвердил получение","confirmed_by","","text","required") + area("Содержание фактического ответа","ack_note","",true) + sourcesField() +
        '</div><div class="form-footer"><button class="primary" type="submit">Записать подтверждение</button></div></form>');
    } else if (action === "register-review") {
      showDialog("Сверка полноты реестра", '<form id="register-review-form"><div class="form-grid">' + field("Кто сверил договор и приложения","reviewer","","text","required") +
        area("Что сверено, версия договора и оставшиеся спорные условия","review_note","",true) + sourcesField() + '</div><div class="form-footer"><button class="primary" type="submit">Записать фактическую сверку</button></div></form>');
    } else if (action === "entry-waive") {
      showDialog("Снятие пункта с основанием", '<form id="entry-waive-form"><input type="hidden" name="entry_id" value="' + esc(id) + '"><div class="form-grid">' +
        field("Кто принял решение","reviewer","","text","required") + area("Основание изменения обязательства или отказа от права","waiver_reason","",true) + sourcesField() +
        '</div><div class="form-footer"><button class="primary" type="submit">Сохранить решение</button></div></form>');
    } else if (action === "pool") {
      showDialog("Проверка применимости пула", '<form id="pool-form"><div class="form-grid">' + select("Пул","pool_id",Object.fromEntries(meta.activation_catalog.map(p => [p.id,p.title]))) +
        select("Применимость","pool_status",{needs_clarification:"Нужно уточнить",applies:"Применяется",not_applicable:"Не применяется с основанием"}) + field("Проверяющий","pool_reviewer","","text","required") +
        area("Основание и оставшиеся вопросы","pool_reason","",true) + sourcesField() + '</div><div class="form-footer"><button class="primary" type="submit">Сохранить проверку</button></div></form>');
    }
    else if (action === "select") {
      const c = research.candidates.find(c => c.id === id);
      showDialog(c.selected ? "Убрать из выбранного пула" : "Выбор для глубокого анализа",
        '<form id="selection-form"><input type="hidden" name="candidate_id" value="' + esc(id) + '"><input type="hidden" name="selected" value="' +
        String(!c.selected) + '"><div class="form-grid">' + area("Основание выбора","selection_reason","",true) +
        '</div><div class="form-footer"><button class="primary" type="submit">Сохранить выбор</button></div></form>');
    } else if (action === "task-status") {
      showDialog("Обновить обязательство",'<form id="task-status-form"><input type="hidden" name="task_id" value="' + esc(id) +
        '"><div class="form-grid">' + select("Статус","task_status",taskNames,research.tasks.find(t => t.id === id).status) +
        area("Причина / комментарий","task_reason") + sourcesField() +
        '</div><div class="form-footer"><button class="primary" type="submit">Сохранить статус</button></div></form>');
    } else if (action === "history") {
      const history = await api("/api/research/" + encodeURIComponent(research.id) + "/history");
      showDialog("История исследования",'<div class="source-list">' + history.slice().reverse().map(e =>
        '<div class="source"><strong>Версия ' + e.revision + '</strong> · ' + esc(e.action) + '<small>' +
        esc(new Date(e.at).toLocaleString("ru-RU",{timeZone:"Europe/Riga"})) + ' · ' + esc(e.actor) + '</small></div>').join("") + '</div>');
    }
  } catch(error) {toast(error.message,true);}
});

document.addEventListener("submit", async event => {
  const formElement = event.target;
  if (!(formElement instanceof HTMLFormElement)) return;
  event.preventDefault();
  if (busy) return;
  formElement.querySelector(".form-error")?.remove();
  busy = true;document.body.classList.add("busy");
  const f = new FormData(formElement);
  try {
    const id = formElement.id;
    if (id === "create-form") {
      const previous = research;research = null;
      let brief;
      try {brief = readBrief(f);} finally {research = previous;}
      research = await api("/api/research",{title:f.get("research_title"),request:f.get("request"),brief});
      tab = research.stage;await refreshList();render();toast("Исследование создано");
    } else if (id === "signed-form") {
      const sourceId = "signed-material";
      research = await api("/api/activation", {title:f.get("signed_title"),kind:f.has("signed_synthetic") ? "synthetic" : "owner_brief",brief:{company:f.get("signed_company")},
        sources:[{id:sourceId,title:f.get("signed_source_title"),reference:f.get("signed_reference"),excerpt:f.get("signed_excerpt"),kind:f.has("signed_synthetic") ? "synthetic" : "owner_material",access:"provided_material",retrieved_on:f.get("signed_source_date")}],
        agreement:{partner:f.get("signed_partner"),currency:String(f.get("signed_currency")).toUpperCase(),start:f.get("signed_start"),end:f.get("signed_end"),note:f.get("signed_note"),source_ids:[sourceId]}});
      tab = research.stage;await refreshList();render();toast("Карточка исполнения создана");
    } else if (id === "brief-form") await act("update_brief",{brief:readBrief(f),reset_weights:true},"Новая версия брифа сохранена");
    else if (id === "source-form") await act("add_source",{title:f.get("source_title"),url:f.get("source_url"),reference:f.get("source_reference"),
      excerpt:f.get("source_excerpt"),kind:f.get("source_kind"),access:f.get("source_access"),retrieved_on:f.get("source_date")});
    else if (id === "candidate-form") {
      const old = research.candidates.find(c => c.id === f.get("candidate_id")) || {};
      const ids = sourceIds(f), followers = numeric(f,"followers"), platform = f.get("metric_platform");
      const metrics = [...(old.metrics || [])];
      if (platform && (followers != null || f.get("metric_precision") === "hidden")) metrics.push({
        platform,followers,precision:f.get("metric_precision"),observed_on:f.get("metric_date"),evidence_ids:ids});
      await act("save_candidate",{...old,id:old.id,name:f.get("candidate_name"),kind:f.get("candidate_kind"),official_url:f.get("candidate_url"),
        rationale:f.get("rationale"),queue:f.get("candidate_queue"),exclusion_reason:f.get("exclusion_reason"),source_ids:ids,metrics,
        platform_scan_complete:f.has("scan_complete"),risk:{status:f.get("risk_status"),reason:f.get("risk_reason"),source_ids:ids,human_reviewed:f.has("human_reviewed")}});
    } else if (id === "selection-form") await act("select_candidate",{candidate_id:f.get("candidate_id"),selected:f.get("selected") === "true",reason:f.get("selection_reason")});
    else if (id === "weights-form") await act("set_weights",{weights:Object.fromEntries(Object.keys(meta.criteria).map(k => [k,numeric(f,k)/100])),reason:f.get("weight_reason")});
    else if (id === "package-form") {
      const old = research.packages.find(p => p.id === f.get("package_id")) || {}, ids = sourceIds(f);
      const status = f.get("fee_status"), forecastBase = numeric(f,"forecast_base");
      await act("save_package",{...old,id:old.id,candidate_id:f.get("package_candidate"),name:f.get("package_name"),months:numeric(f,"package_months"),
        territory:listText(f.get("package_territory")).map(x => x.toUpperCase()),deliverables:f.get("deliverables"),rights:f.get("rights"),source_ids:ids,
        criteria:Object.fromEntries(Object.keys(meta.criteria).map(k => [k,{value:numeric(f,"criterion_"+k),reason:f.get("reason_"+k),source_ids:ids}])),
        fee:{status,low:status === "unknown" ? null : numeric(f,"fee_low"),high:status === "unknown" ? null : numeric(f,"fee_high"),
          currency:String(f.get("fee_currency")).toUpperCase(),basis:"this_package",source_ids:ids,valid_on:f.get("fee_date"),derivation:f.get("fee_derivation")},
        extra_costs:{low:numeric(f,"extras_low"),high:numeric(f,"extras_high"),complete:f.has("extras_complete"),reason:f.get("extras_reason")},
        forecast:forecastBase == null ? null : {metric:f.get("forecast_metric"),low:numeric(f,"forecast_low"),base:forecastBase,high:numeric(f,"forecast_high"),
          basis:f.get("forecast_basis"),deduplication:f.get("forecast_deduplication"),source_ids:ids},
        reassess:true,reassessment_reason:f.get("reassessment_reason")});
    } else if (id === "decision-form") {
      const kind = f.get("decision_kind");
      await act("decision",{kind,[kind === "c_level_continue" ? "package_id" : "offer_id"]:f.get("target_id"),
        reason:f.get("decision_reason"),decision_maker:f.get("decision_maker")});
    } else if (id === "offer-form") await act("receive_offer",{package_id:f.get("offer_package"),representative:f.get("representative"),note:f.get("offer_note"),
      source_ids:sourceIds(f),...(f.get("offer_rights") ? {rights:f.get("offer_rights")} : {}),
      fee:{status:"reported",low:numeric(f,"offer_low"),high:numeric(f,"offer_high"),currency:String(f.get("offer_currency")).toUpperCase(),valid_on:f.get("offer_date")}});
    else if (id === "campaign-form") {await act("start_campaign",{offer_id:f.get("offer_id"),start:f.get("campaign_start"),end:f.get("campaign_end"),
      agreement_note:f.get("agreement_note"),source_ids:sourceIds(f)},"Исходный план сохранён; кампания начата");tab = research.stage;render();}
    else if (id === "task-form") {
      const old = research.tasks.find(t => t.id === f.get("task_id")) || {}, entryId = f.get("task_entry");
      const allocation = entryId ? [{entry_id:entryId,quantity:numeric(f,"task_quantity")}] : [];
      await act(f.get("template_id") ? "template_task" : "save_task", {id:old.id,title:f.get("task_title"),template_id:f.get("template_id"),owner:f.get("task_owner"),due:f.get("task_due"),next_action:f.get("task_next"),
        acceptance:f.get("task_acceptance") || old.acceptance || "",pool_id:f.get("task_pool"),depends_on:sourceIds(f,"task_dependencies"),requires_ack:f.has("task_requires_ack"),allocations:[...allocation,...(old.allocations || []).slice(1)]});
    } else if (id === "ack-form") await act("acknowledge_task",{task_id:f.get("task_id"),confirmed_by:f.get("confirmed_by"),note:f.get("ack_note"),source_ids:sourceIds(f)});
    else if (id === "entry-form") await act("save_entry",{id:f.get("entry_id") || undefined,type:f.get("entry_type"),title:f.get("entry_title"),owner:f.get("entry_owner"),unit:f.get("entry_unit"),quantity:numeric(f,"entry_quantity"),contract_version:f.get("contract_version"),clause:f.get("clause"),start:f.get("entry_start"),end:f.get("entry_end"),request_by:f.get("request_by"),source_ids:sourceIds(f)});
    else if (id === "register-review-form") await act("review_register",{reviewer:f.get("reviewer"),note:f.get("review_note"),source_ids:sourceIds(f)});
    else if (id === "entry-waive-form") await act("waive_entry",{entry_id:f.get("entry_id"),reviewer:f.get("reviewer"),reason:f.get("waiver_reason"),source_ids:sourceIds(f)});
    else if (id === "pool-form") await act("save_pool",{pool_id:f.get("pool_id"),status:f.get("pool_status"),reason:f.get("pool_reason"),reviewer:f.get("pool_reviewer"),source_ids:sourceIds(f)});
    else if (id === "measurement-form") {
      const keys = ["metric","unit","population","owner","collection","deduplication","baseline","control","assignment","confounders","analysis","uncertainty","data_access","cost_scope","margin_definition","limitations","method","start","end"];
      await act("save_measurement",{...Object.fromEntries(keys.map(k => [k,f.get("measurement_"+k)])),target:numeric(f,"measurement_target"),source_ids:sourceIds(f)},"Новая версия плана сохранена");
    } else if (id === "assessment-form") {
      const packageId = f.get("assessment_package"), assessor = String(f.get("assessor")).trim(), pkg = research.packages.find(p => p.id === packageId);
      const previous = (research.assessments || []).filter(a => a.package_id === packageId && a.assessor.toLocaleLowerCase() === assessor.toLocaleLowerCase() &&
        a.brief_version === research.brief_version && a.weights_version === research.weights_version && a.package_version === pkg?.package_version).at(-1);
      await act("record_assessment",{package_id:packageId,assessor,rubric_version:f.get("rubric_version"),independence_note:f.get("independence_note"),
        ...(f.has("replace_assessment") && previous ? {supersedes:previous.id} : {}),criteria:Object.fromEntries(Object.keys(meta.criteria).map(k =>
          [k,{value:numeric(f,"assessment_"+k),reason:f.get("assessment_reason_"+k),source_ids:sourceIds(f,"assessment_sources_"+k)}]))});
    }
    else if (id === "task-status-form") await act("task_status",{task_id:f.get("task_id"),status:f.get("task_status"),reason:f.get("task_reason"),source_ids:sourceIds(f)});
    else if (id === "outcome-form") await act("record_outcome",{metric:f.get("outcome_metric"),value:numeric(f,"outcome_value"),scope:f.get("outcome_scope"),
      start:f.get("outcome_start"),end:f.get("outcome_end"),currency:String(f.get("outcome_currency")).toUpperCase(),deduplication:f.get("deduplication"),source_ids:sourceIds(f)});
    else if (id === "case-form") await act("close_case",{recommendation:f.get("recommendation"),lessons:f.get("lessons")},"Кейс завершён и сохранён");
    if ($("#dialog").open && formElement.closest("dialog")) closeDialog();
  } catch(error) {toast(error.message,true);}
  finally {busy = false;document.body.classList.remove("busy");}
});

async function start() {
  const themeButton = document.querySelector('[data-action="theme"]');
  if (themeButton && document.documentElement.dataset.theme === "dark") {
    themeButton.textContent = "☀";
    themeButton.setAttribute("aria-label", "Включить светлую тему");
    themeButton.title = "Включить светлую тему";
  }
  try {const session=await fetch('/auth/me');if(session.ok){window.sponsorSession=await session.json();const label=document.querySelector('.local-label');label.textContent=window.sponsorSession.username+' · '+window.sponsorSession.role;const logout=document.createElement('button');logout.textContent='Выйти';logout.onclick=async()=>{await api('/auth/logout',{});location.assign('/login');};label.after(logout);}meta = await api("/api/meta");await refreshList();render();}
  catch(error) {$("#main").textContent = "Не удалось открыть рабочее пространство: " + error.message;}
}
$("#dialog").addEventListener("cancel", event => {
  if (dialogStack.length) {event.preventDefault();closeDialog();}
});
start();
