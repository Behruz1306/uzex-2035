import { html, useState, useEffect, useRef, api, store, useStore, nf, sum, md, Icon, refreshMe, t, toast, go, Status, Modal, dt, usePoll, short, set } from "./lib.js";

const NAMES = { cement: "Цемент", propane: "Сжиженный газ", ai92: "Бензин А-92", pp: "Полипропилен", urea: "Карбамид", wheat: "Пшеница", sugar: "Сахар", rebar: "Арматура" };
const TOOL_LABEL = { market: "смотрю цены", recommend: "считаю прогноз", explain_price: "разбираю цену", calendar: "смотрю расписание торгов",
  propose_mandate: "готовлю поручение", my_mandates: "проверяю поручения", my_deals: "смотрю сделки", wallet: "проверяю кошелёк",
  remember: "запоминаю", set_alert: "оформляю подписку", seasonality: "смотрю сезонность", price_lock_quote: "считаю фиксацию цены", registry_query: "ищу в реестре 500 000 сделок", legal_help: "смотрю нормы и суды", open_dispute: "открываю спор", cancel_mandate: "отменяю" };

export function MandateCard({ c, onDone }) {
  const [pin, setPin] = useState(""); const [qty, setQty] = useState(c.qty); const [lim, setLim] = useState(c.limit_price);
  const [st, setSt] = useState(c.confirmed ? "ok" : "draft"); const [err, setErr] = useState("");
  const confirm = async () => {
    setErr("");
    try { await api(`/api/mandates/${c.mandate_id}/confirm`, { body: { pin, qty, limit_price: lim } }); setSt("ok"); refreshMe(); onDone && onDone(); }
    catch (e) { setErr(e.message); }
  };
  const strat = { smart: c.side === "sell" ? "Торговаться: держать цену выше рынка до срока" : "Торговаться: ждать выгодную цену до срока",
    now: c.side === "sell" ? "Продать на ближайшей сессии" : "Купить на ближайшей сессии", alert: "Только уведомлять" }[c.strategy];
  return html`<div class="mcard">
    <h4><${Icon} n=${c.side === "sell" ? "sell" : "buy"} s=${16}/> ${c.side === "sell" ? "Поручение продать" : "Поручение купить"} ${st === "ok" ? html`<span class="chip ok">подписано</span>` : html`<span class="chip ag">ждёт подписи</span>`}</h4>
    <dl class="kv">
      <dt>Товар</dt><dd style="font-family:var(--sans)">${c.name}</dd>
      <dt>Объём</dt><dd>${st === "ok" ? `${nf(qty)} т` : html`<input class="inp mono" style="width:90px;padding:4px 8px;text-align:right" value=${qty} onInput=${e => setQty(+e.target.value.replace(/\D/g, "") || 0)}/> т`}</dd>
      <dt>${c.side === "sell" ? "Цена не ниже" : "Цена не выше"}</dt><dd>${st === "ok" ? `${nf(lim)} сум/т` : html`<input class="inp mono" style="width:130px;padding:4px 8px;text-align:right" value=${nf(lim)} onInput=${e => setLim(+e.target.value.replace(/\D/g, "") || 0)}/>`}</dd>
      <dt>${c.side === "sell" ? "Минимум выручки" : "Максимум"}</dt><dd>${sum(qty * lim)}</dd>
      <dt>${c.side === "sell" ? "Гарантийный задаток" : "Задаток (блокируется)"}</dt><dd>~${sum(Math.round(c.deposit_estimate * (qty * lim) / (c.qty * c.limit_price)))}</dd>
      <dt>Стратегия</dt><dd style="font-family:var(--sans)">${strat}</dd>
      <dt>Срок</dt><dd>${c.deadline_days} дн.</dd>
    </dl>
    ${c.side !== "sell" && qty < c.min_lot && html`<p class="hint" style="margin:8px 0 0">Объём меньше лота (${c.min_lot} т) — агент объединит вас с другими покупателями в общий лот.</p>`}
    ${st !== "ok" && html`<div class="row" style="margin-top:12px">
      <input class="inp mono" type="password" maxlength="6" placeholder="PIN" style="width:110px;text-align:center;letter-spacing:.3em" value=${pin} onInput=${e => setPin(e.target.value.replace(/\D/g, ""))} inputmode="numeric"/>
      <button class="btn pri" disabled=${pin.length < 4} onClick=${confirm}><${Icon} n="check"/> Подписать поручение</button></div>`}
    ${err && html`<div class="err">${err}</div>`}
    ${st === "ok" && html`<p class="hint" style="margin:10px 0 0">Подписано вашим ключом Ed25519. Агент действует только в этих границах.</p>`}
  </div>`;
}

