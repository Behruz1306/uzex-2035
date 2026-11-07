import { html, useState, useEffect, useRef, api, store, useStore, nf, sum, Icon, usePoll, useNow, countdown, time, dt, Status, toast, short, md } from "./lib.js";

const NAMES = { cement: "Цемент", propane: "Сжиженный газ", ai92: "Бензин А-92", pp: "Полипропилен", urea: "Карбамид", wheat: "Пшеница", sugar: "Сахар", rebar: "Арматура" };
const EV = {
  matched: ["Сделка заключена на аукционе", ""], document: ["Документ сформирован и подписан", ""], paid: ["Деньги поступили в сейф биржи", "ok"],
  loaded: ["Погрузка: вес и пломба зафиксированы", ""], gps_anomaly: ["GPS: отклонение от маршрута", "warn"], arrived: ["Машина прибыла", ""],
  unloaded: ["Выгрузка: вес на весах покупателя", ""], settled: ["Расчёт: продавец получил оплату", "ok"], dispute_opened: ["Открыт спор", "warn"],
  decision_proposed: ["ИИ-арбитр предложил решение", ""], decision_executed: ["Решение исполнено", "ok"], annulled_nonpayment: ["Аннулирована: нет оплаты", "warn"],
  ship_deadline_missed: ["Срок отгрузки пропущен", "warn"], forward_due: ["Наступил срок поставки по зафиксированной цене", "ok"], auto_accepted: ["Принято автоматически по истечении окна", "warn"],
};
const DOCK = { contract: "ДОГ", invoice: "ЭСФ", ttn: "ТТН", acceptance: "АКТ", decision: "РЕШ", claim: "ПРЕТ" };

export function DealsScreen({ id }) {
  return id ? html`<${Deal} id=${id} key=${id}/>` : html`<${DealList}/>`;
}

function DealList() {
  const s = useStore();
  const [rows, setRows] = useState(null);
  usePoll(() => api("/api/deals").then(d => setRows(d.deals)), 5000, [s.tick]);
  return html`<div><div class="h1">Сделки</div><p class="sub">Каждую сделку агент ведёт сам: оплата в сейф, отгрузка, дорога, приёмка, расчёт. Вы вмешиваетесь, только когда нужно ваше решение.</p>
    <div class="card" style="overflow-x:auto">${rows === null ? html`<div class="empty"><span class="spin"/></div>` : !rows.length ? html`<div class="empty">Сделок пока нет. Дайте поручение агенту — первая сделка появится после ближайшей торговой сессии.</div>` : html`
      <table class="tbl"><thead><tr><th>Время</th><th>Товар</th><th>Продавец</th><th class="num">Объём</th><th class="num">Цена</th><th class="num">Сумма</th><th>Статус</th></tr></thead>
      <tbody>${rows.map(d => html`<tr class="click" onClick=${() => location.hash = "#/deals/" + d.id}>
        <td class="mono">${dt(d.created_at)}</td><td>${NAMES[d.instrument]}${d.pool_id ? html` <span class="chip ag tiny">общий лот</span>` : ""}</td><td class="small">${d.seller_info?.name}</td>
        <td class="num">${nf(d.qty)} т</td><td class="num">${nf(d.price)}</td><td class="num">${short(d.amount)}</td><td><${Status} s=${d.status}/></td></tr>`)}</tbody></table>`}</div></div>`;
}

const STEPS = [["signed", "Договор"], ["paid", "Оплата в сейф"], ["in_transit", "В пути"], ["delivered", "Приёмка"], ["settled", "Расчёт"]];

function Stepper({ s }) {
  const order = ["signed", "paid", "in_transit", "delivered", "settled"];
  const idx = s === "disputed" || s === "resolved" ? 3 : s === "annulled" ? 1 : s === "forward" ? 0 : order.indexOf(s);
  return html`<div class="stepper">${STEPS.map(([k, l], i) => {
    const cls = (s === "annulled" && i === 1) || (s === "disputed" && i === 3) ? "bad" : i < idx || s === "settled" || s === "resolved" ? "done" : i === idx ? "cur" : "";
    return html`<div class="st ${cls}"><i/>${s === "disputed" && i === 3 ? "Спор" : s === "resolved" && i === 4 ? "Решено" : l}</div>`;
  })}</div>`;
}

