import { html, useState, useEffect, useRef, api, set, setToken, refreshMe, store, nf, Icon, sum, tr, setLang, useStore } from "./lib.js";

const REGIONS = ["Toshkent shahri", "Toshkent viloyati", "Andijon viloyati", "Buxoro viloyati", "Fargʻona viloyati", "Jizzax viloyati",
  "Xorazm viloyati", "Namangan viloyati", "Navoiy viloyati", "Qashqadaryo viloyati", "Qoraqalpogʻiston Respublikasi",
  "Samarqand viloyati", "Sirdaryo viloyati", "Surxondaryo viloyati"];
const INTERESTS = [["cement", "Цемент"], ["rebar", "Арматура"], ["urea", "Удобрения (карбамид)"], ["wheat", "Пшеница"],
  ["sugar", "Сахар"], ["pp", "Полипропилен"], ["propane", "Сжиженный газ"], ["ai92", "Бензин А-92"]];

function Hero() {
  const pts = [
    ["Найти товар одной фразой.", "Напишите как в мессенджере, на любом языке. ИИ-брокер найдёт товар на бирже, цену и надёжных продавцов."],
    ["Знает рынок.", "Ваша доля рынка, спрос по регионам, куда расти и когда покупать — по реальным сделкам биржи."],
    ["Больше, чем подача заявки.", "Готовит поручение без ошибок, подаёт через брокерскую контору, следит за оплатой и отгрузкой."],
    ["Гарантия биржи.", "Деньги блокируются на клиринговом счёте, продавец вносит задаток, документы создаются сами."],
  ];
  const st = useStore();
  return html`<div class="ob-hero">
    <div class="row"><div class="yr">UZEX · ИИ-брокер</div><span class="sp"/>
      <div class="lang">${["ru", "uz"].map(l => html`<button class=${st.lang === l ? "on" : ""} onClick=${() => setLang(l)}>${l.toUpperCase()}</button>`)}</div></div>
    <h1>${tr("ИИ-брокер биржи: найдёт рынок, покажет спрос и проведёт сделку")}</h1>
    <p>${tr("Данные UZEX за годы торгов превращаются в подсказки для вашего бизнеса. Сделка — с гарантией биржи.")}</p>
    <div class="row" style="flex-wrap:wrap;gap:8px;margin:4px 0 18px">
      <button class="btn pri" onClick=${() => { location.hash = "#/demo"; }}><${Icon} n="spark" s=${16}/> ${tr("Демо за 2 минуты")}</button>
      <button class="btn ghost" onClick=${() => { location.hash = "#/find"; }}>${tr("Найти товар")}</button>
      <button class="btn ghost" onClick=${() => { location.hash = "#/markets"; }}>${tr("Смотреть рынки")}</button>
</div>
    <div class="ob-points">${pts.map(([b, s]) => html`<div><${Icon} n="check" s=${20}/><span><b>${tr(b)}</b> ${tr(s)}</span></div>`)}</div>
    <div class="ob-proof"><span><b>500 000</b> ${tr("сделок биржи")}</span><span><b>41</b> ${tr("товар с аналитикой")}</span><span><b>1 461</b> ${tr("реальных котировок UZEX")}</span></div>
  </div>`;
}