export function ForwardCard({ c }) {
  const [pin, setPin] = useState(""); const [err, setErr] = useState(""); const [did, setDid] = useState(null);
  const lock = async () => { setErr(""); try { const r = await api("/api/forward/create", { body: { instrument: c.instrument, qty: c.qty, weeks: c.weeks, pin } }); setDid(r.deal_id); refreshMe(); } catch (e) { setErr(e.message); } };
  return html`<div class="mcard"><h4><${Icon} n="lockp" s=${16}/> Ценовой щит ${did ? html`<span class="chip ok">цена зафиксирована</span>` : html`<span class="chip ag">котировка</span>`}</h4>
    <dl class="kv"><dt>Товар</dt><dd style="font-family:var(--sans)">${c.name}</dd><dt>Объём</dt><dd>${nf(c.qty)} т</dd>
      <dt>Цена фиксации</dt><dd><b>${nf(c.price)}</b> сум/т</dd><dt>Поставка</dt><dd>через ${c.weeks} нед. (${c.delivery_week})</dd>
      <dt>Коридор прогноза</dt><dd>${nf(c.low)}–${nf(c.high)}</dd><dt>Задаток 15%</dt><dd>${sum(c.deposit)}</dd></dl>
    <p class="hint" style="margin:8px 0 0">${c.explain}</p>
    ${did ? html`<a class="btn sm" style="margin-top:10px" href=${"#/deals/" + did}>Открыть сделку</a>` : html`<div class="row" style="margin-top:12px">
      <input class="inp mono" type="password" maxlength="6" placeholder="PIN" style="width:110px;text-align:center" value=${pin} onInput=${e => setPin(e.target.value.replace(/\D/g, ""))} inputmode="numeric"/>
      <button class="btn pri" disabled=${pin.length < 4} onClick=${lock}><${Icon} n="check"/> Зафиксировать</button></div>`}
    ${err && html`<div class="err">${err}</div>`}</div>`;
}

const RecCard = ({ r }) => html`<div class="reccard">
  <b class=${r.action === "wait" ? "agentc" : "up"}>${r.action === "wait" ? "Совет: подождать" : r.action === "sell_now" ? "Совет: продавать" : "Совет: покупать сейчас"}</b>
  · ${NAMES[r.instrument]} · сейчас ${nf(r.current)} сум/т → прогноз ${nf(r.target_price)} (${r.expected_change_pct > 0 ? "+" : ""}${r.expected_change_pct}%)
  <div class="muted tiny">Уверенность: ${r.confidence} · ошибка модели на истории ${r.mape}% · решение за вами</div></div>`;

function Message({ m }) {
  if (m.role === "user") return html`<div class="m me">${m.content}</div>`;
  return html`<div class="m ai"><div class="av">${(store.me?.agent?.name || "A")[0]}</div><div style="min-width:0">
    ${m.steps?.length > 0 && html`<div class="steps">${m.steps.map(s => html`<span class="chip">${s.done ? html`<${Icon} n="check" s=${13}/>` : html`<span class="spin" style="width:11px;height:11px"/>`} ${TOOL_LABEL[s.tool] || s.tool}</span>`)}</div>`}
    ${(m.content || !m.steps?.length) && html`<div class="bubble md" dangerouslySetInnerHTML=${{ __html: m.content ? md(m.content) : '<span class="spin"></span>' }}/>`}
    ${(m.recs || []).map(r => html`<${RecCard} r=${r}/>`)}
    ${(m.cards || []).map(c => c.forward_card ? html`<${ForwardCard} c=${c}/>` : html`<${MandateCard} c=${c}/>`)}
  </div></div>`;
}