function Route({ d, route }) {
  if (!route?.from || !route?.to) return null;
  const [a, b] = [route.from, route.to];
  const lat = [a[0], b[0]], lon = [a[1], b[1]];
  const box = { x0: Math.min(...lon) - .8, x1: Math.max(...lon) + .8, y0: Math.min(...lat) - .5, y1: Math.max(...lat) + .5 };
  const P = (la, lo) => [((lo - box.x0) / (box.x1 - box.x0)) * 100, (1 - (la - box.y0) / (box.y1 - box.y0)) * 100];
  const [ax, ay] = P(...a), [bx, by] = P(...b);
  const cur = d.gps ? P(...d.gps) : d.status === "in_transit" || ["signed", "paid"].includes(d.status) ? [ax, ay] : [bx, by];
  return html`<div class="route"><svg viewBox="0 0 100 100" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">
      <line x1=${ax} y1=${ay} x2=${bx} y2=${by} stroke="#2E3F60" stroke-width="0.8" stroke-dasharray="2 1.5" vector-effect="non-scaling-stroke"/>
      <line x1=${ax} y1=${ay} x2=${cur[0]} y2=${cur[1]} stroke="#F5B93D" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>
    <div style="position:absolute;left:${ax}%;top:${ay}%;transform:translate(-50%,-50%)" class="chip">${d.seller_info?.region?.split(" ")[0]}</div>
    <div style="position:absolute;left:${bx}%;top:${by}%;transform:translate(-50%,-50%)" class="chip bl">${d.buyer_info?.region?.split(" ")[0]}</div>
    ${d.status === "in_transit" && html`<div style="position:absolute;left:${cur[0]}%;top:${cur[1]}%;transform:translate(-50%,-50%);color:var(--agent)"><${Icon} n="truck" s=${26}/></div>`}
    <div class="tiny muted" style="position:absolute;left:10px;bottom:8px">${d.truck ? `${d.truck} · пломба ${d.seal} · ${d.carrier}` : "Машина ещё не назначена"}${d.gps ? ` · GPS ${d.gps[0]}, ${d.gps[1]}` : ""}</div>
  </div>`;
}

function ticketImage(r, deal) {
  const c = document.createElement("canvas"); c.width = 620; c.height = 820;
  const g = c.getContext("2d"); g.fillStyle = "#fbfaf6"; g.fillRect(0, 0, 620, 820);
  g.fillStyle = "#222"; g.font = "bold 30px monospace"; g.fillText("ВЕСОВОЙ ТАЛОН", 150, 70);
  g.font = "20px monospace";
  const lines = [`№ ${r.ticket_no}`, `Дата: ${new Date().toLocaleString("ru-RU")}`, r.scale, `Автомобиль: ${r.truck}`, `Груз: ${NAMES[deal.instrument]}`,
    "", `БРУТТО:  ${r.gross_t.toFixed(3)} т`, `ТАРА:    ${r.tare_t.toFixed(3)} т`, "", `НЕТТО:   ${r.net_t.toFixed(3)} т`, "", "Весовщик: ________", "М.П."];
  lines.forEach((l, i) => { g.font = l.startsWith("НЕТТО") ? "bold 34px monospace" : "22px monospace"; g.fillText(l, 50, 140 + i * 48); });
  g.strokeStyle = "#999"; g.setLineDash([6, 6]); g.strokeRect(25, 25, 570, 770);
  g.save(); g.translate(430, 700); g.rotate(-0.25); g.strokeStyle = "rgba(40,70,160,.55)"; g.setLineDash([]); g.lineWidth = 4;
  g.beginPath(); g.arc(0, 0, 70, 0, Math.PI * 2); g.stroke(); g.fillStyle = "rgba(40,70,160,.55)"; g.font = "bold 18px sans-serif"; g.fillText("ВЕСОВАЯ", -42, 6); g.restore();
  return c.toDataURL("image/jpeg", .9);
}