export function Onboarding({ onDone }) {
  const me = store.me;
  const initial = !store.token ? 0 : !me?.verified ? 2 : !me?.status ? 3 : !me?.agent ? 4 : 5;
  const [step, setStep] = useState(initial || 0);
  useEffect(() => { if (initial < 5) set({ onboarding: true }); }, []);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async fn => { setErr(""); setBusy(true); try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  const steps = [Welcome, Phone, MyId, Status, Agent, TopUp, Done];
  const S = steps[step];
  return html`<div class="ob"><${Hero}/>
    <div class="ob-form">
      ${step > 0 && step < 6 && html`<div class="dots">${[1, 2, 3, 4, 5].map(i => html`<i class=${i <= step ? "on" : ""}/>`)}</div>`}
      <${S} next=${() => setStep(step + 1)} run=${run} busy=${busy} err=${err} onDone=${onDone}/>
    </div></div>`;
}

function Welcome({ next }) {
  return html`<div>
    <div class="h1">${tr("Подключите ИИ-брокера")}</div>
    <p class="sub">${tr("2 минуты: телефон и ID-карта. Договор с брокерской конторой оформляется онлайн, сделки идут через неё.")}</p>
    <button class="btn pri" style="width:100%;padding:13px" onClick=${next}>${tr("Начать")} <${Icon} n="arrow"/></button>
    <p class="hint" style="margin-top:14px">${tr("Это рабочий прототип: государственные сервисы (SMS, MyID, оплата картой) имитируются, но весь процесс — торги, клиринг, подписи, документы, споры — работает по-настоящему.")}</p>
  </div>`;
}

function Phone({ next, run, busy, err }) {
  const [phone, setPhone] = useState("+998 ");
  const [ok, setOk] = useState(false);
  const [sms, setSms] = useState(null);
  const [code, setCode] = useState("");
  return html`<div>
    <div class="h1">${tr("Номер телефона")}</div><p class="sub">${tr("Это ваш логин. Пароль не нужен.")}</p>
    ${!sms ? html`
      <div class="field"><input class="inp" value=${phone} onInput=${e => setPhone(e.target.value)} inputmode="tel" autocomplete="tel" placeholder="+998 90 123 45 67"/></div>
      <label class="consent"><input type="checkbox" checked=${ok} onChange=${e => setOk(e.target.checked)}/>
        <span>${tr("Согласен на обработку персональных данных (Закон РУз «О персональных данных», ЗРУ-547) и с правилами платформы")}</span></label>
      ${err && html`<div class="err">${err}</div>`}
      <button class="btn pri" style="width:100%" disabled=${busy || !ok} onClick=${() => run(async () => { const r = await api("/api/auth/start", { body: { phone } }); setSms(r.sandbox_sms || "отправлен по SMS"); })}>${tr("Получить код")}</button>`
    : html`
      <div class="sms">SMS (песочница): ваш код <b>${sms}</b></div>
      <div class="field"><input class="inp big" maxlength="6" value=${code} onInput=${e => setCode(e.target.value.replace(/\D/g, ""))} inputmode="numeric" autocomplete="one-time-code" placeholder="••••••"/></div>
      ${err && html`<div class="err">${err}</div>`}
      <button class="btn pri" style="width:100%" disabled=${busy || code.length !== 6} onClick=${() => run(async () => {
        const r = await api("/api/auth/verify", { body: { phone, code, lang: store.lang } }); setToken(r.token); set({ me: r.user });
        next(); next && 0; })}>${tr("Войти")}</button>`}
  </div>`;
}

function MyId({ next, run, busy, err }) {
  const [name, setName] = useState(store.me?.name || "");
  const [pinfl, setPinfl] = useState("");
  const [shot, setShot] = useState(null);
  const [camOn, setCamOn] = useState(false);
  const vid = useRef(null), stream = useRef(null);
  const startCam = async () => {
    try { stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } }); setCamOn(true);
      setTimeout(() => { if (vid.current) vid.current.srcObject = stream.current; }, 50);
    } catch (e) { alert("Камера недоступна — загрузите фото файлом"); }
  };
  const snap = () => {
    const v = vid.current, c = document.createElement("canvas"); c.width = 480; c.height = 360;
    c.getContext("2d").drawImage(v, 0, 0, 480, 360); setShot(c.toDataURL("image/jpeg", .8));
    stream.current?.getTracks().forEach(t => t.stop()); setCamOn(false);
  };
  const file = e => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => setShot(r.result); r.readAsDataURL(f); };
  useEffect(() => () => stream.current?.getTracks().forEach(t => t.stop()), []);
  return html`<div>
    <div class="h1">${tr("Проверка личности MyID")}</div><p class="sub">Селфи и ПИНФЛ вместо визита к брокеру. Один ПИНФЛ — один аккаунт: так перекупщики не скупают товар на подставных лиц.</p>
    <div class="field"><label>Имя и фамилия (как в паспорте)</label><input class="inp" value=${name} onInput=${e => setName(e.target.value)} autocomplete="name"/></div>
    <div class="field"><label>ПИНФЛ — 14 цифр на обороте ID-карты</label><input class="inp mono" maxlength="14" value=${pinfl} onInput=${e => setPinfl(e.target.value.replace(/\D/g, ""))} inputmode="numeric"/></div>
    <div class="field"><label>Селфи для проверки живости</label>
      ${shot ? html`<img class="cam" src=${shot} alt="Селфи"/>` : camOn ? html`<video class="cam" ref=${vid} autoplay playsinline muted/>` : html`<div class="cam" style="display:grid;place-items:center;color:var(--muted)"><${Icon} n="camera" s=${42}/></div>`}
      <div class="row" style="margin-top:8px">
        ${camOn ? html`<button class="btn pri" onClick=${snap}>Сделать снимок</button>` : html`<button class="btn" onClick=${startCam}><${Icon} n="camera"/> ${shot ? "Переснять" : "Включить камеру"}</button>`}
        <label class="btn ghost">или файл<input type="file" accept="image/*" capture="user" hidden onChange=${file}/></label>
      </div></div>
    ${err && html`<div class="err">${err}</div>`}
    <button class="btn pri" style="width:100%" disabled=${busy || !shot || pinfl.length !== 14 || name.length < 3}
      onClick=${() => run(async () => { await api("/api/kyc/myid", { body: { name, pinfl, selfie: shot } }); await refreshMe(); next(); })}>
      ${busy ? html`<span class="spin"/> …` : tr("Пройти проверку")}</button>
  </div>`;
}

