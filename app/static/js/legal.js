import { html, useState, useEffect, api, store, set, nf, sum, Icon, tr, go, usePoll, useStore, Status, dt, nm } from "./lib.js";

const KINDS = [
  { k: "short", t: "Недопоставка или просрочка поставки", rate: 0.005, perDay: true, cap: 0.5, norm: "ст.25 Закона №670-I", who: "поставщик",
    text: "0,5% от суммы недопоставленного товара за каждый день просрочки, но не более 50% этой суммы" },
  { k: "quality", t: "Товар ненадлежащего качества", rate: 0.2, perDay: false, norm: "ст.26 Закона №670-I", who: "поставщик",
    text: "штраф 20% от стоимости некачественного (некомплектного) товара" },
  { k: "refuse", t: "Необоснованный отказ от оплаты", rate: 0.15, perDay: false, norm: "ст.32 Закона №670-I", who: "покупатель",
    text: "штраф 15% от суммы, от уплаты которой покупатель отказался" },
  { k: "late_pay", t: "Просрочка оплаты", rate: 0.004, perDay: true, cap: 0.5, norm: "ст.32 Закона №670-I", who: "покупатель",
    text: "пеня 0,4% от суммы просроченного платежа за каждый день, но не более 50% суммы" },
];

function Calc() {
  const [k, setK] = useState("short"); const [amount, setAmount] = useState(100_000_000); const [days, setDays] = useState(10);
  const K = KINDS.find(x => x.k === k);
  const raw = K.perDay ? amount * K.rate * days : amount * K.rate;
  const val = K.cap ? Math.min(raw, amount * K.cap) : raw;
  return html`<div class="card pad"><h3><${Icon} n="calc" s=${16}/> ${tr("Калькулятор неустойки")}</h3>
    <div class="choice">${KINDS.map(x => html`<button class=${k === x.k ? "on" : ""} onClick=${() => setK(x.k)}><span><b>${x.t}</b><span>${x.norm}</span></span></button>`)}</div>
    <div class="grid" style="grid-template-columns:1fr 1fr;gap:8px">
      <div class="field"><label>Сумма, сум</label><input class="inp mono" value=${nf(amount)} onInput=${e => setAmount(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>
      ${K.perDay && html`<div class="field"><label>Дней просрочки</label><input class="inp mono" value=${days} onInput=${e => setDays(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>`}
    </div>
    <div class="verdict"><div class="small muted">${K.norm} · платит ${K.who}</div><div class="mono" style="font-size:26px;font-weight:600">${sum(Math.round(val))}</div>
      <div class="small" style="color:var(--text2)">${K.text}.${K.cap && raw > amount * K.cap ? " Сработало ограничение 50%." : ""}</div></div>
    <p class="tiny muted" style="margin:8px 0 0">Суд вправе уменьшить неустойку, если она явно несоразмерна последствиям нарушения (ст.326 ГК). Санкции биржи (задаток, п.170–171 Правил UzEx) применяются клирингом автоматически.</p></div>`;
}

function Court() {
  const [amount, setAmount] = useState(50_000_000); const [small, setSmall] = useState(true);
  const BRV = 440_000;   // базовая расчётная величина с 01.09.2026
  const duty = Math.max(amount * 0.02, BRV) * (small ? 0.5 : 1);
  return html`<div class="card pad"><h3><${Icon} n="gavel" s=${16}/> Если дойдёт до суда</h3>
    <div class="field"><label>Цена иска, сум</label><input class="inp mono" value=${nf(amount)} onInput=${e => setAmount(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>
    <label class="consent"><input type="checkbox" checked=${small} onChange=${e => setSmall(e.target.checked)}/><span>Субъект малого бизнеса (госпошлина 50%)</span></label>
    <div class="verdict"><div class="small muted">Госпошлина в экономический суд (2% цены иска, не менее 1 БРВ)</div><div class="mono" style="font-size:22px;font-weight:600">${sum(Math.round(duty))}</div></div>
    <ul class="small" style="color:var(--text2);margin:10px 0 0;padding-left:18px">
      <li>Претензия: ответ — в течение 15 дней (ст.18 Закона №670-I). С 2018 года иск можно подать и без претензии, если её не требует договор (ст.19).</li>
      <li>Арбитражная комиссия биржи: решение окончательно внутри биржи; при несогласии сторона вправе обратиться в суд (п.57 Положения). Суды по-разному оценивают подведомственность — см. дела ниже.</li>
      <li>Суд может снизить неустойку при явной несоразмерности (ст.326 ГК).</li></ul></div>`;
}

export function LegalScreen() {
  const s = useStore();
  const [lg, setLg] = useState(null); const [deals, setDeals] = useState([]);
  useEffect(() => { api("/api/legal").then(setLg); }, []);
  usePoll(() => api("/api/deals").then(r => setDeals(r.deals.filter(d => ["disputed", "resolved", "annulled"].includes(d.status)))), 8000, [s.tick]);
  const ask = q => { set({ pendingAsk: q }); go("/agent"); };
  const qs = ["Продавец не отгрузил цемент в срок. Что мне положено по закону?", "Покупатель не оплатил. Что будет с задатком?",
    "Можно ли оспорить решение Арбитражной комиссии биржи в суде?", "Как правильно составить претензию поставщику?"];
  return html`<div class="grid" style="gap:16px">
    <div><div class="h1">${tr("Юрист")}</div><p class="sub">Права и защита по законодательству Узбекистана: ГК, Закон №670-I «О договорно-правовой базе деятельности хозяйствующих субъектов», Закон «О биржах и биржевой деятельности», Правила UzEx. Агент опирается только на эти нормы и реальные судебные акты.</p></div>
    <div class="grid two">
      <div class="grid"><${Calc}/><${Court}/></div>
      <div class="grid">
        <div class="card pad"><h3><${Icon} n="agent" s=${16}/> ${tr("Спросить агента")}</h3>
          ${qs.map(q => html`<button class="lrow click" style="width:100%;text-align:left;background:none;border:0;border-bottom:1px solid var(--line);color:var(--text)" onClick=${() => ask(q)}><span class="small">${q}</span><span class="sp"/><${Icon} n="arrow" s=${15}/></button>`)}</div>
        <div class="card pad"><h3><${Icon} n="gavel" s=${16}/> Мои споры и претензии</h3>
          ${!deals.length ? html`<p class="small muted">Споров нет. Если что-то пойдёт не так, ИИ-арбитр разберёт доказательства, а здесь появится претензия.</p>` :
            deals.map(d => html`<div class="lrow click" onClick=${() => go("/deals/" + d.id)}><span><b>${nf(d.qty)} т ${nm(d.instrument)}</b></span><span class="sp"/><${Status} s=${d.status}/></div>`)}</div>
      </div>
    </div>
    ${lg && html`<div class="card pad"><h3><${Icon} n="gavel" s=${16}/> ${tr("Судебная практика")}: реальные дела по биржевым сделкам UzEx</h3>
      ${lg.cases.map(c => html`<div style="padding:12px 0;border-bottom:1px solid var(--line)"><div class="row" style="flex-wrap:wrap"><a href=${c.source_url} target="_blank" rel="noopener"><b>Дело № ${c.case_number}</b></a><span class="chip tiny">${{ non_payment: "неоплата", non_delivery: "неотгрузка", other: "другое", penalty: "штраф" }[c.dispute_type] || c.dispute_type}</span><span class="sp"/><span class="small muted">${c.court} · ${c.date}</span></div>
        <div class="small" style="margin-top:6px">${c.facts}</div><div class="small" style="margin-top:6px"><span class="up">Итог:</span> ${c.outcome}</div>
        ${c.who_paid && html`<div class="tiny muted" style="margin-top:4px">Кто заплатил: ${c.who_paid}</div>`}</div>`)}
      <p class="tiny muted" style="margin-top:8px">Источник: publication.sud.uz — открытые судебные акты (полные тексты).</p></div>
    <div class="card pad"><h3><${Icon} n="law" s=${16}/> ${tr("Нормы права")}</h3>
      ${lg.norms.map(n => html`<div class="lrow" style="align-items:flex-start"><span style="flex:1"><b class="small">${n.code} ${n.article}</b><div class="small muted">${n.summary}</div></span>${n.url && html`<a class="small" href=${n.url} target="_blank" rel="noopener">lex.uz</a>`}</div>`)}</div>`}
  </div>`;
}