function Accept({ d, reload }) {
  const [img, setImg] = useState(null);
  const [read, setRead] = useState(null);
  const [busy, setBusy] = useState(false);
  const [w, setW] = useState("");
  const now = useNow();
  const scan = async (image) => {
    setImg(image); setRead(null); setBusy(true);
    try { const r = await api(`/api/deals/${d.id}/scan`, { body: { image } }); setRead(r); if (r.net_t) setW(String(r.net_t)); }
    catch (e) { toast("Не удалось распознать", e.message); } finally { setBusy(false); }
  };
  const file = e => { const f = e.target.files[0]; if (!f) return; const rd = new FileReader(); rd.onload = () => scan(rd.result); rd.readAsDataURL(f); };
  const demo = async () => { const r = await api(`/api/deals/${d.id}/scale`); scan(ticketImage(r, d)); };
  const submit = async () => {
    setBusy(true);
    try { const r = await api(`/api/deals/${d.id}/receive`, { body: { weight: +w, method: read ? "photo_ai" : "manual", image_hash: read?.image_hash, ticket_no: read?.ticket_no } });
      toast(r.status === "settled" ? "Товар принят" : "Расхождение — открыт спор", r.status === "settled" ? "Продавец получил оплату из сейфа" : "ИИ-арбитр анализирует доказательства"); reload(); }
    catch (e) { toast("Ошибка", e.message); } finally { setBusy(false); }
  };
  const diff = w ? +w - d.qty : 0;
  return html`<div class="card pad" style="border-color:rgba(245,185,61,.5)">
    <h3><${Icon} n="scale" s=${16}/> Приёмка товара · осталось <span class="mono agentc">${countdown(d.accept_due, now)}</span></h3>
    <p class="small" style="margin:0 0 10px">Сфотографируйте весовой талон — агент прочитает вес и сверит с договором (${nf(d.qty)} т, погружено ${nf(d.loaded_qty, 2)} т). Расхождение больше 0,5% автоматически откроет спор. По Правилам UzEx (ред. 01.06.2026) на замечания — 6 рабочих часов; агент напомнит.</p>
    <div class="row" style="flex-wrap:wrap">
      <label class="btn pri"><${Icon} n="camera"/> Сфотографировать талон<input type="file" accept="image/*" capture="environment" hidden onChange=${file}/></label>
      <button class="btn" onClick=${demo}>Взять талон с весов склада (демо)</button>
    </div>
    ${img && html`<div class="row" style="margin-top:12px;align-items:flex-start;gap:14px;flex-wrap:wrap">
      <img src=${img} style="width:150px;border-radius:8px;border:1px solid var(--line)" alt="Талон"/>
      <div style="flex:1;min-width:200px">${busy && !read ? html`<span class="spin"/> ИИ читает талон…` : read && html`
        <div class="small muted">Распознано ИИ (уверенность ${Math.round((read.confidence || 0) * 100)}%)</div>
        <dl class="kv"><dt>Нетто</dt><dd>${read.net_t ?? "—"} т</dd><dt>Талон</dt><dd>${read.ticket_no ?? "—"}</dd><dt>Машина</dt><dd>${read.truck ?? "—"}</dd></dl>`}</div></div>`}
    <div class="row" style="margin-top:12px">
      <input class="inp mono" style="width:140px" placeholder="Вес, т" value=${w} onInput=${e => setW(e.target.value.replace(",", "."))} inputmode="decimal"/>
      ${w && html`<span class="small ${Math.abs(diff) > d.qty * .005 ? "down" : "up"}">${Math.abs(diff) > d.qty * .005 ? `расхождение ${nf(diff, 2)} т` : "в пределах допуска"}</span>`}
      <span class="sp"/><button class="btn pri" disabled=${!w || busy} onClick=${submit}>Подтвердить приёмку</button>
    </div></div>`;
}

