(function () {
  'use strict';
  function esc(v) { var d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; }
  function pct(v) { var n = Number(v); return isFinite(n) ? (n * 100).toFixed(1) + '%' : '—'; }
  function dateOf(v) { var d = v ? new Date(v) : null; return d && !isNaN(d.getTime()) ? d : null; }
  function settlement(l) {
    if (!l || typeof l !== 'object') return null;
    var correct = l.correct;
    if (correct == null) correct = l.result_correct;
    if (correct == null && l.result && typeof l.result === 'object') correct = l.result.correct;
    if (correct == null && l.settlement && typeof l.settlement === 'object') correct = l.settlement.correct;
    if (correct === true || correct === false) return {finished:true, correct:!!correct};
    if (l.settled === true || l.final === true || l.status === 'FINAL' || l.status === 'ENDED') return {finished:true, correct:null};
    return null;
  }
  var liveStates = {};
  function liveStatus(l) {
    if (!l || String(l.sport || '').toLowerCase() !== 'tennis' || !l.event_id) return null;
    var x = liveStates[String(l.event_id)];
    if (!x) return null;
    if (x.state === 'in') return {live:true, start:x.start_time || null};
    if (x.state === 'post' || x.finished) return {finished:true, start:x.start_time || null};
    return null;
  }
  function state(v, l) {
    var settled = settlement(l);
    if (settled && settled.finished) {
      if (settled.correct === true) return {label:'Final', text:'✓ WON', cls:'finished-correct'};
      if (settled.correct === false) return {label:'Final', text:'✕ LOST', cls:'finished-wrong'};
      return {label:'Final', text:'ENDED', cls:'finished'};
    }
    var live = liveStatus(l);
    if (live && live.finished) return {label:'Final', text:'ENDED', cls:'finished'};
    var liveStart = live && live.live && live.start ? dateOf(live.start) : null;
    var d = liveStart || dateOf(v); if (!d) return { label:'Status', text:'Start time unavailable', cls:'unknown' };
    if (live && live.live) {
      var liveElapsed=Math.max(0,Math.floor((Date.now()-d.getTime())/1000)),leh=Math.floor(liveElapsed/3600),lem=Math.floor((liveElapsed%3600)/60),les=liveElapsed%60;
      return {label:'Live play',text:'LIVE · '+String(leh).padStart(2,'0')+'h '+String(lem).padStart(2,'0')+'m '+String(les).padStart(2,'0')+'s',cls:'live'};
    }
    var diff = d.getTime() - Date.now();
    if (diff > 0) {
      var total=Math.floor(diff/1000),days=Math.floor(total/86400); total%=86400; var h=Math.floor(total/3600); total%=3600; var m=Math.floor(total/60); var s=total%60;
      return {label:'Starts in',text:days?days+'d '+String(h).padStart(2,'0')+'h '+String(m).padStart(2,'0')+'m':String(h).padStart(2,'0')+'h '+String(m).padStart(2,'0')+'m '+String(s).padStart(2,'0')+'s',cls:diff<=900000?'soon':'upcoming'};
    }
    var e=Math.floor((Date.now()-d.getTime())/1000),eh=Math.floor(e/3600),em=Math.floor((e%3600)/60),es=e%60;
    return {label:'Live play',text:'LIVE · '+String(eh).padStart(2,'0')+'h '+String(em).padStart(2,'0')+'m '+String(es).padStart(2,'0')+'s',cls:'live'};
  }
  function refreshLiveStatuses(legs) {
    var ts=(Array.isArray(legs)?legs:[]).filter(function(l){return String(l.sport||'').toLowerCase()==='tennis' && l.event_id;});
    return Promise.all(ts.map(function(l){
      var tours=['wta','atp'];
      function findTour(i){
        if(i>=tours.length)return Promise.resolve();
        var url='./api/espn?path='+encodeURIComponent('/apis/site/v2/sports/tennis/'+tours[i]+'/scoreboard')+'&_='+Date.now();
        return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('tennis scoreboard HTTP '+r.status);return r.json();}).then(function(data){
          var found=null;
          (data.events||[]).some(function(e){if(String(e.id)===String(l.event_id)){found=e;return true;}return false;});
          if(found){var st=found.status||{},typ=st.type||{};liveStates[String(l.event_id)]={state:typ.state,start_time:found.date||found.competitions?.[0]?.startDate||l.start_time,finished:typ.completed===true||typ.state==='post'};return;}
          return findTour(i+1);
        });
      }
      return findTour(0).catch(function(){});
    }));
  }
  function local(v) { var d=dateOf(v); return d?d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—'; }
  function timer(v, l) { var c=state(v, l); return '<div class="timer '+c.cls+'" data-start="'+esc(v||'')+'" data-correct="'+(c.cls==='finished-correct'?'1':c.cls==='finished-wrong'?'0':'')+'" data-finished="'+(c.cls.indexOf('finished')===0?'1':'')+'"><span class="timerLabel">'+esc(c.label)+'</span><strong class="timerValue">'+esc(c.text)+'</strong></div>'; }
  function updateTimers() {
    document.querySelectorAll('#oddsBuilder .timer[data-start]').forEach(function(el){ if(el.getAttribute('data-finished')==='1') return; var c=state(el.getAttribute('data-start'), {sport:'tennis', event_id:el.getAttribute('data-event-id')}); el.className='timer '+c.cls; var a=el.querySelector('.timerLabel'),b=el.querySelector('.timerValue'); if(a)a.textContent=c.label; if(b)b.textContent=c.text; });
  }
  function render(data) {
    var target=document.getElementById('oddsBuilder'); if(!target)return;
    var legs=Array.isArray(data.qualified_legs)?data.qualified_legs:[],sports=[];
    legs.forEach(function(l){var s=String(l.sport||'').toUpperCase();if(s&&sports.indexOf(s)<0)sports.push(s);});
    var cards=legs.map(function(l,i){var settled=settlement(l);return '<article class="card"><div class="meta"><span>Leg '+(i+1)+' · '+esc(String(l.sport||'').toUpperCase())+' · '+esc(l.competition||'—')+'</span><span>Fair odds '+esc(l.model_fair_odds==null?'—':l.model_fair_odds)+'</span></div><div class="teams">'+esc(l.match||'—')+'</div><div class="pick">Selection: <b>'+esc(l.pick||'—')+'</b><span class="conf">Model '+pct(l.model_probability)+'</span></div>'+timer(l.start_time,l)+'<div class="startTime">Start: '+esc(local(l.start_time))+' <span>· your browser time</span></div><div class="section"><div class="row"><span>Market</span><b>'+esc(l.market||'—')+'</b></div><div class="row"><span>Model fair odds</span><b>'+esc(l.model_fair_odds==null?'—':l.model_fair_odds)+'</b></div><div class="row"><span>Bookmaker odds</span><b>Verify manually</b></div></div></article>';}).join('');
    var status=data.status==='QUALIFIED_ACCUMULATOR'?'READY FOR MANUAL BUILD':(data.status||'—');
    target.innerHTML='<div class="metrics"><div class="metric"><small>Qualified legs</small><strong>'+legs.length+'/4</strong></div><div class="metric"><small>Sports</small><strong>'+esc(sports.length?sports.join(' + '):'—')+'</strong></div><div class="metric"><small>Status</small><strong>'+esc(status)+'</strong></div><div class="metric"><small>Reference combined odds</small><strong>'+esc(data.reference_combined_odds==null?'—':data.reference_combined_odds)+'</strong></div></div><div class="panel"><b>Manual 3–4 Selection Accumulator · Football + Tennis</b><div class="sub">Research-qualified selections only. Confirm current bookmaker prices yourself before placing an accumulator.</div><div class="grid" style="margin-top:14px">'+(cards||'<div class="empty">No 3–4 selection set currently qualifies. The system will not force an accumulator.</div>')+'</div><div class="section"><div class="row"><span>Bookmaker feed</span><b>Manual confirmation required</b></div><div class="row"><span>Reference combined odds</span><b>'+esc(data.reference_combined_odds==null?'—':data.reference_combined_odds)+'</b></div></div></div>';
    updateTimers();
  }
  function load(){var target=document.getElementById('oddsBuilder');if(!target)return;target.innerHTML='<div class="empty">Loading Odds Builder data…</div>';fetch('./data/odds_builder.json?v=20260916-odds-final-'+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('odds_builder.json HTTP '+r.status);return r.json();}).then(function(data){var legs=Array.isArray(data.qualified_legs)?data.qualified_legs:[];return refreshLiveStatuses(legs).then(function(){render(data);});}).catch(function(e){target.innerHTML='<div class="empty">Accumulator data unavailable: '+esc(e.message)+'</div>';});}
  function boot(){
    if(!document.getElementById('odds-builder-result-style')){
      var s=document.createElement('style');s.id='odds-builder-result-style';s.textContent='.timer.finished-correct{border-color:#35d49a;background:#06251a}.timer.finished-correct .timerValue{color:#35d49a}.timer.finished-wrong{border-color:#ff7474;background:#2a0d12}.timer.finished-wrong .timerValue{color:#ff7474}.timer.finished{border-color:#8f98b8}.timer.finished .timerValue{color:#eef1fb}';document.head.appendChild(s);
    }
    load();window.setInterval(load,60000);window.setInterval(updateTimers,1000);}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}());