export function AgentScreen() {
  const s = useStore();
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(false);
  const box = useRef(null), recog = useRef(null);
  useEffect(() => { api("/api/chat/history").then(d => {
    const name = s.me?.agent?.name;
    setMsgs(d.messages.length ? d.messages : [{ role: "assistant", content: `Салом! Я **${name}**, ваш агент на бирже. Скажите, что нужно купить, к какому сроку и до какой цены — я посмотрю рынок, прогноз и ближайшие торги и подготовлю поручение. Можно голосом, по-узбекски или по-русски.` }]);
  }); }, []);
  useEffect(() => { box.current && (box.current.scrollTop = box.current.scrollHeight); }, [msgs]);
  useEffect(() => { if (store.pendingAsk) { const q = store.pendingAsk; set({ pendingAsk: null }); setTimeout(() => send(q), 400); } }, []);

  const send = async (q) => {
    q = (q ?? text).trim(); if (!q || busy) return;
    setText(""); setBusy(true);
    const ai = { role: "assistant", content: "", steps: [], cards: [], recs: [] };
    setMsgs(m => [...m, { role: "user", content: q }, ai]);
    const upd = () => setMsgs(m => [...m.slice(0, -1), { ...ai }]);
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + store.token }, body: JSON.stringify({ message: q, lang: store.lang }) });
      if (!r.ok) throw new Error((await r.json()).detail || "Ошибка");
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
      for (;;) {
        const { value, done } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let k;
        while ((k = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, k); buf = buf.slice(k + 2);
          if (!line.startsWith("data: ")) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "text") ai.content += ev.text;
          else if (ev.type === "reset") ai.content = "";
          else if (ev.type === "step") { ai.steps.forEach(x => x.done = true); ai.steps.push({ tool: ev.tool }); }
          else if (ev.type === "card") ai.cards.push(ev.card);
          else if (ev.type === "recommendation") ai.recs.push(ev.data);
          else if (ev.type === "done") { ai.content = ev.text || ai.content; ai.steps.forEach(x => x.done = true); }
          else if (ev.type === "error") throw new Error(ev.message);
          upd();
        }
      }
    } catch (e) { ai.content = "⚠️ " + e.message; upd(); }
    finally { setBusy(false); refreshMe(); }
  };

  const voice = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { toast("Голос недоступен в этом браузере", "Откройте в Chrome или наберите текстом"); return; }
    if (rec) { recog.current?.stop(); return; }
    const r = new SR(); recog.current = r;
    r.lang = store.lang === "uz" ? "uz-UZ" : "ru-RU"; r.interimResults = true; r.continuous = false;
    let final = "";
    r.onresult = e => { let txt = ""; for (const x of e.results) txt += x[0].transcript; final = txt; setText(txt); };
    r.onend = () => { setRec(false); if (final.trim()) send(final); };
    r.onerror = () => setRec(false);
    setRec(true); r.start();
  };

  const quick = store.lang === "uz"
    ? ["Menga 30 tonna sement kerak, Namanganga, hafta oxirigacha", "Karbamid hozir olsam bo‘ladimi yoki kutaymi?", "Yaqin savdolar qachon?", "Bitimim qayerda?"]
    : ["Нужно 30 тонн цемента в Наманган до конца недели", "Карбамид сейчас брать или подождать?", "Когда ближайшие торги по газу?", "Почему цена цемента такая?", "Что будет, если продавец не отгрузит?"];

  return html`<div class="ag-layout">
    <div class="card chat">
      <div class="msgs" ref=${box}>${msgs.map(m => html`<${Message} m=${m}/>`)}</div>
      ${msgs.length < 3 && html`<div class="quick">${quick.map(q => html`<button onClick=${() => send(q)}>${q}</button>`)}</div>`}
      <div class="composer">
        <button class="mic ${rec ? "on" : ""}" onClick=${voice} title="Сказать голосом" aria-label="Голос"><${Icon} n="mic"/></button>
        <textarea rows="1" value=${text} placeholder=${t("ask")} onInput=${e => { setText(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px"; }}
          onKeyDown=${e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}/>
        <button class="send" disabled=${busy} onClick=${() => send()} aria-label="Отправить">${busy ? html`<span class="spin"/>` : html`<${Icon} n="send"/>`}</button>
      </div>
    </div>
    <div class="ag-side grid"><${Mandates}/><${Feed}/></div>
  </div>`;
}

export function Mandates() {
  const s = useStore();
  const [list, setList] = useState([]);
  usePoll(() => api("/api/mandates").then(d => setList(d.mandates)).catch(() => {}), 5000, [s.tick]);
  const cancel = async id => { await api(`/api/mandates/${id}/cancel`, { body: {} }); setList(list.map(m => m.id === id ? { ...m, status: "cancelled" } : m)); };
  const active = list.filter(m => m.status === "active"), rest = list.filter(m => m.status !== "active").slice(0, 4);
  return html`<div class="card pad"><h3>Поручения агенту</h3>
    ${!list.length && html`<p class="muted small">Пока нет. Скажите агенту, что нужно, — он подготовит поручение.</p>`}
    ${[...active, ...rest].map(m => html`<div class="mand">
      <div class="row"><b style="font-size:14px">${m.side === "sell" ? "Продажа · " : ""}${NAMES[m.instrument]}</b><span class="sp"/><${Status} s=${m.status}/></div>
      <div class="bar"><i style="width:${Math.min(100, 100 * m.filled / m.qty)}%"/></div>
      <div class="row small muted"><span>${nf(m.filled)} / ${nf(m.qty)} т · до ${nf(m.limit_price)} сум/т</span><span class="sp"/>
        ${m.filled > 0 && html`<span class="mono">ср. ${nf(m.spent / m.filled)}</span>`}
        ${m.status === "active" && html`<button class="btn sm ghost" onClick=${() => cancel(m.id)}>Отменить</button>`}</div>
    </div>`)}
  </div>`;
}

function Feed() {
  const s = useStore();
  const [items, setItems] = useState([]);
  usePoll(() => api("/api/notifications").then(d => setItems(d.notifications)).catch(() => {}), 8000, [s.tick]);
  return html`<div class="card pad"><h3>Что делает агент</h3><div class="feed">
    ${!items.length && html`<p class="muted small">Здесь появятся действия агента: анонсы торгов, заявки, сделки, отгрузки.</p>`}
    ${items.map(n => html`<div class="fe" style="cursor:${n.link ? "pointer" : "default"}" onClick=${() => go(n.link)}><b>${n.title}</b>${n.body}<div class="t">${dt(n.ts)}</div></div>`)}
  </div></div>`;
}