function Verdict({ dsp, d, reload }) {
  if (!dsp) return null;
  const dec = dsp.decision;
  if (!dec) return html`<div class="card pad"><h3><${Icon} n="gavel" s=${16}/> Спор</h3><span class="spin"/> ИИ-арбитр сверяет весы, пломбу, GPS и документы…</div>`;
  const accept = async () => { try { await api(`/api/disputes/${dsp.id}/accept`, { body: {} }); toast("Решение исполнено", "Деньги распределены"); reload(); } catch (e) { toast("Ошибка", e.message); } };
  const lbl = { "escrow→seller": "Сейф → продавцу", "escrow→buyer": "Сейф → вам (возврат)", "seller_deposit→buyer": "Задаток продавца → вам", "carrier→buyer": "Перевозчик → вам", "escrow_hold": "Удержано в сейфе" };
  return html`<div class="card pad" style="border-color:${dsp.status === "resolved" ? "var(--line)" : "rgba(242,85,90,.5)"}">
    <h3><${Icon} n="gavel" s=${16}/> Решение ИИ-арбитра ${dsp.status === "resolved" ? html`<span class="chip ok">исполнено</span>` : dsp.status === "needs_review" ? html`<span class="chip bad">нужна перевеска</span>` : html`<span class="chip ag">предложено</span>`}</h3>
    <div class="verdict">
      <div style="font-size:17px;font-weight:600;margin-bottom:8px">${dec.summary}</div>
      ${dec.findings.map(f => html`<div class="finding"><${Icon} n="check" s=${15}/><span>${f.fact}</span><span class="sp"/><code>${f.evidence}</code></div>`)}
    </div>
    <h3 style="margin-top:14px">Движение денег</h3>
    <table class="tbl"><tbody>${dec.moves.map(([k, a, m]) => html`<tr><td>${lbl[k] || k}<div class="tiny muted">${m}</div></td><td class="num">${sum(a)}</td></tr>`)}</tbody></table>
    ${dec.reasoning && html`<h3 style="margin-top:14px">Обоснование</h3><div class="small md" style="color:var(--text2)" dangerouslySetInnerHTML=${{ __html: md(dec.reasoning) }}/>`}
    ${dec.precedents?.length > 0 && html`<h3 style="margin-top:10px">Близкая судебная практика Узбекистана</h3>
      ${dec.precedents.map(p => html`<div class="small" style="padding:6px 0;border-bottom:1px solid var(--line)"><a href=${p.url} target="_blank" rel="noopener">Дело № ${p.case}</a> · ${p.court}<div class="muted tiny">${p.outcome}</div></div>`)}`}
    ${dsp.status === "proposed" && d.role === "buyer" && html`<div class="row" style="margin-top:14px"><button class="btn pri" onClick=${accept}><${Icon} n="check"/> Согласен с решением</button>
      <span class="small muted">Не согласны — Арбитражная комиссия биржи, затем экономический суд</span></div>`}
  </div>`;
}

function Load({ d, reload }) {
  const [qty, setQty] = useState(String(d.qty)); const [truck, setTruck] = useState(""); const [seal, setSeal] = useState("");
  const [busy, setBusy] = useState(false); const now = useNow();
  const go_ = async () => { setBusy(true); try { await api(`/api/deals/${d.id}/load`, { body: { qty: +qty, truck, seal } }); toast("Отгрузка подтверждена", "Покупатель видит машину на карте"); reload(); } catch (e) { toast("Ошибка", e.message); } finally { setBusy(false); } };
  return html`<div class="card pad" style="border-color:rgba(245,185,61,.5)">
    <h3><${Icon} n="truck" s=${16}/> Отгрузка · осталось <span class="mono agentc">${countdown(d.ship_due, now)}</span></h3>
    <p class="small" style="margin:0 0 10px">Покупатель оплатил: ${sum(d.amount)} лежат в сейфе биржи и придут вам после приёмки. Укажите вес с ваших весов, номер машины и пломбы — это станет частью цепочки доказательств.</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">
      <div class="field"><label>Вес погрузки, т</label><input class="inp mono" value=${qty} onInput=${e => setQty(e.target.value.replace(",", "."))} inputmode="decimal"/></div>
      <div class="field"><label>Госномер машины</label><input class="inp mono" placeholder="30 A777BC" value=${truck} onInput=${e => setTruck(e.target.value.toUpperCase())}/></div>
      <div class="field"><label>Номер пломбы</label><input class="inp mono" placeholder="UZX-123456" value=${seal} onInput=${e => setSeal(e.target.value.toUpperCase())}/></div>
    </div>
    <button class="btn pri" disabled=${busy || !truck || !seal} onClick=${go_}><${Icon} n="check"/> Подтвердить отгрузку</button>
    <p class="tiny muted" style="margin:8px 0 0">Без отгрузки в срок гарантийный задаток уйдёт покупателю (п.171 Правил UzEx), а покупатель вправе требовать неустойку 0,5% в день (ст.25 Закона №670-I).</p></div>`;
}

