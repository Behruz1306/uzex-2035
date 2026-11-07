import { html, useState, api, store, useStore, nf, sum, short, Icon, usePoll, useNow, countdown, time, dt, Status, toast, Modal, refreshMe } from "./lib.js";
import { TopUpForm } from "./onboarding.js";
import { Mandates } from "./agent.js";
import { CalendarCard } from "./market.js";

const NAMES = { cement: "Цемент", propane: "Сжиженный газ", ai92: "Бензин А-92", pp: "Полипропилен", urea: "Карбамид", wheat: "Пшеница", sugar: "Сахар", rebar: "Арматура" };

export function WalletScreen() {
  const s = useStore();
  const [d, setD] = useState(null); const [top, setTop] = useState(false);
  usePoll(() => api("/api/wallet").then(setD), 5000, [s.tick]);
  if (!d) return html`<div class="empty"><span class="spin"/></div>`;
  const b = d.balances;
  return html`<div class="grid">
    <div class="row" style="flex-wrap:wrap"><div><div class="h1">Кошелёк</div><p class="sub" style="margin:0">Счёт в клиринге биржи. Каждая операция — проводка двойной записи.</p></div><span class="sp"/>
      <button class="btn pri" onClick=${() => setTop(true)}><${Icon} n="plus"/> Пополнить</button></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
      <div class="card pad"><div class="small muted">Доступно</div><div class="mono" style="font-size:26px;font-weight:600">${sum(b.wallet)}</div></div>
      <div class="card pad"><div class="small muted">Заблокировано в задатках</div><div class="mono" style="font-size:26px;font-weight:600">${sum(b.blocked)}</div>
        <div class="tiny muted">Освобождается после исполнения или отмены заявки</div></div>
    </div>
    <div class="card" style="overflow-x:auto"><table class="tbl"><thead><tr><th>Время</th><th>Операция</th><th class="num">Сумма</th></tr></thead>
      <tbody>${d.ledger.map(r => html`<tr class=${r.ref_type === "settlement" || r.ref_id?.startsWith("D_") ? "click" : ""} onClick=${() => r.ref_id?.startsWith("D_") && (location.hash = "#/deals/" + r.ref_id)}>
        <td class="mono small">${dt(r.ts)}</td><td>${r.memo}<div class="tiny muted mono">${r.debit} → ${r.credit}</div></td>
        <td class="num ${r.internal ? "muted" : r.sign > 0 ? "up" : "down"}">${r.internal ? "⇄ " : r.sign > 0 ? "+" : "−"}${nf(r.amount)}</td></tr>`)}</tbody></table>
      ${!d.ledger.length && html`<div class="empty">Операций пока нет</div>`}</div>
    ${top && html`<${Modal} onClose=${() => setTop(false)}><div class="h1" style="font-size:20px">Пополнение</div><${TopUpForm} onOk=${() => { setTop(false); toast("Кошелёк пополнен"); }}/></${Modal}>`}
  </div>`;
}

