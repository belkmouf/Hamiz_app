/* Hamiz Pulse app. Data comes from the Pulse API. Strings live in /i18n.js. Default language is French. */
(function(){
"use strict";
const C=window.PulseCalc;
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const store={get(k,f){try{const v=localStorage.getItem("hp."+k);return v==null?f:JSON.parse(v)}catch(e){return f}},set(k,v){try{localStorage.setItem("hp."+k,JSON.stringify(v))}catch(e){}}};
function lang(){const v=store.get("lang","fr");return v==="ar"||v==="en"||v==="fr"?v:"fr"}
function locale(){return lang()==="ar"?"ar-DZ-u-nu-latn":lang()==="en"?"en-US":"fr-DZ"}
function t(key,vars){
  const packs=window.PULSE_I18N||{}, pack=packs[lang()]||{}, en=packs.en||{};
  let s=pack[key]!=null?pack[key]:en[key]!=null?en[key]:key;
  if(vars)Object.keys(vars).forEach(k=>{s=s.split("{"+k+"}").join(String(vars[k]))});
  return s;
}
function applyLang(){
  const l=lang();
  document.documentElement.lang=l==="ar"?"ar":l;
  document.documentElement.dir=l==="ar"?"rtl":"ltr";
  document.title=t("app.title");
}
function fmt(n,d=0){return n==null||!isFinite(+n)?t("num.na"):Number(n).toLocaleString(locale(),{maximumFractionDigits:d,minimumFractionDigits:d})}
function da(n){
  if(n==null||!isFinite(+n))return t("num.na");
  const a=Math.abs(n);let num=n,suf="";
  if(a>=1e6){num=n/1e6;suf=" "+t("num.million")}
  else if(a>=1e4){num=n/1e3;suf=" "+t("num.thousand")}
  const digits=a>=1e6?(a>=1e7?1:2):0;
  return Number(num).toLocaleString(locale(),{maximumFractionDigits:digits,minimumFractionDigits:digits})+suf+" "+t("currency.dzd");
}
function pct(n,d=1){return n==null||!isFinite(+n)?t("num.na"):Number(n).toLocaleString(locale(),{style:"percent",minimumFractionDigits:d,maximumFractionDigits:d})}
function usd(n,d=2){return n==null||!isFinite(+n)?t("num.na"):"$"+fmt(n,d)}
function formatWhen(iso){
  if(!iso)return "";
  const d=new Date(iso);
  if(isNaN(d.getTime()))return String(iso);
  return new Intl.DateTimeFormat(locale(),{timeZone:"Africa/Algiers",dateStyle:"medium",timeStyle:"short"}).format(d);
}

const TABS={sales:[["overview","tab.overview"],["trend","tab.trend"],["sellers","tab.sellers"],["products","tab.products"],["channels","tab.channels"],["orders","tab.orders"]],
            ads:[["budget","tab.budget"],["plan","tab.plan"],["review","tab.review"]]};
const STAGES=["pending","confirmed","delivered","returned","cancelled"];
const STAGE_PILL={pending:"p-idle",confirmed:"p-info",delivered:"p-good",returned:"p-warn",cancelled:"p-bad"};
const DECISION_PILL={promote:"p-good",kill:"p-bad",wait:"p-idle",fix:"p-info"};

const S={section:store.get("section","sales"),tab:store.get("tab",{sales:"overview",ads:"budget"}),
  data:{summary:null,sellers:null,products:null,orders:null},sync:null,pulse:null,me:null,net:"wait",
  period:store.get("period","last7"),trend:{days:30,metric:"o"},lists:{sellers:{q:"",sort:"gmv",n:25},products:{q:"",sort:"revenue",n:25}},
  orders:{q:"",stage:"all",n:40},teamOpen:false,staff:[],teamMsg:"",
  ads:Object.assign({aov:null,cr:null,dr:null,fx:250,cac:5,basis:"raw",low:200,high:250,cpm:"0.5,1,1.5,2",ctr:"1.5,2.5,4",
    creatives:6,testBudget:18,minSpend:3,scaleStart:20,step:20,calls:500,stock:6000,remit:10,gap:2},store.get("ads",{})),
  review:{mode:store.get("reviewMode","live"),window:store.get("reviewWindow","today"),live:{},loading:false,
    meta:store.get("metaCsv",""),orders:store.get("ordersCsv","")}};
if(!TABS[S.section])S.section="sales";

function meta(){return S.data.summary&&S.data.summary.meta}
async function api(path,opts){
  const r=await fetch(path,Object.assign({credentials:"same-origin",cache:"no-store",headers:{Accept:"application/json"}},opts||{}));
  if(r.status===401){location.href="/login";throw new Error("login required")}
  if(!r.ok)throw new Error("HTTP "+r.status);
  return r.json();
}
function ageText(mins){
  if(mins==null)return "";
  if(mins<1)return t("age.now");
  if(mins<60)return t("age.min",{n:mins});
  if(mins<1440)return t("age.hour",{n:Math.round(mins/60)});
  return t("age.day",{n:Math.round(mins/1440)});
}
function ageMinutes(){const m=meta();return m?Math.max(0,Math.round((Date.now()-new Date(m.generated_at))/6e4)):null}
function setSync(){
  const dot=$("#syncDot"),tx=$("#syncText"),sy=S.sync,m=meta(),mins=ageMinutes();
  const chip=$("#sync");
  if(chip)chip.dataset.state=(sy&&sy.state)||(m&&m.example?"example":S.net);
  if(S.net==="off"&&!m){dot.className="dot off";tx.textContent=t("sync.nodata");return}
  if(!m){dot.className="dot";tx.textContent=S.net==="wait"?t("sync.connecting"):t("sync.waiting");return}
  const stale=sy?mins>sy.stale_after_minutes:mins>150,failed=sy&&sy.odoo&&sy.odoo.last&&sy.odoo.last.ok===false;
  if(m.example){dot.className="dot ex";tx.textContent=t("sync.example");return}
  if(failed){dot.className="dot off";tx.textContent=t("sync.failed");return}
  dot.className="dot "+(stale||S.net==="off"?"off":"live");
  tx.textContent=t("sync.ago",{age:ageText(mins)});
}
async function loadReports(){
  try{
    const d=await api("/api/reports");
    ["summary","sellers","products","orders"].forEach(k=>S.data[k]=d[k]||null);
    S.sync=d.sync;S.pulse=d.pulse||null;S.net="ok";
  }catch(e){S.net="off"}
  setSync();render();
}
async function loadMe(){try{S.me=await api("/api/me")}catch(e){S.me=null}}
async function pollStatus(){
  try{
    const s=await api("/api/status");
    const changed=!S.sync||s.generated_at!==S.sync.generated_at||s.last_synced_at!==(S.sync&&S.sync.last_synced_at);
    S.sync=s;S.net="ok";
    if(changed)return loadReports();
    if(S.section==="ads"&&S.tab.ads==="review"&&S.review.mode==="live"){S.review.live={};loadAds()}
  }catch(e){S.net="off"}
  setSync();
}
async function refreshAll(){
  const btn=$("#refreshBtn");
  if(btn)btn.classList.add("spin");
  S.review.live={};
  await loadReports();
  if(S.section==="ads"&&S.tab.ads==="review"&&S.review.mode==="live")await loadAds();
  if(btn)btn.classList.remove("spin");
}
async function loadAds(){
  const w=S.review.window;if(S.review.loading===w)return;S.review.loading=w;
  try{S.review.live[w]=await api("/api/ads?window="+encodeURIComponent(w))}catch(e){S.review.live[w]={error:e.message}}
  S.review.loading=false;
  if(S.section==="ads"&&S.tab.ads==="review"&&!S.teamOpen)rerenderKeep(null);
}

function renderLangs(){
  const el=$("#langs");if(!el)return;
  const l=lang();
  el.setAttribute("aria-label",t("lang.group"));
  el.innerHTML=[["fr","FR","lang.fr"],["ar","ع","lang.ar"],["en","EN","lang.en"]].map(([id,lab,key])=>`<button type="button" data-lang="${id}" aria-pressed="${l===id}" aria-label="${esc(t(key))}">${lab}</button>`).join("");
  el.querySelectorAll("[data-lang]").forEach(b=>b.onclick=()=>{store.set("lang",b.dataset.lang);applyLang();render()});
}
function renderTabs(){
  $("#secSales").setAttribute("aria-pressed",S.section==="sales");
  $("#secAds").setAttribute("aria-pressed",S.section==="ads");
  $("#secSales").textContent=t("nav.sales");
  $("#secAds").textContent=t("nav.ads");
  $("#tabs").setAttribute("aria-label",t("nav.tabs"));
  $("#tabs").innerHTML=TABS[S.section].map(([id,key])=>`<button type="button" role="tab" data-tab="${id}" aria-selected="${S.tab[S.section]===id}">${esc(t(key))}</button>`).join("");
}
function banners(){
  const m=meta(),sy=S.sync,mins=ageMinutes();let h="";
  if(S.net==="off")h+=`<div class="banner bad"><b>${esc(t("banner.offline"))}</b> ${m?esc(t("banner.offlineCached")):esc(t("banner.offlinePull"))}</div>`;
  if(m&&m.example)h+=`<div class="banner"><b>${esc(t("banner.exampleTitle"))}</b> ${esc(t("banner.example"))}</div>`;
  else if(sy&&sy.odoo&&sy.odoo.last&&sy.odoo.last.ok===false)h+=`<div class="banner bad"><b>${esc(t("banner.failed"))}</b> ${esc(ageText(_ago(sy.odoo.last.finished_at)))}. ${esc(t("banner.failedKeep",{age:ageText(mins)}))}${sy.odoo.last.error?`<br><span class="hint">${esc(sy.odoo.last.error)}</span>`:""}</div>`;
  else if(m&&sy&&mins>sy.stale_after_minutes)h+=`<div class="banner warn"><b>${esc(t("banner.stale",{age:ageText(mins)}))}</b></div>`;
  return h;
}
function _ago(iso){return iso?Math.max(0,Math.round((Date.now()-new Date(iso))/6e4)):null}
function render(){
  applyLang();renderLangs();renderTabs();
  const btn=$("#refreshBtn");if(btn)btn.setAttribute("aria-label",t("refresh.button"));
  const tname=S.tab[S.section],main=$("#main");
  let h=banners();
  const fn={overview,trend,sellers:()=>ranked("sellers"),products:()=>ranked("products"),channels,orders,budget,plan,review}[tname]||overview;
  try{h+=S.teamOpen?teamPanel():fn()}catch(e){h+=`<section class="card"><p class="hint">${esc(t("tab.couldNot",{msg:e.message}))}</p></section>`}
  const m=meta();
  if(m&&m.fields&&!m.example&&!S.teamOpen)h+=dataChecks(m);
  const when=formatWhen(S.sync&&(S.sync.last_synced_at||S.sync.generated_at)||(m&&m.generated_at));
  h+=`<p class="age" id="lastSynced">${esc(t("foot.synced",{when:when||t("sync.waiting")}))}</p>`;
  h+=`<div class="foot">${S.me&&S.me.role==="admin"?`<button type="button" data-team="1">${esc(t(S.teamOpen?"team.back":"team.title"))}</button>`:""}<button type="button" data-logout="1">${esc(t("foot.signOut"))}</button></div>`;
  main.innerHTML=h;
  bind();
}
function dataChecks(m){
  const f=m.fields||{},o=f.order||{},l=f.line||{},dc=f.date||{},sk=f.lines_skipped||{};
  const need=[["status","checks.fStatus"],["sellers","checks.fSellers"],["store","checks.fStore"],["magento_id","checks.fMagento"],["utm_content","checks.fUtm"],["wilaya","checks.fWilaya"]];
  const missing=need.filter(([k])=>!o[k]).map(x=>t(x[1]));
  const late=dc.date_order_after_create_1h,share=dc.orders?late/dc.orders:0;
  let warn=missing.length?`<p class="hint" style="color:var(--warn)">${esc(t("checks.missing",{list:missing.join(", ")}))}</p>`:"";
  if(dc.field==="date_order"&&share>.05)warn+=`<p class="hint" style="color:var(--warn)">${esc(t("checks.dateMoved",{late:fmt(late),n:fmt(dc.orders)}))}</p>`;
  return`<details class="card" style="padding:12px 14px"${warn?" open":""}><summary class="hint" style="cursor:pointer;min-height:24px">${esc(t("checks.title"))}</summary>
    <div class="list" style="margin-top:8px">${Object.entries(o).map(([k,v])=>`<div class="kv"><span>${esc(k)}</span><span class="mono">${esc(v)}</span></div>`).join("")}
    ${Object.entries(l).map(([k,v])=>`<div class="kv"><span>${esc(t("checks.line",{k}))}</span><span class="mono">${esc(v)}</span></div>`).join("")}
    <div class="kv"><span>${esc(t("checks.dateField"))}</span><span class="mono">${esc(dc.field||"date_order")}</span></div>
    <div class="kv"><span>${esc(t("checks.scanned"))}</span><span>${fmt(m.orders_scanned)} / ${fmt(m.lines_scanned)}</span></div>
    ${sk.delivery_fee||sk.section_or_note?`<div class="kv"><span>${esc(t("checks.linesOut"))}</span><span>${esc(t("checks.linesOutValue",{d:fmt(sk.delivery_fee||0),n:fmt(sk.section_or_note||0)}))}</span></div>`:""}</div>${warn}</details>`;
}
function noData(k){return !S.data[k]?`<section class="card"><div class="empty">${S.net==="off"?esc(t("empty.live")):S.net==="wait"?esc(t("empty.wait")):esc(t("empty.first"))}</div></section>`:null}

const PERIODS=[["today","period.today","yesterday","period.vsYesterday"],["yesterday","period.yesterday",null,null],["last7","period.last7","prev7","period.vs7"],["last30","period.last30","prev30","period.vs30"]];
function delta(cur,prev,inverse){
  if(prev==null||!prev)return`<span class="d flat">${esc(t("period.noCompare"))}</span>`;
  const ch=(cur-prev)/Math.abs(prev);if(!isFinite(ch))return"";
  const good=inverse?ch<0:ch>0,cls=Math.abs(ch)<.005?"flat":good?"up":"down";
  return`<span class="d ${cls}">${ch>0?"▲":ch<0?"▼":"■"} ${fmt(Math.abs(ch*100),1)}%</span>`;
}
function bandStatus(rate,low,high){if(rate==null||!isFinite(rate))return"unknown";if(rate<low)return"short";if(rate>high)return"above";return"on_target"}
function overview(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary,p=PERIODS.find(x=>x[0]===S.period)||PERIODS[2],k=s.kpis[p[0]],pv=p[2]?s.kpis[p[2]]:null;
  const low=(S.pulse&&S.pulse.goal_low)||200,high=(S.pulse&&S.pulse.goal_high)||250;
  const ppdRate=fullDaysRate(s,7)??s.kpis.last7.orders_per_day,scaleMax=Math.max(high*1.2,ppdRate*1.1,1);
  const gst=bandStatus(ppdRate,low,high);
  const gPill=gst==="on_target"?"p-good":gst==="above"?"p-info":"p-warn";
  const gLabel=gst==="on_target"?t("goal.on"):gst==="above"?t("goal.above"):t("goal.short",{n:fmt(Math.max(0,low-ppdRate),0)});
  const today=(S.pulse&&S.pulse.today_check)||{},cap=(S.pulse&&S.pulse.spend_cap)||0.05,fx=(S.pulse&&S.pulse.fx)||250;
  const sk=today.spend_ok,sPill=sk===true?"p-good":sk===false?"p-bad":"p-idle";
  const sLabel=sk===true?t("spend.ok"):sk===false?t("spend.over"):t("spend.nodata");
  const st=k.stages||{},tot=k.orders||1;
  let h=`<div class="chips" role="group" aria-label="${esc(t("period.group"))}">${PERIODS.map(x=>`<button type="button" class="chip" data-period="${x[0]}" aria-pressed="${x[0]===p[0]}">${esc(t(x[1]))}</button>`).join("")}</div>`;
  h+=`<div class="questions">
    <section class="q" id="dailyGoal"><h2>${esc(t("goal.title"))} <small>${fmt(low)}–${fmt(high)}</small></h2>
      <div class="gauge"><div class="row2"><span><span class="big">${fmt(ppdRate,1)}</span> ${esc(t("goal.perDay"))}</span><span class="pill ${gPill}">${esc(gLabel)}</span></div>
      <div class="track"><i class="fill" style="width:${Math.min(100,ppdRate/scaleMax*100)}%"></i><i class="band" style="inset-inline-start:${low/scaleMax*100}%;width:${(high-low)/scaleMax*100}%"></i></div>
      <div class="row2"><span>0</span><span>${esc(t("goal.band",{low:fmt(low),high:fmt(high)}))}</span><span>${fmt(scaleMax,0)}</span></div></div>
      <p class="hint">${esc(t("goal.today",{n:fmt(today.orders||0)}))}</p></section>
    <section class="q" id="spendCheck"><h2>${esc(t("spend.title"))} <small>${esc(t("spend.cap",{cap:pct(cap,0)}))}</small></h2>
      <div class="row2"><span class="big" style="color:var(${sk===true?"--good":sk===false?"--bad":"--muted"})">${today.spend_ratio==null?t("num.na"):pct(today.spend_ratio,1)}</span><span class="pill ${sPill}">${esc(sLabel)}</span></div>
      <p class="hint">${esc(t("spend.detail",{spend:da(today.spend_dzd||0),value:da(today.order_value_dzd||0),fx:fmt(fx,0)}))}</p>
      ${S.pulse&&S.pulse.last7?`<p class="hint">${esc(t("spend.last7",{pct:S.pulse.last7.spend_ratio==null?t("num.na"):pct(S.pulse.last7.spend_ratio,1)}))}</p>`:""}
    </section></div>`;
  h+=`<div class="kpis">
    ${kpi(t("kpi.orders"),fmt(k.orders),pv&&delta(k.orders,pv.orders))}
    ${kpi(t("kpi.gmv"),da(k.gmv),pv&&delta(k.gmv,pv.gmv))}
    ${kpi(t("kpi.aov"),da(k.aov),pv&&delta(k.aov,pv.aov))}
    ${kpi(t("kpi.cancel"),pct(k.cancel_rate),pv&&delta(k.cancel_rate,pv.cancel_rate,true))}
    ${kpi(t("kpi.net"),da(k.net_gmv),pv&&delta(k.net_gmv,pv.net_gmv))}
    ${kpi(t("kpi.perDay"),fmt(k.orders_per_day,1),pv&&delta(k.orders_per_day,pv.orders_per_day))}
  </div>`;
  if(pv)h+=`<p class="hint" style="margin-top:-4px">${esc(t("kpi.changes",{what:t(p[3])}))}</p>`;
  h+=`<section class="card"><h2>${esc(t("status.title"))} <small>${esc(t("status.orders",{n:fmt(k.orders)}))}</small></h2>
    <div class="stack">${STAGES.map(id=>`<i class="s-${id}" style="width:${(st[id]||0)/tot*100}%"></i>`).join("")}</div>
    <div class="legend">${STAGES.map(id=>`<span><i class="s-${id}"></i>${esc(t("stage."+id))} <b class="num">${fmt(st[id]||0)}</b></span>`).join("")}</div>
    <div class="stats">
      <div class="stat"><div class="l">${esc(t("status.confirmed"))}</div><div class="v">${pct(k.confirm_rate,0)}</div><div class="u">${esc(t("status.confirmedHint"))}</div></div>
      <div class="stat"><div class="l">${esc(t("status.delivered"))}</div><div class="v">${pct(k.delivery_rate,0)}</div><div class="u">${esc(t("status.deliveredHint"))}</div></div>
      <div class="stat"><div class="l">${esc(t("status.lost"))}</div><div class="v">${pct(k.cancel_rate_value,0)}</div><div class="u">${esc(t("status.lostHint"))}</div></div>
    </div></section>`;
  h+=`<section class="card"><h2>${esc(t("hours.title"))}</h2>${hourChart(s.hours)}<p class="hint">${esc(t("hours.hint"))}</p></section>`;
  return h;
}
function fullDaysRate(s,n){const rows=(s.daily||[]).slice(0,-1).slice(-n);return rows.length?rows.reduce((a,r)=>a+r.o,0)/rows.length:null}
function kpi(l,v,d){return`<div class="kpi"><span class="l">${esc(l)}</span><span class="v">${v}</span>${d||'<span class="d flat">&nbsp;</span>'}</div>`}
function hourChart(hours){
  const W=340,H=120,max=Math.max(1,...hours),bw=W/24;
  let b="";hours.forEach((v,i)=>{const h=v/max*(H-22);b+=`<rect x="${i*bw+1.5}" y="${H-16-h}" width="${bw-3}" height="${h}" rx="2" fill="var(--accent)" opacity="${v===max?1:.55}"><title>${i}:00 · ${v}</title></rect>`});
  [0,6,12,18,23].forEach(i=>b+=`<text x="${i*bw+bw/2}" y="${H-3}" text-anchor="middle">${i}h</text>`);
  const peak=hours.indexOf(Math.max(...hours));
  return`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("hours.chart",{h:peak}))}">${b}</svg>`;
}

function trend(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary,days=s.daily.slice(-S.trend.days),M=S.trend.metric;
  const W=360,H=190,pad=34,cw=W-pad-6,ch=H-38,bw=cw/days.length;
  const val=d=>M==="o"?d.o:d.g,cval=d=>M==="o"?d.c:d.cg;
  const goalLow=(S.pulse&&S.pulse.goal_low)||200;
  const max=Math.max(1,...days.map(val),M==="o"?goalLow:0),nice=niceMax(max);
  let g="";
  [0,.5,1].forEach(f=>{const y=10+ch-ch*f;g+=`<line x1="${pad}" x2="${W-6}" y1="${y}" y2="${y}" stroke="var(--line)"/><text x="${pad-5}" y="${y+3}" text-anchor="end">${M==="o"?fmt(nice*f):da(nice*f).replace(" "+t("currency.dzd"),"")}</text>`});
  days.forEach((d,i)=>{const v=val(d),c=cval(d),hv=v/nice*ch,hc=c/nice*ch,x=pad+i*bw;
    g+=`<rect x="${x+bw*.12}" y="${10+ch-hv}" width="${bw*.76}" height="${hv}" fill="var(--accent)" opacity=".8"><title>${d.date}</title></rect>`;
    if(hc>0)g+=`<rect x="${x+bw*.12}" y="${10+ch-hc}" width="${bw*.76}" height="${hc}" fill="var(--bad)"/>`;});
  const step=Math.ceil(days.length/5);
  days.forEach((d,i)=>{if(i%step===0||i===days.length-1)g+=`<text x="${pad+i*bw+bw/2}" y="${H-8}" text-anchor="middle">${d.date.slice(5)}</text>`});
  if(M==="o"&&goalLow<=nice){const y=10+ch-goalLow/nice*ch;g+=`<line x1="${pad}" x2="${W-6}" y1="${y}" y2="${y}" stroke="var(--good)" stroke-dasharray="4 3"/><text x="${W-8}" y="${y-4}" text-anchor="end" style="fill:var(--good)">${fmt(goalLow)}</text>`}
  const tot=days.reduce((a,d)=>a+val(d),0),canc=days.reduce((a,d)=>a+cval(d),0);
  let h=`<div class="chips">${[[7,"trend.days7"],[30,"trend.days30"],[90,"trend.days90"]].map(([n,key])=>`<button type="button" class="chip" data-tdays="${n}" aria-pressed="${S.trend.days===n}">${esc(t(key))}</button>`).join("")}
    <span style="flex:1"></span>${[["o","trend.metricOrders"],["g","trend.metricGmv"]].map(([m,key])=>`<button type="button" class="chip" data-tmetric="${m}" aria-pressed="${M===m}">${esc(t(key))}</button>`).join("")}</div>`;
  h+=`<section class="card"><h2>${esc(t(M==="o"?"trend.titleOrders":"trend.titleGmv"))}</h2>
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("trend.chart"))}">${g}</svg>
    <div class="stats"><div class="stat"><div class="l">${esc(t("trend.total"))}</div><div class="v">${M==="o"?fmt(tot):da(tot)}</div></div>
    <div class="stat"><div class="l">${esc(t("trend.avg"))}</div><div class="v">${M==="o"?fmt(tot/days.length,1):da(tot/days.length)}</div></div>
    <div class="stat"><div class="l">${esc(t("trend.cancelled"))}</div><div class="v">${pct(tot?canc/tot:0,0)}</div></div></div></section>`;
  h+=`<section class="card"><h2>${esc(t("trend.heat"))}</h2>${heat(s.weekday_hours)}</section>`;
  return h;
}
function niceMax(v){const p=Math.pow(10,Math.floor(Math.log10(v)));return Math.ceil(v/p*2)/2*p}
function heat(m){
  const days=["wd.mon","wd.tue","wd.wed","wd.thu","wd.fri","wd.sat","wd.sun"],W=360,cw=(W-34)/24,chh=15,H=7*chh+18,max=Math.max(1,...m.flat());
  let g="";m.forEach((row,d)=>{g+=`<text x="0" y="${d*chh+11}">${esc(t(days[d]))}</text>`;row.forEach((v,hh)=>{g+=`<rect x="${34+hh*cw}" y="${d*chh}" width="${cw-1.5}" height="${chh-2}" rx="2" fill="var(--accent)" opacity="${v?(.08+.92*v/max).toFixed(2):.04}"><title>${t(days[d])} ${hh}:00 · ${v}</title></rect>`})});
  [0,6,12,18,23].forEach(hh=>g+=`<text x="${34+hh*cw+cw/2}" y="${H-2}" text-anchor="middle">${hh}h</text>`);
  return`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("trend.heat"))}">${g}</svg>`;
}

const cancelPill=c=>`<span class="pill ${c>.3?"p-bad":c>.15?"p-warn":"p-good"}">${pct(c,0)} ${esc(t("cancel.word"))}</span>`;
function ranked(kind){
  const e=noData(kind);if(e)return e;
  const doc=S.data[kind],L=S.lists[kind],isP=kind==="products";
  const sorts=isP?[["revenue","products.sortRevenue"],["qty","products.sortUnits"],["cancel","products.sortCancel"]]:[["gmv","sellers.sortGmv"],["orders","sellers.sortOrders"],["cancel","sellers.sortCancel"]];
  let rows=doc.rows.filter(r=>!L.q||String(r.name).toLowerCase().includes(L.q.toLowerCase()));
  const cr=r=>r.orders?r.cancelled/r.orders:0,key=L.sort==="cancel"?cr:r=>r[L.sort];
  rows=rows.slice().sort((a,b)=>key(b)-key(a)||(b.orders-a.orders));
  const total=doc.rows.reduce((a,r)=>a+(isP?r.revenue:r.gmv),0),top=Math.max(1,...rows.map(r=>isP?r.revenue:r.gmv));
  let h=`<div class="search"><input id="q_${kind}" type="search" placeholder="${esc(t(isP?"products.search":"sellers.search"))}" value="${esc(L.q)}" aria-label="${esc(t(isP?"products.search":"sellers.search"))}">
    <select id="s_${kind}" aria-label="${esc(t("sort.label"))}">${sorts.map(([v,key])=>`<option value="${v}" ${L.sort===v?"selected":""}>${esc(t(key))}</option>`).join("")}</select></div>`;
  h+=`<section class="card"><h2>${esc(t(isP?"products.title":"sellers.title"))} <small>${esc(t("ranked.window",{n:fmt(doc.rows.length)+(doc.meta&&doc.meta.trimmed?"+":"")}))}</small></h2><div class="list">`;
  rows.slice(0,L.n).forEach(r=>{const v=isP?r.revenue:r.gmv,c=cr(r);
    h+=`<div class="item"><span class="n">${esc(r.name)}</span><span class="r">${da(v)}</span>
      <span class="s">${esc(t(isP?"products.meta":"sellers.meta",{orders:fmt(r.orders),units:fmt(r.qty),share:pct(total?v/total:0,1)}))}</span>
      <span class="s" style="text-align:end">${cancelPill(c)}</span>
      <span class="share"><i style="width:${v/top*100}%"></i></span></div>`});
  if(!rows.length)h+=`<div class="empty">${esc(t("empty.match"))}</div>`;
  h+=`</div>${rows.length>L.n?`<button type="button" class="more" data-more="${kind}">${esc(t("more.show",{n:Math.min(25,rows.length-L.n)}))}</button>`:""}`;
  if(!isP&&doc.meta)h+=`<p class="hint">${esc(t("sellers.basis",{basis:doc.meta.seller_basis||""}))}</p>`;
  if(doc.meta&&doc.meta.trimmed)h+=`<p class="hint">${esc(t("trimmed",{kind:t(isP?"tab.products":"tab.sellers")}))}</p>`;
  return h+`</section>`;
}

function channels(){
  const e=noData("summary");if(e)return e;
  const s=S.data.summary;
  const block=(title,rows,note)=>{if(!rows||!rows.length)return"";const tot=rows.reduce((a,r)=>a+r.gmv,0),top=Math.max(1,...rows.map(r=>r.gmv));
    return`<section class="card"><h2>${esc(title)} <small>${esc(t("channels.window"))}</small></h2><div class="list">${rows.slice(0,12).map(r=>{const c=r.orders?r.cancelled/r.orders:0;
      return`<div class="item"><span class="n">${esc(r.name)}</span><span class="r">${da(r.gmv)}</span><span class="s">${esc(t("channels.meta",{orders:fmt(r.orders),share:pct(tot?r.gmv/tot:0,0),deliv:pct(r.orders?r.delivered/r.orders:0,0)}))}</span><span class="s" style="text-align:end">${cancelPill(c)}</span><span class="share"><i style="width:${r.gmv/top*100}%"></i></span></div>`}).join("")}</div>${note?`<p class="hint">${esc(note)}</p>`:""}</section>`};
  return block(t("channels.stores"),s.stores)+block(t("channels.utm"),s.utm,t("channels.utmNote"))+block(t("channels.wilayas"),s.wilayas)+block(t("channels.people"),s.salespeople)||`<section class="card"><div class="empty">${esc(t("empty.channels"))}</div></section>`;
}

function orders(){
  const e=noData("orders");if(e)return e;
  const O=S.orders,q=O.q.toLowerCase();
  let rows=S.data.orders.rows.filter(r=>(O.stage==="all"||r.st===O.stage)&&(!q||[r.ref,r.mg,r.cu,r.se,r.so].some(x=>x&&String(x).toLowerCase().includes(q))));
  let h=`<div class="search"><input id="q_orders" type="search" placeholder="${esc(t("orders.search"))}" value="${esc(O.q)}" aria-label="${esc(t("orders.search"))}"></div>
    <div class="chips">${[["all","stage.all"],...STAGES.map(id=>[id,"stage."+id])].map(([id,key])=>`<button type="button" class="chip" data-stage="${id}" aria-pressed="${O.stage===id}">${esc(t(key))}</button>`).join("")}</div>`;
  h+=`<section class="card"><h2>${esc(t("orders.title"))} <small>${esc(t("orders.count",{n:fmt(rows.length),all:fmt(S.data.orders.rows.length)}))}</small></h2><div class="list">`;
  rows.slice(0,O.n).forEach(r=>{h+=`<div class="ord"><span class="a">${esc(r.ref)}${r.mg?` <span style="color:var(--muted);font-weight:500">#${esc(r.mg)}</span>`:""}</span><span class="t">${da(r.t)}</span>
    <span class="c">${esc(r.dt)} · ${esc(r.cu||t("orders.guest"))}${r.se?" · "+esc(r.se):""}</span><span style="text-align:end"><span class="pill ${STAGE_PILL[r.st]||"p-idle"}" title="${esc(r.raw||"")}">${esc(t("stage."+(r.st||"pending")))}</span></span></div>`});
  if(!rows.length)h+=`<div class="empty">${esc(t("orders.empty"))}</div>`;
  h+=`</div>${rows.length>O.n?`<button type="button" class="more" data-more="orders">${esc(t("orders.more"))}</button>`:""}</section>`;
  return h;
}

function live(){const k=S.data.summary&&S.data.summary.kpis&&S.data.summary.kpis.last30;return k||null}
function odooDefaults(){const k=live();return{aov:k&&k.aov?k.aov:4500,cr:k&&k.confirm_rate!=null?+(k.confirm_rate*100).toFixed(0):70,dr:k&&k.delivery_rate!=null?+(k.delivery_rate*100).toFixed(0):75}}
function adsInputs(){
  const A=S.ads,D=odooDefaults();
  const aov=+(A.aov??D.aov)||4500,cr=(+(A.cr??D.cr))/100,dr=(+(A.dr??D.dr))/100;
  return{aov,c:Math.min(1,Math.max(.01,cr||.7)),d:Math.min(1,Math.max(.01,dr||.75)),fx:+A.fx||250,cac:(+A.cac||5)/100,basis:A.basis,low:+A.low||200,high:+A.high||250};
}
function field(id,label,val,opts){const src=opts&&opts.src;return`<label for="${id}">${esc(label)}${src?` <span class="src">${esc(src)}</span>`:""}
  ${opts&&opts.select?`<select id="${id}" data-ads="${id}">${opts.select.map(([v,l])=>`<option value="${v}" ${String(val)===v?"selected":""}>${esc(l)}</option>`).join("")}</select>`
  :`<input id="${id}" data-ads="${id}" inputmode="decimal" value="${esc(val)}">`}</label>`}

function budget(){
  const I=adsInputs(),k=live(),A=S.ads,D=odooDefaults();
  const B=C.cacBudget(I),perConf=B.perConf,perDeliv=B.perDeliv,perRaw=B.perRaw;
  const src=k&&!(meta()&&meta().example)?t("budget.fromOdoo"):k?t("budget.example"):null;
  let h=`<section class="card"><h2>${esc(t("budget.title"))}</h2><div class="form">
    ${field("aov",t("budget.aov"),A.aov??D.aov,{src:A.aov==null&&src})}
    ${field("fx",t("budget.fx"),A.fx)}
    ${field("cr",t("budget.cr"),A.cr??D.cr,{src:A.cr==null&&src})}
    ${field("dr",t("budget.dr"),A.dr??D.dr,{src:A.dr==null&&src})}
    ${field("cac",t("budget.cac"),A.cac)}
    ${field("basis",t("budget.basis"),A.basis,{select:[["raw",t("budget.basisPlaced")],["confirmed",t("budget.basisConfirmed")],["delivered",t("budget.basisDelivered")]]})}
    ${field("low",t("budget.low"),A.low)}
    ${field("high",t("budget.high"),A.high)}
  </div>${A.aov!=null||A.cr!=null||A.dr!=null?`<button type="button" class="btn ghost" data-reset="1">${esc(t("budget.reset"))}</button>`:""}</section>`;
  h+=`<section class="card"><h2>${esc(t("budget.max"))}</h2><div class="stats">
    <div class="stat"><div class="l">${esc(t("budget.perPlaced"))}</div><div class="v">${usd(perRaw/I.fx)}</div><div class="u">${da(perRaw)}</div></div>
    <div class="stat"><div class="l">${esc(t("budget.perConfirmed"))}</div><div class="v">${usd(perConf/I.fx)}</div><div class="u">${da(perConf)}</div></div>
    <div class="stat"><div class="l">${esc(t("budget.perDelivered"))}</div><div class="v">${usd(perDeliv/I.fx)}</div><div class="u">${da(perDeliv)}</div></div></div>
    ${I.basis!=="delivered"?`<p class="hint">${esc(t("budget.realCost",{da:da(perDeliv),pct:pct(perDeliv/I.aov)}))}</p>`:""}</section>`;
  h+=`<section class="card"><h2>${esc(t("budget.dailyTitle"))}</h2><div class="list">${B.daily.map(v=>`<div class="item"><span class="n">${esc(t("budget.placedDay",{n:fmt(v.placed)}))}</span><span class="r">${usd(v.spend/I.fx,0)}${esc(t("budget.perDay"))}</span><span class="s">${esc(t("budget.mix",{c:fmt(v.conf),d:fmt(v.deliv),da:da(v.spend)}))}</span></div>`).join("")}</div>`;
  if(k){const r30=fullDaysRate(S.data.summary,30);h+=`<p class="hint">${esc(t("budget.rightNow",{n:fmt(r30??k.orders_per_day,1)}))}</p>`}
  h+=`</section>`;
  const raw=perRaw/I.fx,cpms=String(A.cpm).split(",").map(Number).filter(x=>x>0),ctrs=String(A.ctr).split(",").map(Number).filter(x=>x>0);
  h+=`<section class="card"><h2>${esc(t("budget.landing",{usd:usd(raw)}))}</h2>
    <div class="form">${field("cpm",t("budget.cpm"),A.cpm)}${field("ctr",t("budget.ctr"),A.ctr)}</div>
    <div class="scroll"><table><thead><tr><th>${esc(t("budget.cpmShort"))}</th>${ctrs.map(x=>`<th>${esc(t("budget.ctrShort",{n:fmt(x,1)}))}</th>`).join("")}</tr></thead><tbody>${cpms.map(m=>`<tr><td>$${fmt(m,2)}</td>${ctrs.map(x=>{const need=C.landingNeeded(m,x,raw);return`<td class="${need<=.05?"ok":need<=.1?"mid":"no"}">${need>1?esc(t("budget.impossible")):pct(need)}</td>`}).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="hint">${esc(t("budget.landingHint"))}</p></section>`;
  return h;
}

function plan(){
  const I=adsInputs(),A=S.ads,cpa=C.capConfUsd(I.cac,I.aov,I.fx,I.basis,I.c,I.d);
  const hiD=C.toDeliv(I.high,"raw",I.c,I.d),hiSpend=hiD/I.d*cpa,calls=+A.calls||0,capD=calls*I.c*I.d;
  let ceiling=hiSpend;if(calls)ceiling=Math.min(ceiling,calls*I.c*cpa);
  const top=Math.max(ceiling-(+A.testBudget||0),+A.scaleStart||20);
  let h=`<section class="card"><h2>${esc(t("plan.title"))}</h2><div class="form">
    ${field("creatives",t("plan.creatives"),A.creatives)}${field("testBudget",t("plan.testBudget"),A.testBudget)}
    ${field("minSpend",t("plan.minSpend"),A.minSpend)}${field("scaleStart",t("plan.scaleStart"),A.scaleStart)}
    ${field("step",t("plan.step"),A.step)}${field("calls",t("plan.calls"),A.calls)}
    ${field("stock",t("plan.stock"),A.stock)}${field("remit",t("plan.remit"),A.remit)}
  </div></section>`;
  const need=(+A.creatives)*(+A.minSpend),per=Math.max(1,Math.floor((+A.testBudget)/(+A.minSpend)));
  const basis=t(I.basis==="confirmed"?"budget.basisConfirmed":I.basis==="delivered"?"budget.basisDelivered":"budget.basisPlaced");
  h+=`<section class="card"><h2>${esc(t("plan.rules"))}</h2>
    <div class="verdict">${esc(t("plan.target",{usd:usd(cpa),cap:pct(I.cac,0),aov:fmt(I.aov),basis}))}</div>
    <div class="list">
      <div class="item"><span class="n">${esc(t("plan.testing"))}</span><span class="r">${need<=+A.testBudget?`<span class="pill p-good">${esc(t("plan.ok"))}</span>`:`<span class="pill p-warn">${esc(t("plan.waves"))}</span>`}</span><span class="s">${need<=+A.testBudget?esc(t("plan.testingOk",{n:A.creatives,min:A.minSpend,total:fmt(need)})):esc(t("plan.testingWaves",{need:fmt(need),budget:A.testBudget,per}))}</span></div>
      <div class="item"><span class="n">${esc(t("plan.promote"))}</span><span class="r"><span class="pill p-good">≤ ${usd(cpa)}</span></span><span class="s">${esc(t("plan.promoteHint"))}</span></div>
      <div class="item"><span class="n">${esc(t("plan.kill"))}</span><span class="r"><span class="pill p-bad">&gt; ${usd(cpa*1.5)}</span></span><span class="s">${esc(t("plan.killHint",{none:usd(cpa*2.5),rate:pct(Math.max(0,I.c-.2),0)}))}</span></div>
    </div></section>`;
  h+=`<section class="card"><h2>${esc(t("plan.capacity",{n:fmt(I.high)}))}</h2><div class="list">
    <div class="item"><span class="n">${esc(t("plan.spendNeeded"))}</span><span class="r">${usd(hiSpend,0)}${esc(t("budget.perDay"))}</span><span class="s">${da(hiSpend*I.fx)}</span></div>
    <div class="item"><span class="n">${esc(t("plan.callsRow"))}</span><span class="r"><span class="pill ${!calls||capD>=hiD-.5?"p-good":"p-bad"}">${!calls?esc(t("plan.callsUnset")):capD>=hiD-.5?esc(t("plan.ok")):esc(t("plan.callsFew"))}</span></span><span class="s">${esc(t("plan.callsHint",{need:fmt(I.high),have:fmt(calls)}))}</span></div>
    <div class="item"><span class="n">${esc(t("plan.stockRow"))}</span><span class="r">${esc(t("plan.stockDays",{n:fmt((+A.stock)/(hiD/I.d),0)}))}</span><span class="s">${esc(t("plan.stockHint",{stock:fmt(A.stock),ship:fmt(hiD/I.d)}))}</span></div>
    <div class="item"><span class="n">${esc(t("plan.cash"))}</span><span class="r">${usd(hiSpend*(+A.remit),0)}</span><span class="s">${esc(t("plan.cashHint",{days:A.remit,da:da(hiSpend*(+A.remit)*I.fx)}))}</span></div></div></section>`;
  const gap=+A.gap||2;let bud=+A.scaleStart||20,day=1,step=0;const rows=[];
  while(true){rows.push({step,day,budget:bud});if(bud>=top||step>80)break;bud=Math.min(bud*(1+(+A.step||20)/100),top);step++;day+=gap}
  h+=`<section class="card"><h2>${esc(t("plan.schedule"))}</h2>
    <div class="chips"><button type="button" class="chip" data-gap="2" aria-pressed="${gap===2}">${esc(t("plan.every48"))}</button><button type="button" class="chip" data-gap="1" aria-pressed="${gap===1}">${esc(t("plan.every24"))}</button></div>
    <div class="scroll"><table><thead><tr><th>${esc(t("plan.colDay"))}</th><th>${esc(t("plan.colBudget"))}</th><th>${esc(t("plan.colPlaced"))}</th><th>${esc(t("plan.colConfirmed"))}</th><th>${esc(t("plan.colDelivered"))}</th></tr></thead><tbody>
    ${rows.map(r=>{const conf=r.budget/cpa;return`<tr><td>${r.day}</td><td>${usd(r.budget,0)}</td><td>${fmt(conf/I.c)}</td><td>${fmt(conf)}</td><td>${fmt(conf*I.d)}</td></tr>`}).join("")}</tbody></table></div>
    <p class="hint">${esc(t("plan.scheduleHint",{day,weeks:(day/7).toFixed(1)}))}</p></section>`;
  return h;
}

const WINDOWS=[["today","period.today"],["yesterday","period.yesterday"],["last7","period.last7"]];
function decisionText(r){
  const label=r.label||"";
  if(r.code==="fix"||label==="Fix tracking")return t("decision.fix");
  if(label.indexOf("under 3 full days")>=0)return t("decision.waitYoung",{detail:label.replace(/^Wait: under 3 full days \(would /,"").replace(/\)$/,"")});
  if(label.indexOf("most orders")>=0)return t("decision.waitPending");
  if(label.indexOf("not enough")>=0)return t("decision.waitData");
  if(label.indexOf("junk")>=0)return t("decision.killJunk");
  if(label.indexOf("no orders")>=0)return t("decision.killNone");
  if(label.indexOf("Kill: CAC")===0)return t("decision.killCac",{pct:label.replace("Kill: CAC ","")});
  if(r.code==="promote")return t("decision.promote");
  return label;
}
function review(){
  const I=adsInputs(),R=S.review;
  let h=`<div class="chips" role="group" aria-label="${esc(t("review.source"))}"><button type="button" class="chip" data-rmode="live" aria-pressed="${R.mode==="live"}">${esc(t("review.live"))}</button><button type="button" class="chip" data-rmode="upload" aria-pressed="${R.mode==="upload"}">${esc(t("review.upload"))}</button></div>`;
  return h+(R.mode==="live"?reviewLive(I):reviewUpload(I));
}
function reviewLive(I){
  const R=S.review,d=R.live[R.window];
  let h=`<div class="chips" role="group" aria-label="${esc(t("period.group"))}">${WINDOWS.map(([w,key])=>`<button type="button" class="chip" data-rwin="${w}" aria-pressed="${R.window===w}">${esc(t(key))}</button>`).join("")}</div>`;
  if(!d){if(!R.loading)setTimeout(loadAds,0);return h+`<section class="card"><div class="empty">${esc(t("review.loading"))}</div></section>`}
  if(d.error)return h+`<section class="card"><div class="empty">${esc(t("review.error",{err:d.error}))}</div></section>`;
  const ms=d.sync&&d.sync.meta,last=ms&&ms.last;
  let note=last?t("review.metaAgo",{age:ageText(_ago(last.finished_at))})+(last.ok===false?" · "+t("review.metaFailed"):""):t("review.metaNever");
  if(!d.has_spend&&!d.has_orders)return h+`<section class="card"><div class="empty">${esc(t("review.empty",{start:d.start,end:d.end!==d.start?" → "+d.end:""}))}<br><span class="hint">${esc(note)}</span></div></section>`;
  let spend=d.spend,warn="";
  if(d.currency&&d.currency!=="USD"){
    if(d.currency==="DZD"){spend=Object.fromEntries(Object.entries(d.spend).map(([k,v])=>[k,v/I.fx]));warn=t("currency.warnDzd",{fx:fmt(I.fx)})}
    else warn=t("currency.warnOther",{cur:d.currency});
  }
  if(d.timezone_offset_hours_utc!=null&&+d.timezone_offset_hours_utc!==1)warn+=(warn?" ":"")+t("tz.warn",{tz:d.timezone_name||""});
  if(warn)h+=`<div class="banner warn">${esc(warn)}</div>`;
  const res=C.review(spend,d.groups,I,d.days_running);
  h+=account(res,I,`${d.start}${d.end!==d.start?" → "+d.end:""}`);
  h+=adList(res,true);
  h+=`<p class="hint">${esc(note)}. ${esc(t("review.joinNote"))}${d.other_channels?" "+esc(t("review.other",{n:fmt(d.other_channels)})):""} ${esc(t("review.youngNote"))}</p>`;
  return h;
}
function reviewUpload(I){
  const R=S.review;
  let h=`<section class="card"><h2>${esc(t("review.uploadTitle"))}</h2>
    <label class="file">${esc(t("review.uploadMeta"))}<input type="file" id="fMeta" accept=".csv,text/csv"></label>
    <label class="file">${esc(t("review.uploadOrders"))}<input type="file" id="fOrd" accept=".csv,text/csv"></label>
    <p class="hint">${esc(t("review.uploadHint"))}</p>
    ${R.meta?`<button type="button" class="btn ghost" data-clear="1">${esc(t("review.clear"))}</button>`:""}</section>`;
  if(!R.meta)return h+`<section class="card"><div class="empty">${esc(t("review.needFile",{cap:pct(I.cac,0)}))}</div></section>`;
  const spend=C.spendFromCsv(R.meta);let groups={};
  if(R.orders)groups=C.groupsFromCsv(R.orders);
  else if(S.data.summary){const utm=S.data.summary.utm||[];Object.keys(spend).forEach(n=>{const m=utm.filter(u=>u.name.toLowerCase().includes(n.toLowerCase())||n.toLowerCase().includes((u.name.split(" / ").pop()||"").toLowerCase()));
      if(m.length){const g=groups[n]=C.newGroup();g.approx=true;m.forEach(u=>{g.raw+=u.orders;g.conf+=u.confirmed;g.deliv+=u.delivered;g.val.push(u.gmv/u.orders)})}})}
  const res=C.review(spend,groups,I,null);
  h+=account(res,I,t("review.uploaded"));
  h+=adList(res,false);
  h+=`<p class="hint">${esc(t("review.uploadNote"))}</p>`;
  return h;
}
function account(res,I,label){
  const a=res.account;
  return`<section class="card"><h2>${esc(t("account.title"))} <small>${esc(label)}</small></h2><div class="stats">
    <div class="stat"><div class="l">${esc(t("account.spend"))}</div><div class="v">${usd(a.spAll,0)}</div><div class="u">${da(a.spAll*I.fx)}</div></div>
    <div class="stat"><div class="l">${esc(t("account.orders"))}</div><div class="v">${fmt(a.rawAll)}</div><div class="u">${esc(t("account.confirmed",{n:fmt(a.confAll)}))}</div></div>
    <div class="stat"><div class="l">${esc(t("account.cac"))}</div><div class="v" style="color:var(${a.ok?"--good":"--bad"})">${isFinite(a.blended)?pct(a.blended):t("num.na")}</div><div class="u">${esc(a.ok?t("account.ok"):t("account.over"))} · ${esc(t("account.cap",{cap:pct(I.cac,0),basis:t(I.basis==="confirmed"?"budget.basisConfirmed":I.basis==="delivered"?"budget.basisDelivered":"budget.basisPlaced")}))}</div></div></div>
    ${a.perDelivPct!=null&&I.basis!=="delivered"?`<p class="hint">${esc(t("account.perDelivered",{pct:pct(a.perDelivPct)}))}</p>`:""}</section>`;
}
function adList(res,liveMode){
  return`<section class="card"><h2>${esc(t("ads.title"))}</h2><div class="list">${res.rows.map(r=>`<div class="item"><span class="n">${esc(r.n)}</span><span class="r">${isFinite(r.cac)?pct(r.cac):t("num.na")}</span>
    <span class="s">${usd(r.sp)} · ${esc(t("ads.line",{placed:fmt(r.g.raw),conf:fmt(r.g.conf),rate:pct(r.rate,0),aov:da(r.aov)}))}${r.g.approx?" · "+esc(t("ads.matched")):""}${liveMode&&r.days!=null?" · "+esc(t("ads.days",{n:r.days})):""}</span>
    <span class="s" style="grid-column:1/-1"><span class="pill ${DECISION_PILL[r.code]||"p-idle"}">${esc(decisionText(r))}</span></span></div>`).join("")||`<div class="empty">${esc(t("ads.empty"))}</div>`}</div></section>`;
}

function teamPanel(){
  const rows=S.staff||[];
  let h=`<section class="card"><h2>${esc(t("team.title"))}</h2><p class="hint">${esc(t("team.intro"))}</p>`;
  if(S.teamMsg)h+=`<p class="hint">${esc(t(S.teamMsg))}</p>`;
  h+=`<form class="form" id="teamForm">
    <label>${esc(t("team.name"))}<input id="tm_name" autocomplete="name"></label>
    <label>${esc(t("team.email"))}<input id="tm_email" type="email" autocomplete="off" inputmode="email"></label>
    <label>${esc(t("team.password"))}<input id="tm_password" type="password" autocomplete="new-password"></label>
    <label>${esc(t("team.role"))}<select id="tm_role"><option value="staff">${esc(t("team.roleStaff"))}</option><option value="admin">${esc(t("team.roleAdmin"))}</option></select></label>
    <button class="btn" type="submit">${esc(t("team.add"))}</button>
  </form><p class="hint">${esc(t("team.passwordHint"))}</p></section>`;
  h+=`<section class="card"><div class="list">${rows.map(s=>`<div class="item"><span class="n">${esc(s.name||s.email)}</span><span class="r">${esc(s.role==="admin"?t("team.roleAdmin"):t("team.roleStaff"))}</span><span class="s">${esc(s.email)}${s.email===(S.me&&S.me.email)?" · "+esc(t("team.you")):""}</span><span class="s" style="text-align:end">${s.email===(S.me&&S.me.email)?"":`<button type="button" class="btn ghost" data-remove="${esc(s.email)}">${esc(t("team.remove"))}</button>`}</span></div>`).join("")||`<div class="empty">${esc(t("team.empty"))}</div>`}</div></section>`;
  return h;
}
async function openTeam(){
  S.teamOpen=true;S.teamMsg="";
  try{const d=await api("/api/staff");S.staff=d.staff||[]}catch(e){S.staff=[];S.teamMsg="team.error"}
  render();
}

function bind(){
  document.querySelectorAll("[data-period]").forEach(b=>b.onclick=()=>{S.period=b.dataset.period;store.set("period",S.period);render()});
  document.querySelectorAll("[data-tdays]").forEach(b=>b.onclick=()=>{S.trend.days=+b.dataset.tdays;render()});
  document.querySelectorAll("[data-tmetric]").forEach(b=>b.onclick=()=>{S.trend.metric=b.dataset.tmetric;render()});
  document.querySelectorAll("[data-stage]").forEach(b=>b.onclick=()=>{S.orders.stage=b.dataset.stage;S.orders.n=40;render()});
  document.querySelectorAll("[data-more]").forEach(b=>b.onclick=()=>{const k=b.dataset.more;if(k==="orders")S.orders.n+=40;else S.lists[k].n+=25;rerenderKeep(null)});
  document.querySelectorAll("[data-gap]").forEach(b=>b.onclick=()=>{S.ads.gap=+b.dataset.gap;saveAds();rerenderKeep(null)});
  document.querySelectorAll("[data-rmode]").forEach(b=>b.onclick=()=>{S.review.mode=b.dataset.rmode;store.set("reviewMode",S.review.mode);render()});
  document.querySelectorAll("[data-rwin]").forEach(b=>b.onclick=()=>{S.review.window=b.dataset.rwin;store.set("reviewWindow",S.review.window);render()});
  ["sellers","products"].forEach(k=>{const q=$("#q_"+k),s=$("#s_"+k);
    if(q)q.oninput=()=>{S.lists[k].q=q.value;S.lists[k].n=25;rerenderKeep("q_"+k)};
    if(s)s.onchange=()=>{S.lists[k].sort=s.value;render()}});
  const qo=$("#q_orders");if(qo)qo.oninput=()=>{S.orders.q=qo.value;S.orders.n=40;rerenderKeep("q_orders")};
  document.querySelectorAll("[data-ads]").forEach(el=>el.onchange=()=>{const k=el.dataset.ads;S.ads[k]=el.tagName==="SELECT"||k==="cpm"||k==="ctr"?el.value:(el.value===""?null:el.value);saveAds();rerenderKeep(null)});
  const r=$("[data-reset]");if(r)r.onclick=()=>{S.ads.aov=S.ads.cr=S.ads.dr=null;saveAds();render()};
  const fm=$("#fMeta"),fo=$("#fOrd");
  if(fm)fm.onchange=()=>readFile(fm,"meta");if(fo)fo.onchange=()=>readFile(fo,"orders");
  const cl=$("[data-clear]");if(cl)cl.onclick=()=>{S.review.meta="";S.review.orders="";store.set("metaCsv","");store.set("ordersCsv","");render()};
  const lo=$("[data-logout]");if(lo)lo.onclick=async()=>{try{await fetch("/auth/logout",{method:"POST",credentials:"same-origin",cache:"no-store"})}catch(e){}
    try{if(window.caches)for(const k of await caches.keys())await caches.delete(k)}catch(e){}location.href="/login"};
  const tm=$("[data-team]");if(tm)tm.onclick=()=>{if(S.teamOpen){S.teamOpen=false;render()}else openTeam()};
  const tf=$("#teamForm");if(tf)tf.onsubmit=async ev=>{
    ev.preventDefault();
    const body={name:$("#tm_name").value,email:$("#tm_email").value,password:$("#tm_password").value,role:$("#tm_role").value};
    try{
      const res=await fetch("/api/staff",{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(!res.ok){S.teamMsg="team.error";render();return}
      S.teamMsg="team.saved";await openTeam();S.teamMsg="team.saved";render();
    }catch(e){S.teamMsg="team.error";render()}
  };
  document.querySelectorAll("[data-remove]").forEach(b=>b.onclick=async()=>{
    const email=b.dataset.remove;
    try{
      const res=await fetch("/api/staff/"+encodeURIComponent(email),{method:"DELETE",credentials:"same-origin",cache:"no-store"});
      if(!res.ok){S.teamMsg="team.error";render();return}
      await openTeam();
    }catch(e){S.teamMsg="team.error";render()}
  });
}
function readFile(input,key){const f=input.files&&input.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{S.review[key]=String(rd.result);store.set(key==="meta"?"metaCsv":"ordersCsv",S.review[key].length<400000?S.review[key]:"");render()};rd.readAsText(f)}
function saveAds(){const {aov,cr,dr,fx,cac,basis,low,high,cpm,ctr,creatives,testBudget,minSpend,scaleStart,step,calls,stock,remit,gap}=S.ads;store.set("ads",{aov,cr,dr,fx,cac,basis,low,high,cpm,ctr,creatives,testBudget,minSpend,scaleStart,step,calls,stock,remit,gap})}
function rerenderKeep(id){const y=window.scrollY,el=id&&$("#"+id),pos=el?el.selectionStart:null;render();if(id){const n=$("#"+id);if(n){n.focus();try{n.setSelectionRange(pos,pos)}catch(e){}}}window.scrollTo(0,y)}

$("#secSales").onclick=()=>{S.section="sales";S.teamOpen=false;store.set("section","sales");render();window.scrollTo(0,0)};
$("#secAds").onclick=()=>{S.section="ads";S.teamOpen=false;store.set("section","ads");render();window.scrollTo(0,0)};
$("#tabs").onclick=e=>{const b=e.target.closest("[data-tab]");if(!b)return;S.teamOpen=false;S.tab[S.section]=b.dataset.tab;store.set("tab",S.tab);render();window.scrollTo(0,0)};
const refreshBtn=$("#refreshBtn");
if(refreshBtn)refreshBtn.onclick=()=>refreshAll();
let pullY=0,pulling=false;
document.addEventListener("touchstart",e=>{if(window.scrollY<=0&&e.touches.length===1){pulling=true;pullY=e.touches[0].clientY}},{passive:true});
document.addEventListener("touchmove",e=>{
  if(!pulling)return;
  const dy=e.touches[0].clientY-pullY,el=$("#ptr");
  if(!el)return;
  if(dy>12&&window.scrollY<=0){el.hidden=false;el.dataset.ready=dy>70?"1":"0";el.textContent=dy>70?t("refresh.release"):t("refresh.pull")}
},{passive:true});
document.addEventListener("touchend",()=>{
  const el=$("#ptr");
  if(pulling&&el&&el.dataset.ready==="1")refreshAll();
  pulling=false;
  if(el){el.hidden=true;el.dataset.ready="0"}
},{passive:true});
setInterval(setSync,60000);
setInterval(pollStatus,5*60000);
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")pollStatus()});
if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
applyLang();render();loadMe();loadReports();
})();
