(function(){
'use strict';if(window.__MATCH_SIGNAL_WORKSPACE_UI__)return;window.__MATCH_SIGNAL_WORKSPACE_UI__=true;
const esc=v=>{const n=document.createElement('span');n.textContent=String(v??'');return n.innerHTML;};
const basePath=location.pathname.startsWith('/match-signal/')?'/match-signal':'';
const route=path=>basePath+path;
let host=document.getElementById('workspace-nav');
if(!host){
  const legacyHost=document.getElementById('msNav');
  if(legacyHost){host=document.createElement('div');host.id='workspace-nav';legacyHost.replaceWith(host);}
}
const pagePath=location.pathname.toLowerCase();
const inferredActive=pagePath.includes('/virtual-lab')?'lab':
  pagePath.endsWith('/reports.html')?'reports':
  pagePath.endsWith('/analyst.html')?'analyst':
  pagePath.endsWith('/football.html')?'football':
  pagePath.endsWith('/tennis.html')?'tennis':
  pagePath.endsWith('/live.html')?'live':
  pagePath.endsWith('/odds-builder.html')?'builder':
  pagePath.endsWith('/league.html')?(new URLSearchParams(location.search).get('sport')==='tennis'?'tennis':'football'):'desk';
const sharedCssUrl=route('/workspace-ui.css?v=20261011-workspace-media1');
const existingCss=document.querySelector('link[href*="workspace-ui.css"]');
if(existingCss)existingCss.href=sharedCssUrl;else{const l=document.createElement('link');l.rel='stylesheet';l.href=sharedCssUrl;document.head.appendChild(l);}
if(!document.getElementById('workspace-ui-polish')){
  const style=document.createElement('style');style.id='workspace-ui-polish';
  style.textContent='.ws-media-credit{max-width:1380px;margin:10px auto 16px;padding:8px 6px;color:var(--ws-muted);font-size:9px;line-height:1.5;opacity:.82}footer .ws-media-credit{margin:12px 0 0;padding:10px 0;border-top:1px solid #27374655}.ws-role-card{display:flex;flex-direction:column;gap:6px;min-height:130px}.ws-role-card strong{display:block;font-size:15px;line-height:1.25;color:var(--ws-text)}.ws-role-card p{margin:0;color:var(--ws-muted);font-size:11px;line-height:1.5}.ws-role-card a{margin-top:auto;color:var(--ws-cyan);font-size:10px;font-weight:900;text-decoration:none}.ws-role-card a:hover{text-decoration:underline}';
  document.head.appendChild(style);
}
if(host){
const active=host.dataset.active||inferredActive,links=[['Desk','/index.html','⌂','desk'],['Football','/football.html','⚽','football'],['Tennis','/tennis.html','🎾','tennis'],['Live','/live.html','◉','live'],['Reports','/reports.html','▥','reports'],['Odds Builder','/odds-builder.html','⇄','builder'],['Virtual Lab','/virtual-lab/','⚗','lab'],['AI Analyst','/analyst.html','✦','analyst']];
host.innerHTML='<nav class="ws-nav" aria-label="Match Signal workspaces"><a class="ws-brand" href="'+route('/index.html')+'" aria-label="Match Signal main desk"><span class="ws-brand-mark" aria-hidden="true"><svg viewBox="0 0 48 48" width="28" height="28" fill="none"><path d="M7 29a17 17 0 0 1 34 0" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"/><path d="M13 29a11 11 0 0 1 22 0M19 29a5 5 0 0 1 10 0" stroke="#42e59a" stroke-width="2.5" stroke-linecap="round"/><path d="M24 29 34 15" stroke="#eef7fb" stroke-width="3" stroke-linecap="round"/><circle cx="24" cy="29" r="3" fill="#37e7ff"/></svg></span><span><strong>MATCH SIGNAL</strong><small>Research &amp; intelligence</small></span></a><div class="ws-nav-right"><div class="ws-nav-links">'+links.map(([label,href,icon,key])=>'<a class="ws-nav-link '+(active===key?'active':'')+'" '+(active===key?'aria-current="page" ':'')+'href="'+route(href)+'"><span aria-hidden="true">'+icon+'</span>'+label+(key==='analyst'?'<span class="ws-private">PRIVATE</span>':'')+'</a>').join('')+'</div><span class="ws-nav-status"><i></i>PAPER / RESEARCH ONLY</span></div></nav>';
}
function clean(name,kind){let s=String(name||'').trim();if(kind==='team')s=s.replace(/\s*\([^()]+\)\s*$/,'').trim();return s;}
function norm(name,kind){let raw=clean(name,kind);if(kind==='player'&&raw.includes(',')){const parts=raw.split(',').map(x=>x.trim()).filter(Boolean);if(parts.length>1)raw=parts.slice(1).join(' ')+' '+parts[0];}let s=raw.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ');if(kind==='team')s=s.replace(/^(fc|afc|sc|ac|club)\s+/,'').replace(/\s+(football club|fc|cf|afc|sc|ac)$/,'').trim();return s;}
function initials(name){const w=clean(name,'team').split(/\s+/).filter(Boolean);return (w.length>1?w[0][0]+w[1][0]:(w[0]||'MS').slice(0,2)).toUpperCase();}
const cache=new Map(),entries=new Map(),queue=[];let busy=false;const prefix='match-signal-media-v1:';
function getCache(k){if(cache.has(k))return cache.get(k);try{const x=JSON.parse(localStorage.getItem(prefix+k)||'null');if(!x)return undefined;if(Date.now()-x.at>x.ttl){localStorage.removeItem(prefix+k);return undefined;}cache.set(k,x.url||null);return x.url||null;}catch(_){return undefined;}}
function saveCache(k,url,ttl){cache.set(k,url||null);try{localStorage.setItem(prefix+k,JSON.stringify({url:url||null,at:Date.now(),ttl:ttl||86400000}));}catch(_){}}
function srcFor(kind,row){const urls=kind==='team'?[row.strBadge,row.strTeamBadge,row.strLogo,row.strTeamLogo]:[row.strCutout,row.strThumb,row.strRender,row.strThumbCard];return urls.find(u=>typeof u==='string'&&/^https:\/\//i.test(u))||null;}
function exactRow(kind,name,data){const k=norm(name,kind),rows=kind==='team'?(data.teams||[]):(data.player||data.players||[]),fields=kind==='team'?['strTeam','strTeamShort','strTeamAlternate']:['strPlayer'];return rows.find(r=>fields.some(f=>r[f]&&norm(r[f],kind)===k&&srcFor(kind,r))&&(kind!=='player'||!r.strSport||/tennis/i.test(String(r.strSport))))||null;}
async function lookup(kind,name){const n=clean(name,kind),key=norm(n,kind);if(key.length<3)return null;const queryName=kind==='player'&&n.includes(',')?n.split(',').map(x=>x.trim()).slice(1).join(' ')+' '+n.split(',')[0].trim():n;const base=kind==='team'?'https://www.thesportsdb.com/api/v1/json/123/searchteams.php?t=':'https://www.thesportsdb.com/api/v1/json/123/searchplayers.php?p=';try{const r=await fetch(base+encodeURIComponent(queryName),{mode:'cors',credentials:'omit',cache:'force-cache'});if(!r.ok)throw Error();const data=await r.json(),row=exactRow(kind,n,data),url=row?srcFor(kind,row):null;saveCache(kind+':'+key,url,url?30*86400000:86400000);return url;}catch(_){saveCache(kind+':'+key,null,2*3600000);return null;}}
function paint(item,url){item.nodes.forEach(node=>{if(!node.isConnected)return;if(url){node.replaceChildren();const img=document.createElement('img');img.className='ws-media-image';img.alt='';img.loading='lazy';img.decoding='async';img.referrerPolicy='no-referrer';img.src=url;img.addEventListener('error',()=>{node.classList.remove('has-media');img.remove();node.textContent=initials(node.dataset.wsMediaName||'');},{once:true});node.appendChild(img);node.classList.add('has-media');}node.dataset.wsMediaResolved='true';});}
function enqueue(node){if(!node||node.dataset.wsMediaResolved==='true')return;const kind=node.dataset.wsMediaKind;if(!['team','player'].includes(kind))return;const name=clean(node.dataset.wsMediaName||'',kind),n=norm(name,kind);if(n.length<3){node.dataset.wsMediaResolved='true';return;}const k=kind+':'+n,cached=getCache(k);if(cached!==undefined){paint({nodes:[node]},cached);return;}if(entries.has(k)){entries.get(k).nodes.push(node);return;}const item={key:k,kind,name,nodes:[node]};entries.set(k,item);queue.push(item);drain();}
async function drain(){if(busy||!queue.length)return;busy=true;const item=queue.shift(),url=await lookup(item.kind,item.name);paint(item,url);busy=false;window.setTimeout(drain,2250);}
let io=null;function watch(node){if(node.dataset.wsMediaResolved==='true'||node.dataset.wsMediaObserved==='true')return;node.dataset.wsMediaObserved='true';if(io)io.observe(node);else enqueue(node);}
function scan(root){if(root?.matches?.('[data-ws-media-kind][data-ws-media-name]'))watch(root);root?.querySelectorAll?.('[data-ws-media-kind][data-ws-media-name]').forEach(watch);}
if('IntersectionObserver'in window)io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){io.unobserve(e.target);enqueue(e.target);}}),{rootMargin:'360px 0px'});
function mediaLabel(name,kind){
  const raw=String(name||'').trim()||'Unknown';
  const normalized=kind==='team'?raw.replace(/\s*\([^()]+\)\s*$/,'').trim():raw;
  const words=normalized.split(/\s+/).filter(Boolean);
  const initials=(words.length>1?words[0][0]+words[1][0]:(words[0]||'MS').slice(0,2)).toUpperCase();
  const label=document.createElement('span');label.className='ws-entity-label ws-fixture-team';
  const slot=document.createElement('span');slot.className='ws-media-slot';slot.dataset.wsMediaKind=kind;slot.dataset.wsMediaName=raw;slot.setAttribute('aria-hidden','true');slot.textContent=initials;
  const textNode=document.createElement('span');textNode.className='ws-entity-name';textNode.textContent=raw;
  label.append(slot,textNode);return label;
}
function decorateVirtualFixtureCards(root){
  const rows=[];
  if(root?.matches?.('.liveCard .liveTeams'))rows.push(root);
  root?.querySelectorAll?.('.liveCard .liveTeams').forEach(n=>rows.push(n));
  rows.forEach(container=>{
    if(container.dataset.wsMediaDecorated==='true')return;
    const children=Array.from(container.children);
    const sides=children.filter(n=>n.tagName==='STRONG'&&!n.closest('.participantIdentityLine')).slice(0,2);
    if(sides.length<2)return;
    const vs=children.find(n=>n.tagName==='SPAN'&&n.textContent.trim().toLowerCase()==='vs');
    const row=document.createElement('div');row.className='ws-live-fixture-row';
    row.append(mediaLabel(sides[0].textContent,'team'));
    const label=document.createElement('span');label.className='ws-live-fixture-vs';label.textContent='VS';row.append(label);
    row.append(mediaLabel(sides[1].textContent,'team'));
    sides.forEach(n=>n.remove());if(vs)vs.remove();
    container.prepend(row);container.dataset.wsMediaDecorated='true';
  });
}
decorateVirtualFixtureCards(document);scan(document);
new MutationObserver(rs=>rs.forEach(r=>r.addedNodes.forEach(n=>{if(n.nodeType===1){decorateVirtualFixtureCards(n);scan(n);}}))).observe(document.documentElement,{childList:true,subtree:true});
function ageLabel(v){const t=Date.parse(v||'');if(!Number.isFinite(t))return 'timestamp unavailable';const m=Math.max(0,Math.round((Date.now()-t)/60000));return m<60?m+'m ago':(m/60).toFixed(1)+'h ago';}
function ageM(v){const t=Date.parse(v||'');return Number.isFinite(t)?Math.max(0,(Date.now()-t)/60000):Infinity;}
async function json(path){const r=await fetch(route(path)+'?v='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error();return r.json();}
function metric(a,b,c){return '<article class="ws-metric-card"><small>'+esc(a)+'</small><strong>'+esc(b)+'</strong><p>'+esc(c)+'</p></article>';}
function badge(a,c){return '<span class="ws-status-badge '+c+'">'+esc(a)+'</span>';}
async function reportSummary(){
const target=document.getElementById('researchLabSummary');if(!target)return;
target.innerHTML='<div class="ws-overview-head"><div><div class="ws-overview-eyebrow">Research &amp; Intelligence</div><h3>Virtual Lab status</h3><p>Loading current published research artifacts…</p></div></div>';
const result=await Promise.allSettled([json('/data/virtual_lab_status.json'),json('/data/virtual_lab_model_eval.json'),json('/data/virtual_lab_eligibility.json'),json('/data/system_health.json'),json('/data/efootball_market_research.json')]);
const d=result.map(x=>x.status==='fulfilled'?x.value:null),s=d[0]||{},e=d[1]||{},g=d[2]||{},h=d[3]||{},a=d[4]||{};
const stale=ageM(s.updated_at)>60||ageM(e.generated_at)>90||ageM(g.generated_at)>90||!s.updated_at||!e.generated_at||!g.generated_at,hold=e.holdout_metrics||{},po=hold.poisson||{},mb=hold.market||{},summary=a.summary?.summary_by_product_market||{};
const lanes=[['GT Match Winner',summary['efootball_gt|match_winner']],['GT GG / NG',summary['efootball_gt|btts']],['Adriatic Winner',summary['efootball_adriatic|match_winner']]],captured=lanes.reduce((n,x)=>n+Number(x[1]?.captured||0),0),settled=lanes.reduce((n,x)=>n+Number(x[1]?.settled||0),0),pending=lanes.reduce((n,x)=>n+Number(x[1]?.pending||0),0);
const marketCards=lanes.map(([name,x])=>!x?'<article class="ws-market-card"><h5>'+esc(name)+'</h5><p>Market archive unavailable.</p></article>':'<article class="ws-market-card"><h5>'+esc(name)+'</h5><div class="ws-market-stats"><div><small>Settled</small><strong>'+Number(x.settled||0)+'</strong></div><div><small>Pending</small><strong>'+Number(x.pending||0)+'</strong></div><div><small>Fav ROI</small><strong>'+(Number.isFinite(Number(x.favourite_flat_stake_roi))?(Number(x.favourite_flat_stake_roi)*100).toFixed(1)+'%':'—')+'</strong></div></div></article>').join('');
target.innerHTML='<div class="ws-overview-head"><div><div class="ws-overview-eyebrow">Research &amp; Intelligence</div><h3>Virtual Lab status</h3><p>The Lab investigates candidate signals; Reports measures published evidence; the private Analyst explains system state and ticket records.</p></div><div class="ws-overview-actions"><button type="button" class="ws-action" id="wsReloadResearch">↻ Refresh status</button><a class="ws-action" href="'+route('/virtual-lab/')+'">Open Virtual Lab →</a><a class="ws-action" href="'+route('/analyst.html')+'">Open private Analyst →</a></div></div>'+
'<div class="ws-overview-grid">'+metric('Upcoming lab events',s.upcoming_events!=null?Number(s.upcoming_events).toLocaleString():'—','Status · '+ageLabel(s.updated_at))+metric('Settled O/U history',s.settled_observations!=null?Number(s.settled_observations).toLocaleString():'—','Historical observations · '+ageLabel(s.updated_at))+metric('Walk-forward holdout',e.holdout?.events!=null?Number(e.holdout.events).toLocaleString():'—','Events · evaluation '+ageLabel(e.generated_at))+metric('Alternative eFootball markets',settled+' settled','Across '+captured+' captured · '+pending+' pending')+'</div>'+
'<div class="ws-section-title"><h4>Virtual Lab · O/U model validation</h4><span>'+(stale?badge('LAB ARTIFACTS STALE','warn'):badge('LAB ARTIFACTS FRESH','good'))+' '+badge('MODE: '+String(g.mode||'UNKNOWN'),g.mode==='PAPER_RESEARCH_ONLY'?'good':'warn')+'</span></div>'+
'<div class="ws-market-grid"><article class="ws-market-card"><h5>Poisson · chronological holdout</h5><div class="ws-market-stats"><div><small>Brier</small><strong>'+(po.brier!=null?Number(po.brier).toFixed(4):'—')+'</strong></div><div><small>Log loss</small><strong>'+(po.log_loss!=null?Number(po.log_loss).toFixed(4):'—')+'</strong></div><div><small>Holdout rows</small><strong>'+Number(po.n||e.holdout?.rows||0).toLocaleString()+'</strong></div></div></article><article class="ws-market-card"><h5>SportyBet · market baseline</h5><div class="ws-market-stats"><div><small>Brier</small><strong>'+(mb.brier!=null?Number(mb.brier).toFixed(4):'—')+'</strong></div><div><small>Log loss</small><strong>'+(mb.log_loss!=null?Number(mb.log_loss).toFixed(4):'—')+'</strong></div><div><small>Artifact age</small><strong>'+esc(ageLabel(e.generated_at))+'</strong></div></div></article><article class="ws-market-card"><h5>System dependencies</h5><div class="ws-market-stats"><div><small>Health</small><strong>'+esc(h.status||'UNKNOWN')+'</strong></div><div><small>Critical</small><strong>'+Number(h.critical_issues||0)+'</strong></div><div><small>Warnings</small><strong>'+Number(h.warning_issues||0)+'</strong></div></div></article></div>'+
'<div class="ws-section-title"><h4>Experimental eFootball side markets</h4><span>Separate archive · not active Lab eligibility</span></div><div class="ws-market-grid">'+marketCards+'</div>'+
'<p class="ws-overview-note"><strong>Promotion boundary:</strong> Winner and GG/NG figures are descriptive bookmaker-favourite baselines, not independent Match Signal model outcomes. Lab eligibility remains '+esc((g.policy?.eligible_markets||[]).join(', ')||'unavailable')+' only; automatic promotion is disabled. System health reports '+esc(h.status||'UNKNOWN')+'.</p>';
const button=document.getElementById('wsReloadResearch');if(button)button.addEventListener('click',reportSummary,{once:true});
}
function ensureMediaAttribution(){
  if(document.querySelector('.ws-media-credit'))return;
  const note=document.createElement('p');
  note.className='ws-media-credit';
  note.textContent='Club crests and real-player headshots are resolved through TheSportsDB only when the team/player name matches exactly. Ambiguous or missing artwork stays as initials; eFootball gamer handles are not presented as real-person photos. Team marks and photos remain with their respective rights holders.';
  const footer=document.querySelector('footer');
  if(footer)footer.appendChild(note);
  else if(host)host.insertAdjacentElement('afterend',note);
}
ensureMediaAttribution();
reportSummary();
})();