function ForwardInfo({ d }) {
  const now = useNow(); const f = d.flags.forward || {};
  const [spot, setSpot] = useState(null);
  usePoll(() => api("/api/market/" + d.instrument).then(x => setSpot(x.recommendation.current)), 8000, []);
  const diff = spot ? (spot - d.price) * d.qty : 0;
  return html`<div class="card pad" style="border-color:rgba(76,141,255,.5)"><h3><${Icon} n="lockp" s=${16}/> Цена зафиксирована до поставки</h3>
    <div class="row" style="flex-wrap:wrap;gap:18px"><div><div class="tiny muted">Ваша цена</div><b class="mono" style="font-size:20px">${nf(d.price)}</b></div>
      <div><div class="tiny muted">Рынок сейчас</div><b class="mono" style="font-size:20px">${spot ? nf(spot) : "…"}</b></div>
      <div><div class="tiny muted">${diff >= 0 ? "Щит экономит" : "Рынок ниже на"}</div><b class="mono ${diff >= 0 ? "up" : "down"}" style="font-size:20px">${sum(Math.abs(diff))}</b></div>
      <div><div class="tiny muted">До поставки</div><b class="mono agentc" style="font-size:20px">${countdown(f.delivery_at, now)}</b></div></div>
    <p class="tiny muted" style="margin:8px 0 0">Демо: одна неделя форварда = ${Math.round((f.delivery_at - d.created_at) / (f.weeks || 1))} c. В срок агент сам оплатит, проследит отгрузку и приёмку.</p></div>`;
}

function Legal({ d }) {
  const [st, setSt] = useState(null); const [busy, setBusy] = useState(false);
  useEffect(() => { api(`/api/deals/${d.id}/statutory`).then(setSt).catch(() => {}); }, [d.status]);
  if (!st || !st.sanctions.length) return null;
  const mk = async () => { setBusy(true); try { const r = await api(`/api/deals/${d.id}/claim`, { body: {} }); window.open("/doc/" + r.doc_id, "_blank"); toast("Претензия готова", "Подписана вашим ключом"); } catch (e) { toast("Ошибка", e.message); } finally { setBusy(false); } };
  return html`<div class="card pad"><h3><${Icon} n="law" s=${16}/> Что можно требовать по закону</h3>
    <table class="tbl"><tbody>${st.sanctions.map(x => html`<tr><td>${x.what}<div class="tiny muted">${x.norm} · ${x.rate} · платит ${x.who_pays}</div></td><td class="num">${sum(x.amount)}</td></tr>`)}</tbody></table>
    <p class="tiny muted">Санкции биржи (задатки) уже применены клирингом автоматически. Неустойку по Закону №670-I сторона вправе требовать дополнительно — сначала претензией, затем в экономическом суде.</p>
    <button class="btn" disabled=${busy} onClick=${mk}>${busy ? html`<span class="spin"/>` : html`<${Icon} n="doc"/>`} Составить претензию</button></div>`;
}