function Status({ next, run, busy, err }) {
  const [st, setSt] = useState("self_employed");
  const [region, setRegion] = useState("Toshkent shahri");
  const [inn, setInn] = useState(""); const [company, setCompany] = useState("");
  const [res, setRes] = useState(null);
  const opts = [
    ["individual", "Физическое лицо", "Покупки до 50 млн сум в месяц, без дефицитных товаров (топливо, газ)"],
    ["self_employed", "Самозанятый — оформим за 1 минуту", "Фермер, мастер, небольшой цех. До 1 млрд сум в год"],
    ["ip", "Индивидуальный предприниматель", "Нужен ИНН. Без лимитов"],
    ["company", "Компания", "Нужен ИНН. Без лимитов"],
  ];
  return html`<div>
    <div class="h1">${tr("Кто вы на бирже?")}</div><p class="sub">В 2035 году на биржу может прийти любой человек. Статус задаёт лимиты, а не право на вход.</p>
    <div class="choice">${opts.map(([k, b, s]) => html`<button class=${st === k ? "on" : ""} onClick=${() => setSt(k)}><span><b>${b}</b><span>${s}</span></span></button>`)}</div>
    ${(st === "ip" || st === "company") && html`<div class="field"><label>ИНН (9 цифр)</label><input class="inp mono" maxlength="9" value=${inn} onInput=${e => setInn(e.target.value.replace(/\D/g, ""))}/></div>
      <div class="field"><label>Название</label><input class="inp" value=${company} onInput=${e => setCompany(e.target.value)}/></div>`}
    <div class="field"><label>Регион (куда доставлять)</label><select class="inp" value=${region} onChange=${e => setRegion(e.target.value)}>${REGIONS.map(r => html`<option>${r}</option>`)}</select></div>
    ${res?.self_employed_reg && html`<div class="sms">Самозанятость оформлена (песочница soliq.uz): <b>${res.self_employed_reg}</b></div>`}
    ${err && html`<div class="err">${err}</div>`}
    <button class="btn pri" style="width:100%" disabled=${busy} onClick=${() => run(async () => {
      const r = await api("/api/profile/status", { body: { status: st, inn, company, region } }); setRes(r); await refreshMe();
      setTimeout(next, r.self_employed_reg ? 1100 : 0); })}>${tr("Продолжить")}</button>
  </div>`;
}

function Agent({ next, run, busy, err }) {
  const [name, setName] = useState("Baraka");
  const [interests, setInterests] = useState(["cement"]);
  const [business, setBusiness] = useState("");
  const [risk, setRisk] = useState("balanced");
  const [pin, setPin] = useState("");
  const tog = k => setInterests(interests.includes(k) ? interests.filter(x => x !== k) : [...interests, k]);
  return html`<div>
    <div class="h1">${tr("Ваш личный агент")}</div><p class="sub">Агент сразу знает правила биржи, реальные цены UZEX и историю 500 000 сделок. О вас он будет узнавать постепенно — из разговоров и решений.</p>
    <div class="field"><label>Как зовут агента</label><input class="inp" value=${name} maxlength="24" onInput=${e => setName(e.target.value)}/></div>
    <div class="field"><label>Чем вы занимаетесь</label><input class="inp" value=${business} placeholder="Например: строю дома, фермер, пекарня" onInput=${e => setBusiness(e.target.value)}/></div>
    <label class="small muted">Что вам обычно нужно</label>
    <div class="chips" style="margin-top:6px">${INTERESTS.map(([k, l]) => html`<button class=${interests.includes(k) ? "on" : ""} onClick=${() => tog(k)}>${l}</button>`)}</div>
    <label class="small muted">Как агенту торговаться</label>
    <div class="chips" style="margin-top:6px">${[["cautious", "Осторожно — только по выгодной цене"], ["balanced", "Сбалансированно"], ["fast", "Быстро — главное купить"]]
      .map(([k, l]) => html`<button class=${risk === k ? "on" : ""} onClick=${() => setRisk(k)}>${l}</button>`)}</div>
    <div class="field"><label>PIN-код (4–6 цифр) — им вы подписываете поручения агенту</label><input class="inp big" type="password" maxlength="6" value=${pin} onInput=${e => setPin(e.target.value.replace(/\D/g, ""))} inputmode="numeric"/></div>
    ${err && html`<div class="err">${err}</div>`}
    <button class="btn pri" style="width:100%" disabled=${busy || pin.length < 4 || !name} onClick=${() => run(async () => {
      await api("/api/agent/create", { body: { name, interests, business, risk, pin, lang: store.lang } }); await refreshMe(); next(); })}>${tr("Создать агента")}</button>
  </div>`;
}