export function ProfileScreen() {
  const s = useStore();
  const [d, setD] = useState(null);
  const load = () => api("/api/agent/memory").then(setD);
  usePoll(load, 10000, [s.tick]);
  if (!d) return html`<div class="empty"><span class="spin"/></div>`;
  const me = s.me, prof = JSON.parse(d.agent?.profile || "{}");
  const forget = async id => { await api("/api/agent/memory/" + id, { method: "DELETE" }); load(); };
  const label = { preference: "предпочтение", fact: "факт", feedback: "решение" };
  return html`<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr));align-items:start">
    <div class="card pad"><div class="row"><div class="av" style="width:52px;height:52px;font-size:22px">${(d.agent?.name || "A")[0]}</div>
      <div><div class="h1" style="font-size:20px;margin:0">${d.agent?.name}</div><div class="small muted">личный агент · ${prof.business || "занятие не указано"}</div></div></div>
      <dl class="kv" style="margin-top:14px">
        <dt>Владелец</dt><dd style="font-family:var(--sans)">${me.name}</dd>
        <dt>Проверка MyID</dt><dd>${me.verified ? "пройдена" : "нет"} · ПИНФЛ ${me.pinfl_masked || "—"}</dd>
        <dt>Статус</dt><dd style="font-family:var(--sans)">${{ individual: "физлицо", self_employed: "самозанятый", ip: "ИП", company: "компания" }[me.status] || "—"} ${me.inn ? "· " + me.inn : ""}</dd>
        <dt>Регион</dt><dd style="font-family:var(--sans)">${me.region}</dd>
        <dt>Стиль торговли</dt><dd style="font-family:var(--sans)">${{ cautious: "осторожный", balanced: "сбалансированный", fast: "быстрый" }[prof.risk] || "—"}</dd>
        <dt>Ключ подписи</dt><dd>Ed25519 · ${me.sign_pub}…</dd></dl>
      <button class="btn" style="margin-top:12px" onClick=${async () => { const r = await api("/api/telegram/link", { body: {} }); if (r.url) window.open(r.url, "_blank"); else toast("Telegram", r.note); }}>
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path fill="#229ED9" d="M21.9 4.3c.3-1.2-.9-2.2-2-1.7L2.8 9.2c-1.2.5-1.1 2.2.1 2.6l4.3 1.4 1.7 5.3c.3 1 1.6 1.3 2.3.5l2.4-2.5 4.4 3.2c.9.7 2.2.2 2.5-.9l1.4-14.5z"/></svg>
        Уведомления в Telegram</button>
      <p class="hint" style="margin-top:12px">Агент действует только в границах подписанных вами поручений. Ключ хранится в защищённом хранилище биржи и используется после подтверждения PIN-кодом.</p></div>
    <div class="card pad"><h3>Что агент узнал о вас</h3>
      ${!d.memory.length && html`<p class="small muted">Пока ничего. Агент запоминает важное из разговоров и ваших решений — и подстраивается.</p>`}
      ${d.memory.map(m => html`<div class="row" style="padding:7px 0;border-bottom:1px solid var(--line)"><span class="chip tiny">${label[m.kind] || m.kind}</span><span class="small" style="flex:1">${m.text}</span>
        <button class="btn sm ghost" title="Забыть" onClick=${() => forget(m.id)}><${Icon} n="x" s=${14}/></button></div>`)}
      ${d.stats.length > 0 && html`<h3 style="margin-top:14px">Как вы торгуете</h3><table class="tbl"><tbody>${d.stats.map(x => html`<tr><td>${NAMES[x.instrument]}</td><td class="num">${x.n} поруч.</td><td class="num">${nf(x.bought)} т</td><td class="num">лимит ~${nf(x.avg_limit)}</td></tr>`)}</tbody></table>`}
    </div>
    <div class="card pad mobile-links"><h3>Разделы</h3>
      ${[["wallet", "Кошелёк", "wallet"], ["legal", "Юрист", "law"], ["ops", "Пульт биржи", "ops"]].map(([k, l, ic]) => html`<button class="lrow click" style="width:100%;background:none;border:0;border-bottom:1px solid var(--line);color:var(--text)" onClick=${() => location.hash = "#/" + k}><${Icon} n=${ic}/><span>${l}</span><span class="sp"/><${Icon} n="arrow" s=${15}/></button>`)}
      <button class="btn ghost sm" style="margin-top:8px" onClick=${() => { try { localStorage.removeItem("uzx_token"); } catch (e) {} location.hash = ""; location.reload(); }}>Выйти</button></div>
    <${Mandates}/>
    <${CalendarCard}/>
  </div>`;
}