function Deal({ id }) {
  const s = useStore();
  const [x, setX] = useState(null);
  const load = () => api("/api/deals/" + id).then(setX);
  usePoll(load, 3000, [id, s.tick]);
  const now = useNow();
  if (!x) return html`<div class="empty"><span class="spin"/></div>`;
  const d = x.deal;
  return html`<div>
    <div class="row" style="flex-wrap:wrap"><button class="btn ghost sm" onClick=${() => location.hash = "#/deals"}><${Icon} n="back" s=${15}/> Сделки</button><span class="sp"/><${Status} s=${d.status}/></div>
    <div class="h1" style="margin-top:6px">${nf(d.qty)} т · ${d.name}</div>
    <p class="sub">${d.role === "seller" ? "Вы продаёте: " : ""}${d.seller_info?.name} → ${d.buyer_info?.name} · ${nf(d.price)} сум/т · ${sum(d.amount)}${d.pool_id ? " · общий лот" : ""}</p>
    <${Stepper} s=${d.status}/>
    <div class="dl-layout">
      <div class="grid">
        ${d.status === "delivered" && d.role === "buyer" && html`<${Accept} d=${d} reload=${load}/>`}
        ${d.status === "paid" && d.role === "seller" && html`<${Load} d=${d} reload=${load}/>`}
        ${d.status === "forward" && html`<${ForwardInfo} d=${d}/>`}
        ${d.status === "signed" && html`<div class="card pad"><h3>Оплата</h3><p class="small">Агент переводит оплату в сейф биржи автоматически. Осталось <b class="mono">${countdown(d.pay_due, now)}</b> — если на кошельке не хватит денег, сделка аннулируется и задаток уйдёт продавцу (п.170 Правил).</p></div>`}
        <${Verdict} dsp=${x.dispute} d=${d} reload=${load}/>
        ${["disputed", "resolved", "annulled"].includes(d.status) && html`<${Legal} d=${d}/>`}
        <div class="card pad"><h3><${Icon} n="truck" s=${16}/> Доставка</h3><${Route} d=${d} route=${x.route}/>
          <dl class="kv" style="margin-top:12px"><dt>По договору</dt><dd>${nf(d.qty)} т</dd><dt>Погружено (весы продавца)</dt><dd>${d.loaded_qty ? nf(d.loaded_qty, 2) + " т" : "—"}</dd>
          <dt>Принято (весы покупателя)</dt><dd>${d.delivered_qty ? nf(d.delivered_qty, 2) + " т" : "—"}</dd><dt>Задаток покупателя</dt><dd>${sum(d.deposit_buyer)}</dd><dt>Задаток продавца</dt><dd>${sum(d.deposit_seller)}</dd></dl></div>
      </div>
      <div class="grid">
        <div class="card pad"><h3><${Icon} n="doc" s=${16}/> Документы — созданы и подписаны автоматически</h3>
          ${x.documents.map(doc => html`<a class="doc" href=${"/doc/" + doc.id} target="_blank" rel="noopener"><div class="ic">${DOCK[doc.kind]}</div><div style="flex:1"><div style="color:var(--text)">${doc.title}</div><div class="tiny muted mono">SHA-256 ${doc.hash.slice(0, 20)}…</div></div><span class="chip ok tiny">подписан</span></a>`)}</div>
        <div class="card pad"><h3><${Icon} n="shield" s=${16}/> Цепочка доказательств ${x.chain.ok ? html`<span class="chip ok">целостна · ${x.chain.events}</span>` : html`<span class="chip bad">нарушена</span>`}</h3>
          <div class="chain">${x.events.filter(e => e.type !== "document").map(e => { const [l, c] = EV[e.type] || [e.type, ""]; const p = e.payload;
            const extra = e.type === "loaded" ? `${p.weighbridge_qty} т · пломба ${p.seal}` : e.type === "unloaded" ? `${p.weighbridge_qty} т · ${p.source === "photo_ai" ? "фото талона, ИИ" : p.source}` :
              e.type === "gps_anomaly" ? `остановка ${p.stop_minutes} мин` : e.type === "arrived" ? (p.seal_intact ? "пломба цела" : `пломба ${p.seal_seen} — не совпадает`) :
              e.type === "matched" ? `${p.qty} т × ${nf(p.price)}` : e.type === "paid" ? sum(p.amount) : "";
            return html`<div class="ev ${c}"><span class="dot"/><div><b>${l}</b> <span class="small muted">${extra}</span><div class="h">${time(e.ts)} · ${e.hash.slice(0, 24)}… ← ${e.prev_hash.slice(0, 10)}</div></div></div>`; })}</div>
          <p class="tiny muted" style="margin:6px 0 0">Каждое событие содержит хеш предыдущего. Изменить прошлое незаметно нельзя — на этих данных решаются споры.</p></div>
      </div>
    </div></div>`;
}