export function TopUpForm({ onOk, compact }) {
  const [amount, setAmount] = useState(50_000_000);
  const [card, setCard] = useState("8600 1234 5678 9012");
  const [prov, setProv] = useState("sandbox");
  const [pay, setPay] = useState(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const run = async fn => { setErr(""); setBusy(true); try { await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  return html`<div>
    ${!pay ? html`
      <div class="chips">${[10e6, 50e6, 200e6, 1e9].map(a => html`<button class=${amount === a ? "on" : ""} onClick=${() => setAmount(a)}>${nf(a)}</button>`)}</div>
      <div class="field"><label>Сумма, сум</label><input class="inp mono" value=${nf(amount)} onInput=${e => setAmount(+e.target.value.replace(/\D/g, "") || 0)} inputmode="numeric"/></div>
      <div class="chips">${[["payme", "Payme"], ["click", "Click"], ["sandbox", "Песочница"]].map(([k, l]) => html`<button class=${prov === k ? "on" : ""} onClick=${() => setProv(k)}>${l}</button>`)}</div>
      ${prov !== "sandbox" && html`<p class="hint" style="margin:-4px 0 10px">Откроется страница оплаты ${prov === "payme" ? "Payme" : "Click"}. Деньги поступят на ваш счёт в клиринге после подтверждения платёжной системой.</p>`}
      <div class="field" hidden=${prov !== "sandbox"}><label>Карта Uzcard / Humo (песочница)</label><input class="inp mono" value=${card} onInput=${e => setCard(e.target.value)} inputmode="numeric" autocomplete="cc-number"/></div>
      ${err && html`<div class="err">${err}</div>`}
      <button class="btn pri" style="width:100%" disabled=${busy} onClick=${() => run(async () => { const r = await api("/api/wallet/topup/start", { body: { amount, card, provider: prov } });
        if (r.redirect) { location.href = r.redirect; return; }
        if (prov !== "sandbox") setErr("Касса " + prov + " ещё не подключена на этом сервере — используйте песочницу");
        setPay(r); })}>Пополнить ${sum(amount)}</button>`
    : html`
      <div class="sms">SMS от банка (песочница): код <b>${pay.sandbox_sms}</b></div>
      <div class="field"><input class="inp big" maxlength="6" value=${code} onInput=${e => setCode(e.target.value.replace(/\D/g, ""))} inputmode="numeric" autocomplete="one-time-code"/></div>
      ${err && html`<div class="err">${err}</div>`}
      <button class="btn pri" style="width:100%" disabled=${busy || code.length !== 6} onClick=${() => run(async () => {
        await api("/api/wallet/topup/confirm", { body: { payment_id: pay.payment_id, code } }); await refreshMe(); onOk && onOk(); })}>Подтвердить оплату</button>`}
  </div>`;
}

function TopUp({ next }) {
  return html`<div>
    <div class="h1">${tr("Пополните кошелёк")}</div><p class="sub">Деньги лежат на вашем счёте в клиринге биржи. Агент блокирует задаток только под конкретную заявку.</p>
    <${TopUpForm} onOk=${next}/>
    <button class="btn ghost" style="width:100%;margin-top:8px" onClick=${next}>${tr("Позже")}</button>
  </div>`;
}

function Done({ onDone }) {
  useEffect(() => { try { Notification.requestPermission(); } catch (e) {} }, []);
  return html`<div>
    <div class="h1">Агент ${store.me?.agent?.name} готов</div>
    <p class="sub">Скажите ему, что нужно — например: «Мне нужно 30 тонн цемента в Наманган до конца недели». Он покажет цену, прогноз, ближайшие торги и подготовит поручение.</p>
    <button class="btn pri" style="width:100%;padding:13px" onClick=${onDone}>Перейти к агенту <${Icon} n="arrow"/></button>
  </div>`;
}