export function OpsScreen() {
  const s = useStore();
  const [o, setO] = useState(null); const [ig, setIg] = useState(null); const [lg, setLg] = useState(null); const [it, setIt] = useState(null);
  usePoll(() => api("/api/ops/overview").then(setO), 4000, [s.tick]);
  usePoll(() => { api("/api/ops/integrity").then(setIg); api("/api/legal").then(setLg); api("/api/ops/integrations").then(setIt); }, 600000, []);
  const scen = async x => { await api("/api/ops/scenario", { body: { scenario: x } }); toast("Сценарий установлен", "Применится к следующей сделке пользователя"); setO({ ...o, scenario: x }); };
  const approve = async id => { try { await api(`/api/ops/disputes/${id}/approve`, { body: {} }); toast("Решение утверждено"); } catch (e) { toast("Ошибка", e.message); } };
  if (!o) return html`<div class="empty"><span class="spin"/></div>`;
  const ds = Object.fromEntries(o.deals_by_status.map(x => [x.status, x.n]));
  return html`<div class="grid">
    <div><div class="h1">Пульт биржи и регулятора</div><p class="sub">Биржа в модели 2035 — не посредник, а честные правила, гарант расчётов и судья. Здесь она видит рынок целиком.</p></div>
    <div class="sess" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="stat"><b>${o.users}</b><span>людей с агентами</span></div>
      <div class="stat"><b>${o.sessions_today.n}</b><span>сессий проведено</span></div>
      <div class="stat"><b>${short(o.sessions_today.v)}</b><span>оборот песочницы, сум</span></div>
      <div class="stat"><b>${o.pools}</b><span>общих лотов мелких покупателей</span></div>
      <div class="stat"><b>${(ds.settled || 0) + (ds.resolved || 0)}</b><span>сделок завершено</span></div>
      <div class="stat"><b>${ds.disputed || 0}</b><span>споров в работе</span></div>
    </div>
    <div class="card pad"><h3>Сценарий для демонстрации жюри</h3>
      <p class="small muted" style="margin-top:0">Следующая сделка пользователя пройдёт по выбранному сценарию — чтобы показать, как биржа определяет виновного.</p>
      <div class="chips">${[["normal", "Всё честно"], ["short_loading", "Продавец недогрузил"], ["transit_loss", "Потеря в пути (перевозчик)"], ["no_shipment", "Продавец не отгрузил"]]
        .map(([k, l]) => html`<button class=${o.scenario === k ? "on" : ""} onClick=${() => scen(k)}>${l}</button>`)}</div></div>
    <div class="card" style="overflow-x:auto"><div class="pad" style="padding:14px 18px 0"><h3>Споры — ИИ предлагает, человек утверждает</h3></div>
      <table class="tbl"><thead><tr><th>Время</th><th>Сделка</th><th>Причина</th><th>Вина</th><th>Статус</th><th/></tr></thead><tbody>
      ${o.disputes.map(x => { const f = JSON.parse(x.fault || "{}"); return html`<tr><td class="mono small">${dt(x.created_at)}</td><td>${NAMES[x.instrument]} · ${nf(x.qty)} т</td>
        <td class="small">${{ short_weight: "недовес", non_delivery: "неотгрузка", other: "другое" }[x.reason] || x.reason}</td>
        <td class="small">${Object.entries(f).map(([k, v]) => `${{ seller: "продавец", carrier: "перевозчик", buyer: "покупатель", unclear: "неясно" }[k]} ${Math.round(v * 100)}%`).join(", ") || "…"}</td>
        <td><span class="chip ${x.status === "resolved" ? "ok" : x.status === "needs_review" ? "bad" : "ag"}">${{ analyzing: "анализ", proposed: "предложено", needs_review: "нужна перевеска", resolved: "исполнено" }[x.status]}</span></td>
        <td>${x.status === "needs_review" || x.status === "proposed" ? html`<button class="btn sm" onClick=${() => approve(x.id)}>Утвердить</button>` : ""}</td></tr>`; })}
      </tbody></table>${!o.disputes.length && html`<div class="empty">Споров нет</div>`}</div>
    ${it && html`<div class="card pad"><h3><${Icon} n="check" s=${16}/> Готовность к запуску</h3>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
        <div><h3>Интеграции</h3>${it.integrations.map(i => html`<div class="lrow"><span style="flex:1"><b class="small">${i.name}</b><div class="tiny muted">${i.purpose}</div></span>
          ${i.live ? html`<span class="chip ok">боевой режим</span>` : i.implemented ? html`<span class="chip ag">реализовано · нужны ключи</span>` : html`<span class="chip">план</span>`}
          <a class="tiny" href=${i.docs_url} target="_blank" rel="noopener">docs</a></div>`)}</div>
        <div><h3>Право и комплаенс</h3>${it.compliance.map(c => html`<div class="lrow" style="align-items:flex-start"><span style="flex:1"><b class="small">${c.item}</b><div class="tiny muted">${c.how}</div></span>
          <span class="chip ${c.status === "done" || c.status === "ready" ? "ok" : c.status === "todo" ? "bad" : "ag"}">${{ done: "готово", ready: "готово", partial: "частично", todo: "до запуска", regulatory: "нужно решение регулятора" }[c.status]}</span></div>`)}</div>
      </div></div>`}
    ${ig && html`<div class="card pad"><h3><${Icon} n="shield" s=${16}/> Щит честности — анализ реального реестра (${ig.source})</h3>
      <div class="sess" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-bottom:14px">
        <div class="stat"><b>${ig.annulled_share_pct}%</b><span>сделок срываются из-за неоплаты</span></div>
        <div class="stat"><b>${ig.serial_count}</b><span>покупателей сорвали ≥30 сделок</span></div>
        <div class="stat"><b>${ig.top1pct_share}%</b><span>оборота у 1% покупателей</span></div>
        <div class="stat"><b>${ig.median_deal_mln} млн</b><span>медианная сделка — мелким не по силам</span></div>
      </div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
        <div><h3>Систематические срывщики задатков</h3><table class="tbl"><tbody>${ig.serial_nonpayers.map(r => html`<tr><td class="small">${r.name}<div class="tiny muted mono">ИНН ${r.inn}</div></td><td class="num">${r.annulled} срывов</td></tr>`)}</tbody></table>
          <p class="tiny muted">В модели 2035 агент такого участника не допустит к дефицитным торгам без повышенного задатка.</p></div>
        <div><h3>Зависимость продавца от одного покупателя</h3><table class="tbl"><tbody>${ig.dependency.map(r => html`<tr><td class="small">${r.seller} → ${r.buyer}</td><td class="num">${r.share_pct}%</td></tr>`)}</tbody></table>
          <p class="tiny muted">Высокая доля одного покупателя — сигнал проверить аффилированность.</p></div>
      </div></div>`}
    ${lg && html`<div class="card pad"><h3><${Icon} n="gavel" s=${16}/> Правовая база арбитра: реальные дела судов Узбекистана</h3>
      ${lg.cases.map(c => html`<div style="padding:10px 0;border-bottom:1px solid var(--line)"><div class="row"><a href=${c.source_url} target="_blank" rel="noopener"><b>Дело № ${c.case_number}</b></a><span class="sp"/><span class="small muted">${c.court} · ${c.date}</span></div>
        <div class="small" style="margin-top:4px">${c.facts}</div><div class="small up" style="margin-top:4px">Итог: ${c.outcome}</div></div>`)}
      <p class="tiny muted" style="margin-top:8px">Источник: publication.sud.uz — открытые судебные акты. Нормы: ${lg.norms.length} статей ГК, Закона о договорно-правовой базе, Закона о биржах и Правил UzEx.</p></div>`}
  </div>`;
}
