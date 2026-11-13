"""Portable diagnostic reports, with no remote assets or executable input."""

from html import escape

from packages.domain.models import CRITERIA
from packages.scoring.diagnostics import GATE_LABELS, RELATION_LABELS

FEE_LABELS = {"unknown": "неизвестна", "estimated": "оценочная", "reported": "получена от стороны", "published": "опубликована"}


def fmt(value):
    return "—" if value is None else f"{value:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def interval(values):
    return "—" if values is None else " … ".join(fmt(v) for v in values)


def md(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ").replace("<", "&lt;").replace(">", "&gt;")


def status(row):
    if row["gates"]:
        return "; ".join(GATE_LABELS.get(g, g) for g in row["gates"])
    return "Можно сравнивать; коммерческие условия проверяются отдельно"


def request_text(item):
    result = item["question"]
    if item["score_width"] is not None:
        result += f". Ширина пропуска в итоговом балле: {fmt(item['score_width'])} при текущих весах"
    if "tie_score_at_base_weights" in item:
        threshold = item["tie_score_at_base_weights"]
        if threshold > 100 + 1e-8:
            result += ". Даже 100 по этому критерию не достигает текущего лидера"
        elif threshold < -1e-8:
            result += ". Даже 0 по этому критерию выше текущего лидера"
        else:
            result += f". Равенство с текущим лидером при оценке {fmt(max(0, min(100, threshold)))} из 100"
        result += "; остальные оценки и текущие веса зафиксированы. Это порог для проверки, не целевая оценка"
    return result


def markdown(report):
    lines = [f"# Диагностика устойчивости: {md(report['title'])}", "",
             "**СИНТЕТИЧЕСКИЙ ПРИМЕР**" if report["kind"] == "synthetic" else "**Рабочие данные: выводы требуют проверки человеком**", "",
             f"Дата расчёта: {report['as_of_date']}; исследование `{md(report['research_id'])}`, revision {report['research_revision']}; "
             f"бриф v{report['brief_version']}, веса v{report['weights_version']}. Диагностика `{report['diagnostic_version']}`.", "",
             f"Вес каждого критерия: ±{fmt(report['weight_radius_pp'])} п.п. при сумме 100%. "
             f"Отклонение пригодных оценок (баллы): ±{fmt(report['score_radius'])}; пропуски: 0–100. Это заданные допущения.", "",
             "## Матрица пакетов", "",
             "| Кандидат / пакет | Текущий балл | Границы при изменении допущений | Текущее место | Условные границы места | Основания / ограничения |",
             "| --- | ---: | --- | ---: | --- | --- |"]
    for row in report["rows"]:
        lines.append(f"| {md(row['candidate'])} / {md(row['package'])} ({md(row['package_id'])}) | {fmt(row['base_score'])} | "
                     f"{interval(row['stress_bounds'])} | {fmt(row['base_rank'])} | {interval(row['conditional_rank_bounds'])} | {md(status(row))} |")
    lines += ["", "Условные границы мест относятся к диагностическому пулу, включая пропуски 0–100. "
              "Они консервативны, не являются точным множеством достижимых мест и не дают пропущенным данным фактический ранг.", "",
              "## Парные сравнения", "", "Разность = балл первого минус балл второго. Общие веса используются для обоих пакетов.", ""]
    for pair in report["pairs"]:
        lines.append(f"- {md(pair['a'])} / {md(pair['b'])}: {interval(pair['gap_bounds'])}; {RELATION_LABELS[pair['relation']]}. "
                     + ("Есть пропуски: вывод условный." if pair["conditional_on_missing"] else ""))
        for label, key in (("Минимум", "min_witness"), ("Максимум", "max_witness")):
            witness = pair[key]
            lines.append(f"  {label}: веса " + "; ".join(f"{k}={fmt(v * 100)}%" for k, v in witness["weights"].items()) +
                         "; оценки первого " + "/".join(fmt(witness["a_scores"][k]) for k in CRITERIA) +
                         "; второго " + "/".join(fmt(witness["b_scores"][k]) for k in CRITERIA) + ".")
    if not report["pairs"]:
        lines.append("При текущих ограничениях нет двух пакетов для парного сравнения.")
    lines += ["", "## Что проверить дальше", "", "Группы: ограничения → пробелы оценок → коммерческие условия. "
              "Внутри пробелов порядок по ширине балла; это не оценка денежной ценности информации.", ""]
    lines += [f"- {md(item['package_id'])}: {md(request_text(item))}." for item in report["requests"]]
    if not report["requests"]:
        lines.append("Структурных запросов нет. Это не подтверждает истинность данных или готовность сделки.")
    lines += ["", "## Зависимости от источников", ""]
    lines += [f"- {md(source['source_id'])}: {md(source['title'])}; access={md(source['access'])}; "
              f"{len(source['fields'])} полей: {md(', '.join(source['fields']))}." for source in report["source_dependencies"]]
    lines += ["", "Несколько полей с одним источником не являются независимыми подтверждениями. Карта охватывает только ссылки критериев.", "",
              "## Границы вывода", ""] + ["- " + line for line in report["limits"]]
    return "\n".join(lines) + "\n"


def html(report):
    e = lambda value: escape(str(value), quote=True)
    by_id = {r["package_id"]: r for r in report["rows"]}
    bars, table, pairs, tasks, dependencies = [], [], [], [], []
    for row in report["rows"]:
        bounds = row["stress_bounds"]
        band = "<span>Нужна переоценка под текущий бриф</span>"
        if bounds:
            low, high = (min(100., max(0., n)) for n in bounds)
            band = f'<span class="band" style="left:{low:.8f}%;width:{high-low:.8f}%"></span>'
            if row["base_score"] is not None:
                band += f'<span class="point" style="left:{row["base_score"]:.8f}%"></span>'
        bars.append(f'<div class="plot-row"><div><strong>{e(row["candidate"])}</strong><span class="muted">{e(row["package"])}</span></div>'
                    f'<div class="track" role="img" aria-label="Границы балла: {e(interval(bounds))}; текущий балл: {e(fmt(row["base_score"]))}">{band}</div>'
                    f'<div class="numeric">{e(interval(bounds))}<small>{"вне сравнения" if not row["eligible_for_diagnostic"] else "условные границы" if row["missing"] else "при изменении допущений"}</small></div></div>')
        table.append(f'<tr><th scope="row">{e(row["candidate"])}<small>{e(row["package_id"])}</small></th>'
                     f'<td>{e(fmt(row["base_score"]))}</td><td>{e(fmt(row["coverage"]*100))}%</td>'
                     f'<td>{e(fmt(row["base_rank"]))}</td><td>{e(interval(row["conditional_rank_bounds"]))}</td>'
                     f'<td>{e(status(row))}<small>Бюджет: {e(row["economics"]["reason"])}. Статус цены: {e(FEE_LABELS.get(row["fee_status"], row["fee_status"]))}</small></td></tr>')
    for pair in report["pairs"]:
        a, b = by_id[pair["a"]], by_id[pair["b"]]
        scenarios = []
        for label, key in (("Минимальная разность", "min_witness"), ("Максимальная разность", "max_witness")):
            witness = pair[key]
            body = "".join(f'<tr><th scope="row">{e(CRITERIA[k])}</th><td>{e(fmt(witness["weights"][k]*100))}%</td>'
                           f'<td>{e(fmt(witness["a_scores"][k]))}</td><td>{e(fmt(witness["b_scores"][k]))}</td></tr>' for k in CRITERIA)
            scenarios.append(f'<h3>{label}</h3><div class="table-wrap"><table><thead><tr><th>Критерий</th><th>Вес</th><th>Первый</th><th>Второй</th></tr></thead><tbody>{body}</tbody></table></div>')
        pairs.append(f'<details><summary><span>{e(a["candidate"])} / {e(a["package"])} ↔ {e(b["candidate"])} / {e(b["package"])}</span>'
                     f'<strong>{e(RELATION_LABELS[pair["relation"]])}</strong></summary><p>Разность первого и второго: <b>{e(interval(pair["gap_bounds"]))}</b> балла. '
                     f'{"Пропуски меняются от 0 до 100: вывод условный." if pair["conditional_on_missing"] else ""}</p>'
                     + "".join(scenarios) + '</details>')
    groups = {"gate": "Ограничение", "evidence": "Данные", "commercial": "Условия"}
    for item in report["requests"]:
        tasks.append(f'<li><span class="tag">{groups[item["group"]]}</span> <b>{e(item["package_id"])}</b><p>{e(request_text(item))}.</p></li>')
    for source in report["source_dependencies"]:
        dependencies.append(f'<details><summary>{e(source["title"])} <strong>{len(source["fields"])} полей</strong></summary><p>{e(source["source_id"])} · {e(source["access"])}</p><ul>'
                            + ''.join(f'<li>{e(field)}</li>' for field in source["fields"]) + '</ul></details>')
    assumptions = " · ".join(f'{e(CRITERIA[k])}: {e(fmt(v*100))}%' for k, v in report["weights"].items())
    return '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Диагностика устойчивости — Sponsorship Activation</title>
<style>
:root{color-scheme:light;--paper:#f6f5ef;--ink:#1c302e;--muted:#536a65;--line:#cfdbd4;--accent:#b7542e;--green:#356a5b}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{max-width:1200px;margin:auto;padding:42px 32px 70px}header{border-bottom:2px solid var(--ink);padding-bottom:30px}h1{font-size:clamp(30px,4vw,52px);line-height:1.08;max-width:850px;letter-spacing:-.035em;margin:16px 0}
h2{font-size:25px;line-height:1.25;letter-spacing:-.02em;margin:0 0 12px}h3{font-size:17px;margin-top:24px}p{max-width:920px}.eyebrow{letter-spacing:.12em;font-size:12px;font-weight:700;text-transform:uppercase}.muted,small{color:var(--muted)}small,.muted{display:block}small{font-size:13px}.tag{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);font-weight:700}.notice{font-weight:600;color:var(--accent)}
nav{display:flex;gap:12px 24px;flex-wrap:wrap;padding:16px 0;border-bottom:1px solid var(--line)}a{color:var(--green);text-underline-offset:4px}section{padding-top:40px}.flow{list-style:none;display:grid;grid-template-columns:repeat(4,1fr);gap:18px;padding:0;counter-reset:step}.flow li{border-top:2px solid var(--green);padding-top:12px}.flow li:before{counter-increment:step;content:counter(step,decimal-leading-zero);color:var(--accent);display:block;margin-bottom:8px;font-variant-numeric:tabular-nums}.flow strong{display:block}
.axis,.plot-row{display:grid;grid-template-columns:minmax(180px,1fr) 2fr 180px;gap:22px;align-items:center}.axis{font-size:13px;color:var(--muted)}.ticks{display:flex;justify-content:space-between}.plot-row{padding:20px 0;border-bottom:1px solid var(--line)}.plot-row strong{font-weight:600}.numeric{font-variant-numeric:tabular-nums;text-align:right}.track{height:22px;position:relative;background:#e1e7e1;border-radius:2px;font-size:12px}.band{position:absolute;top:5px;height:12px;background:var(--green);min-width:2px}.point{position:absolute;top:0;width:3px;height:22px;background:var(--accent);transform:translateX(-50%)}.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:14px}.legend i{display:inline-block;width:18px;height:8px;background:var(--green);margin-right:8px}.legend .dot{width:3px;height:16px;background:var(--accent);vertical-align:middle}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--line)}thead th{font-weight:600;color:var(--muted)}tbody th{font-weight:500}td{font-variant-numeric:tabular-nums}details{border-top:1px solid var(--line);padding:16px 0}details:last-child{border-bottom:1px solid var(--line)}summary{cursor:pointer;padding:6px 0;overflow-wrap:anywhere}summary strong{display:block;margin-left:20px;color:var(--green)}details table{max-width:780px}li{overflow-wrap:anywhere}.requests{padding-left:24px}.requests li{padding:16px 0;border-bottom:1px solid var(--line)}.requests p{margin:6px 0}footer{margin-top:38px;border-top:2px solid var(--ink);padding-top:20px;font-size:13px;overflow-wrap:anywhere}code{overflow-wrap:anywhere}
@media(max-width:700px){main{padding:24px 18px 40px}.flow{grid-template-columns:repeat(2,1fr)}.plot-row{grid-template-columns:1fr}.axis{display:block}.axis>span{display:none}.numeric{text-align:left}.plot-row{gap:10px}h2{font-size:22px}#matrix table{min-width:620px}details th,details td{padding:10px 5px}}
@media print{nav{display:none}body{background:white}main{padding:0}details{break-inside:avoid}section{break-inside:auto}summary{list-style:none}}
</style></head><body><main>
''' + f'''<header><div class="eyebrow">Sponsorship Activation / лаборатория решений / {e(report['as_of_date'])}</div>
<h1>Насколько устойчив выбор пакета?</h1><p>{e(report['title'])}</p>
<p class="notice">{'СИНТЕТИЧЕСКИЙ ПРИМЕР — кандидаты, оценки и условия вымышлены.' if report['kind']=='synthetic' else 'Рабочий снимок — выводы требуют проверки человеком.'}</p>
<p>Диагностика показывает, что происходит при изменении предположений, и какие сведения стоит уточнить.</p></header>
<nav aria-label="Разделы"><a href="#ranges">Границы баллов</a><a href="#matrix">Матрица</a><a href="#pairs">Парные сравнения</a><a href="#next">Следующая проверка</a><a href="#sources">Зависимости</a></nav>
<section><h2>Логика проверки</h2><ol class="flow"><li><strong>Ограничения</strong>Версия брифа, выбор человека, риск и сопоставимость.</li><li><strong>Основания</strong>Источник по каждому критерию; пропуск остаётся неизвестным.</li><li><strong>Чувствительность</strong>Общие веса и диапазоны исходных оценок.</li><li><strong>Следующее действие</strong>Получить данные, разобрать компромисс, передать человеку.</li></ol></section>
<section id="ranges"><h2>Границы баллов при заданных допущениях</h2><p>Веса: ±{e(fmt(report['weight_radius_pp']))} п.п., сумма всегда 100%. Отклонение пригодных оценок (баллы): ±{e(fmt(report['score_radius']))}. Пропуски: 0–100. Это экспериментальные настройки, а не оценённая статистическая ошибка.</p>
<p class="muted">{assumptions}</p><div class="legend"><span><i></i>Возможный диапазон</span><span><i class="dot"></i>Текущий балл</span></div>
<div class="axis"><span>Кандидат / пакет</span><div class="ticks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><span>Баллы</span></div>{''.join(bars)}
<p class="muted">Интервалы не являются вероятностями или доверительными интервалами. Балл вне допуска показывается только для объяснения.</p></section>
<section id="matrix"><h2>Пригодность, данные и допуск — отдельно</h2><div class="table-wrap"><table><thead><tr><th>Кандидат / пакет</th><th>Балл</th><th>Покрытие весов</th><th>Место сейчас</th><th>Границы места</th><th>Ограничения и условия</th></tr></thead><tbody>{''.join(table)}</tbody></table></div>
<p class="muted">Границы мест условны и консервативны: они включают пакеты с пропусками, но исключают остальные ограничения. Парные крайности не всегда достижимы одновременно. Покрытие не означает уверенность в данных.</p></section>
<section id="pairs"><h2>Где меняется предпочтение</h2><p>Раскройте пару, чтобы увидеть проверяемые значения весов и оценок для минимальной и максимальной разности.</p>{''.join(pairs) or '<p>Нет двух сопоставимых пакетов. Сначала устранить ограничения или добавить материалы.</p>'}</section>
<section id="next"><h2>Что проверить дальше</h2><p>Сначала ограничения, затем пробелы оценок и коммерческие условия. Пробелы упорядочены по ширине балла при текущих весах; денежная ценность информации не рассчитана.</p><ol class="requests">{''.join(tasks) or '<li>Структурных запросов нет. Истинность данных и готовность сделки этим не подтверждаются.</li>'}</ol></section>
<section id="sources"><h2>Какие оценки зависят от одного источника</h2><p>Это карта ссылок критериев. Число заполненных полей не является числом независимых подтверждений.</p>{''.join(dependencies) or '<p>Ссылок критериев на источники нет.</p>'}</section>
<section><h2>Границы вывода</h2><ul>{''.join('<li>'+e(line)+'</li>' for line in report['limits'])}</ul></section>
<footer>Исследование: {e(report['research_id'])} · revision {report['research_revision']} · бриф v{report['brief_version']} · веса v{report['weights_version']}<br>Модель: {e(report['model_version'])} · диагностика: {e(report['diagnostic_version'])}<br>Время расчёта UTC: {e(report['generated_at'])}. Отчёт самодостаточен, внешние ресурсы не загружаются.</footer>
</main></body></html>'''
