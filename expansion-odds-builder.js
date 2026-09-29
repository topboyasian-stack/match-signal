/* Settled result cards: persistent WON/LOST history, never reverted by timer. */
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
  var virtualLiveStates = {};
  var bookingMemory = {};
  var virtualLiveBusy = false;

  function virtualStatusType(status, liveFlag) {
    var s=String(status||'').toLowerCase();
    if(liveFlag || /live|running|playing|in play|started/.test(s)) return 'live';
    if(/finish|ended|final|completed|settled|closed/.test(s)) return 'finished';
    return 'upcoming';
  }

  function refreshVirtualLiveStatuses(legs) {
    var targets={};
    (Array.isArray(legs)?legs:[]).forEach(function(l){
      var product=String(l&&l.product||'').toLowerCase();
      if(l&&l.event_id&&(product==='vfootball'||product==='efootball_gt'||product==='efootball_adriatic'||product==='zoom'))targets[String(l.event_id)]=true;
    });
    if(!Object.keys(targets).length||virtualLiveBusy)return Promise.resolve();
    virtualLiveBusy=true;
    return fetch('./api/sportybet-virtual?sources=efootball,vfootball&pageSize=100&pageNum=1&timeline=24&_='+Date.now(),{cache:'no-store'})
      .then(function(r){if(!r.ok)throw new Error('virtual live HTTP '+r.status);return r.json();})
      .then(function(data){
        var events=Array.isArray(data&&data.events)?data.events:[];
        events.forEach(function(e){
          var id=String(e&&e.event_id||'');if(!targets[id])return;
          var startMs=Number(e&&e.start_time_ms||0);if(startMs>0&&startMs<100000000000)startMs*=1000;
          var type=virtualStatusType(e&&e.match_status,e&&e.live===true);
          virtualLiveStates[id]={type:type,live:(e&&e.live===true)||type==='live',finished:type==='finished',status:String(e&&e.match_status||''),start_time:startMs||null,score:e&&e.score||null};
        });
      }).catch(function(){}).finally(function(){virtualLiveBusy=false;});
  }

  function formatElapsed(startMs){
    if(!startMs)return '';
    var total=Math.max(0,Math.floor((Date.now()-startMs)/1000)),h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60;
    return (h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
  }
  function formatCountdown(startMs){
    if(!startMs)return '—';
    var total=Math.max(0,Math.floor((startMs-Date.now())/1000)),d=Math.floor(total/86400);total%=86400;
    var h=Math.floor(total/3600);total%=3600;var m=Math.floor(total/60),s=total%60;
    return (d?d+'d ':'')+String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
  }
  function scoreText(score){
    if(!score)return 'Score feed unavailable';
    if(score.text)return String(score.text);
    return String(score.home==null?'—':score.home)+' - '+String(score.away==null?'—':score.away);
  }
  function liveTrackerHtml(l){
    var id=esc(l&&l.event_id||''),start=esc(l&&l.start_time||'');
    return '<div class="live-tracker" data-event-id="'+id+'" data-start="'+start+'"><span class="live-tracker-label">GAME TRACKER</span><strong class="live-tracker-main">Loading live status…</strong><span class="live-tracker-sub">Start '+esc(local(l&&l.start_time))+'</span></div>';
  }
  function updateLiveTrackers(){
    document.querySelectorAll('#oddsBuilder .live-tracker[data-event-id]').forEach(function(el){
      var id=el.getAttribute('data-event-id')||'',startRaw=el.getAttribute('data-start')||'',start=dateOf(startRaw),state=virtualLiveStates[id]||null;
      var startMs=start?start.getTime():null,main=el.querySelector('.live-tracker-main'),sub=el.querySelector('.live-tracker-sub'),label=el.querySelector('.live-tracker-label');
      if(!main)return;
      var type=state&&state.type,text='',detail='';
      el.classList.remove('is-live','is-finished','is-upcoming','is-waiting');
      if(state&&state.finished){
        text='FINISHED'+(state.score?' · '+scoreText(state.score):'');detail=state.status||'Final result feed received';el.classList.add('is-finished');
      }else if(state&&(state.live||type==='live')){
        text='LIVE · '+formatElapsed(state.start_time||startMs)+(state.score?' · '+scoreText(state.score):'');detail=state.status||'Live feed active';el.classList.add('is-live');
      }else if(startMs&&startMs>Date.now()){
        text='STARTS IN · '+formatCountdown(startMs);detail='Scheduled '+local(startRaw);el.classList.add('is-upcoming');
      }else if(state){
        text='STARTED · AWAITING LIVE FEED';detail=state.status||'Waiting for live score update';el.classList.add('is-waiting');
      }else{
        text='STARTING / LIVE FEED CHECK';detail=startMs?'Scheduled '+local(startRaw):'Start time unavailable';el.classList.add('is-waiting');
      }
      if(label)label.textContent=state&&state.live?'LIVE TRACKER':'GAME TRACKER';
      main.textContent=text;if(sub)sub.textContent=detail;
    });
  }

  function bookingFingerprint(batch) {
    var legs=Array.isArray(batch&&batch.legs)?batch.legs:[];
    return legs.map(function(l){
      return [String(l.event_id||''),String(l.market||''),l.line==null?'':String(l.line),String(l.pick||'')].join('|');
    }).join('||');
  }
  function bookingHash(value) {
    var s=String(value||''),h=2166136261;
    for(var i=0;i<s.length;i++){h^=s.charCodeAt(i);h+=((h<<1)+(h<<4)+(h<<7)+(h<<8)+(h<<24));}
    return ('00000000'+(h>>>0).toString(16)).slice(-8);
  }
  function bookingKey(batch) {
    return 'match-signal:sportybet-booking:'+String(batch&&batch.batch_id||'')+':'+bookingHash(bookingFingerprint(batch));
  }
  function readBookingState(batch) {
    var key=bookingKey(batch);
    if(bookingMemory[key])return bookingMemory[key];
    try {
      var raw=localStorage.getItem(key);
      if(raw){
        var parsed=JSON.parse(raw);
        if(parsed&&typeof parsed==='object'){bookingMemory[key]=parsed;return parsed;}
      }
    } catch(e) {}
    return null;
  }
  function writeBookingState(batch,state) {
    var key=bookingKey(batch),value=state||{};
    bookingMemory[key]=value;
    try{localStorage.setItem(key,JSON.stringify(value));}catch(e){}
    return value;
  }
  function bookingStillValid(state) {
    if(!state||!state.booking_code)return false;
    var expiry=state.expires_at?dateOf(state.expires_at):null;
    if(expiry)return expiry.getTime()>Date.now()+15000;
    var created=state.generated_at?dateOf(state.generated_at):null;
    return !!created && (created.getTime()+10*60*1000)>Date.now();
  }
  function bookingEligibility(batch) {
    var legs=Array.isArray(batch&&batch.legs)?batch.legs:[];
    var now=Date.now(),started=0,upcoming=0;
    legs.forEach(function(l){
      var d=dateOf(l&&l.start_time);
      if(d&&d.getTime()<=now)started++;else upcoming++;
    });
    return {started:started,upcoming:upcoming,total:legs.length};
  }

  function bookingPanelHtml(batch) {
    var state=readBookingState(batch);
    var eligibility=bookingEligibility(batch);
    
    var status=state&&state.error?'error':(state&&state.booking_code&&bookingStillValid(state)?(state.partial?'partial':'ready'):'loading');
    var code=state&&state.booking_code?state.booking_code:'';
    var expiry=state&&state.expires_at?dateOf(state.expires_at):null;
    var text=state&&state.error?String(state.error)
      :(status==='partial'
        ? 'Partial code: '+String(state.selection_count||0)+' of '+String(state.initial_selection_count||eligibility.total)+' selections remain'+(state.combined_odds?' · '+Number(state.combined_odds).toFixed(3)+'x current odds':'')+'.'
        :(status==='ready'
          ? 'Copy the code, open SportyBet, and confirm the live slip before placing it.'
          :'Preparing a live SportyBet booking code; started, suspended or changed legs will be excluded automatically.'));
    var id=esc(String(batch&&batch.batch_id||'').replace(/[^A-Za-z0-9_-]/g,''));
    var share=state&&state.share_url?String(state.share_url):'#';
    var openClass=code?'':' disabled';
    var openAttrs=code?'':' aria-disabled="true" tabindex="-1"';
    return '<div class="booking-panel" data-booking-panel="'+id+'">'+
      '<div class="booking-panel-head"><div><b>SportyBet Booking Code</b><div class="sub">Prepared from this exact Builder ticket. Match Signal only creates the betslip/share code; it does not stake or place the wager.</div></div>'+
      '<span class="booking-status '+status+'">'+(status==='ready'?'READY':status==='partial'?'PARTIAL':status==='error'?'REFRESH NEEDED':'PREPARING')+'</span></div>'+
      '<div class="booking-code-wrap"><code class="booking-code" data-booking-code>'+esc(code||'Waiting…')+'</code>'+
      '<div class="booking-actions"><button type="button" class="booking-btn primary" data-booking-copy="'+id+'" '+(code?'':'disabled')+'>Copy code</button>'+
      '<a class="booking-btn link'+openClass+'" data-booking-open="'+id+'" href="'+esc(share)+'" target="_blank" rel="noopener"'+openAttrs+'>Open SportyBet</a>'+
      '<button type="button" class="booking-btn" data-booking-refresh="'+id+'" '+(blocked?'disabled':'')+'>Refresh code</button></div></div>'+
      '<div class="booking-message">'+esc(text)+(expiry&&!blocked?' · Valid until '+esc(local(expiry.toISOString())):'')+'</div></div>';
  }
  function findBatchById(batchId) {
    var batches=window.__matchSignalOddsBuilderBatches||[];
    for(var i=0;i<batches.length;i++)if(String(batches[i]&&batches[i].batch_id||'')===String(batchId||''))return batches[i];
    return null;
  }
  function updateBookingPanel(batch,state) {
    var id=String(batch&&batch.batch_id||'').replace(/[^A-Za-z0-9_-]/g,'');
    var panel=document.querySelector('[data-booking-panel="'+id+'"]');
    if(!panel)return;
    var eligibility=bookingEligibility(batch);
    var live=state||readBookingState(batch)||{},ready=!!(live.booking_code&&bookingStillValid(live)),error=!!live.error,partial=ready&&live.partial===true;
    var statusEl=panel.querySelector('.booking-status'),codeEl=panel.querySelector('[data-booking-code]'),msgEl=panel.querySelector('.booking-message'),copy=panel.querySelector('[data-booking-copy]'),open=panel.querySelector('[data-booking-open]'),refresh=panel.querySelector('[data-booking-refresh]');
    if(statusEl){statusEl.className='booking-status '+(error?'error':ready?(partial?'partial':'ready'):'loading');statusEl.textContent=ready?(partial?'PARTIAL':'READY'):error?'REFRESH NEEDED':'PREPARING';}
    if(codeEl)codeEl.textContent=ready?live.booking_code:(error?'Unavailable':'Preparing…');
    if(copy)copy.disabled=!ready;
    if(refresh)refresh.disabled=false;
    if(open){open.classList.toggle('disabled',!ready);open.setAttribute('aria-disabled',ready?'false':'true');if(ready){open.removeAttribute('tabindex');open.href=live.share_url||('https://www.sportybet.com/ng/?c=ng&shareCode='+encodeURIComponent(live.booking_code));}else{open.href='#';open.setAttribute('tabindex','-1');}}
    if(msgEl){
      var msg=live.error;
      if(!msg){
        if(partial){
          msg='Partial booking code: '+String(live.selection_count||0)+' of '+String(live.initial_selection_count||eligibility.total)+' selections booked';
          if(live.combined_odds)msg+=' · '+Number(live.combined_odds).toFixed(3)+'x current combined odds';
          if(live.excluded_count)msg+=' · '+String(live.excluded_count)+' excluded';
        }else{
          msg=ready?'Copy the code, open SportyBet, and confirm the live slip before placing it.':'Preparing a live SportyBet booking code; unavailable selections are excluded automatically.';
        }
      }
      if(eligibility.started&&!error&&!partial)msg+=' · '+eligibility.started+' started leg(s) will be excluded if SportyBet has closed them.';
      var ex=live.expires_at?dateOf(live.expires_at):null;if(ex)msg+=' · Valid until '+local(ex.toISOString());msgEl.textContent=msg;
    }
  }
  function delay(ms){return new Promise(function(resolve){setTimeout(resolve,ms);});}
  function requestBookingCode(batch,force) {
    if(!batch||!batch.batch_id)return Promise.resolve();
    var current=readBookingState(batch);
    if(!force&&current&&bookingStillValid(current)){updateBookingPanel(batch,current);return Promise.resolve(current);}
    var loading={booking_code:'',generated_at:new Date().toISOString(),error:''};
    writeBookingState(batch,loading);updateBookingPanel(batch,loading);
    return fetch('./api/sportybet-booking',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({batch_id:batch.batch_id}),cache:'no-store'})
      .then(function(r){
        return r.text().then(function(text){
          var payload=null;
          try{payload=text?JSON.parse(text):null;}catch(_){}
          if(!payload){
            var raw=String(text||'').replace(/\s+/g,' ').slice(0,180);
            throw new Error('Booking API HTTP '+r.status+' returned a non-JSON response'+(raw?' · '+raw:''));
          }
          if(!r.ok||!payload.ok)throw new Error(String(payload&&payload.message||payload&&payload.error||('HTTP '+r.status)));
          var ready={booking_code:String(payload.booking_code||''),share_url:String(payload.share_url||''),expires_at:payload.expires_at||null,generated_at:new Date().toISOString(),initial_selection_count:Number(payload.initial_selection_count||0),requested_selection_count:Number(payload.requested_selection_count||0),selection_count:Number(payload.selection_count||0),excluded_count:Number(payload.excluded_count||0),unavailable_count:Number(payload.unavailable_count||0),partial:payload.partial===true,combined_odds:payload.combined_odds==null?null:Number(payload.combined_odds)};
          writeBookingState(batch,ready);updateBookingPanel(batch,ready);return ready;
        });
      })
      .catch(function(err){
        var failed={booking_code:'',generated_at:new Date().toISOString(),error:String(err&&err.message||err)};
        writeBookingState(batch,failed);updateBookingPanel(batch,failed);return failed;
      });
  }
  function ensureBookingCodes(batches) {
    var list=Array.isArray(batches)?batches:[];window.__matchSignalOddsBuilderBatches=list;
    var chain=Promise.resolve();
    list.forEach(function(batch){chain=chain.then(function(){return requestBookingCode(batch,false);}).then(function(){return delay(300);});});
    return chain;
  }
  function liveSettlement(l) {
    if (!l || !l.event_id) return null;
    var x = liveStates[String(l.event_id)];
    if (!x || !x.finished || !x.event) return null;
    var pick = String(l.pick || '').toLowerCase();
    var market = String(l.market || '').toLowerCase();
    if (market !== 'total_games') return null;
    var lineMatch = pick.match(/(?:over|under)\s+([0-9]+(?:\.[0-9]+)?)\s*$/i);
    if (!lineMatch) return null;
    var line = Number(lineMatch[1]);
    if (!isFinite(line)) return null;
    var side = /\bover\b/i.test(pick) ? 'over' : /\bunder\b/i.test(pick) ? 'under' : null;
    if (!side) return null;
    var comps = x.event.competitions && x.event.competitions[0] && x.event.competitions[0].competitors;
    if (!Array.isArray(comps) || comps.length < 2) return null;
    var totals = comps.map(function(c){
      var ls = Array.isArray(c.linescores) ? c.linescores : [];
      var vals = ls.map(function(s){ return Number(s && (s.value != null ? s.value : s.score)); }).filter(function(n){ return isFinite(n); });
      if (vals.length) return vals.reduce(function(a,b){return a+b;},0);
      var n = Number(c.score); return isFinite(n) ? n : null;
    });
    if (totals.some(function(n){return n == null;})) return null;
    var totalGames = totals[0] + totals[1];
    if (side === 'over') return {finished:true, correct:totalGames > line};
    return {finished:true, correct:totalGames < line};
  }
  function effectiveSettlement(l) { return settlement(l) || liveSettlement(l); }
  function liveStatus(l) {
    if (!l || String(l.sport || '').toLowerCase() !== 'tennis' || !l.event_id) return null;
    var x = liveStates[String(l.event_id)];
    if (!x) return null;
    if (x.state === 'in') return {live:true, start:x.start_time || null};
    if (x.state === 'post' || x.finished) return {finished:true, start:x.start_time || null};
    return null;
  }
  function state(v, l) {
    var settled = effectiveSettlement(l);
    if (settled && settled.finished) {
      if (settled.correct === true) return {label:'Final', text:'✓ WON', cls:'finished-correct'};
      if (settled.correct === false) return {label:'Final', text:'✕ LOST', cls:'finished-wrong'};
      return {label:'Final', text:'ENDED', cls:'finished'};
    }
    var live = liveStatus(l);
    if (live && live.finished) return {label:'Final', text:'ENDED', cls:'finished'};
    var liveStart = live && live.live && live.start ? dateOf(live.start) : null;
    var d = liveStart || dateOf(v);
    if (!d) return {label:'Status', text:'Start time unavailable', cls:'unknown'};
    if (live && live.live) {
      var liveElapsed=Math.max(0,Math.floor((Date.now()-d.getTime())/1000)),leh=Math.floor(liveElapsed/3600),lem=Math.floor((liveElapsed%3600)/60),les=liveElapsed%60;
      return {label:'Live play',text:'LIVE · '+String(leh).padStart(2,'0')+'h '+String(lem).padStart(2,'0')+'m '+String(les).padStart(2,'0')+'s',cls:'live'};
    }
    var diff = d.getTime() - Date.now();
    if (diff > 0) {
      var total=Math.floor(diff/1000),days=Math.floor(total/86400); total%=86400; var h=Math.floor(total/3600); total%=3600; var m=Math.floor(total/60); var s=total%60;
      return {label:'Starts in',text:days?days+'d '+String(h).padStart(2,'0')+'h '+String(m).padStart(2,'0')+'m':String(h).padStart(2,'0')+'h '+String(m).padStart(2,'0')+'m '+String(s).padStart(2,'0')+'s',cls:diff<=900000?'soon':'upcoming'};
    }
    return {label:'Status check',text:'AWAITING LIVE FEED',cls:'unknown'};
  }
  function refreshLiveStatuses(legs) {
    var ts=(Array.isArray(legs)?legs:[]).filter(function(l){return String(l.sport||'').toLowerCase()==='tennis' && l.event_id;});
    return Promise.all(ts.map(function(l){
      var tours=['wta','atp'];
      function acceptEvent(found, fallbackStart){
        if(!found)return false;
        var st=found.status||{},typ=st.type||{};
        liveStates[String(l.event_id)]={
          state:typ.state,
          start_time:found.date||found.competitions?.[0]?.startDate||fallbackStart||l.start_time,
          finished:typ.completed===true||typ.state==='post',
          event:found
        };
        return true;
      }
      function findSummary(i){
        if(i>=tours.length)return Promise.resolve(false);
        var url='./api/espn?path='+encodeURIComponent('/apis/site/v2/sports/tennis/'+tours[i]+'/summary')+'&event='+encodeURIComponent(String(l.event_id))+'&_='+Date.now();
        return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('tennis summary HTTP '+r.status);return r.json();}).then(function(data){
          var found=data.header && data.header.competitions && data.header.competitions[0];
          if(found && acceptEvent(found, l.start_time))return true;
          return findSummary(i+1);
        }).catch(function(){return findSummary(i+1);});
      }
      function findTour(i){
        if(i>=tours.length)return Promise.resolve();
        var url='./api/espn?path='+encodeURIComponent('/apis/site/v2/sports/tennis/'+tours[i]+'/scoreboard')+'&_='+Date.now();
        return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('tennis scoreboard HTTP '+r.status);return r.json();}).then(function(data){
          var found=null;
          (data.events||[]).some(function(e){if(String(e.id)===String(l.event_id)){found=e;return true;}return false;});
          if(found){ acceptEvent(found, l.start_time); return; }
          return findTour(i+1);
        });
      }
      return findSummary(0).then(function(found){ return found ? true : findTour(0); }).catch(function(){ return findTour(0); });
    }));
  }
  function local(v) { var d=dateOf(v); return d?d.toLocaleString([], {weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'—'; }
  function timer(v, l) {
    var c=state(v, l);
    return '<div class="timer '+c.cls+'" data-event-id="'+esc(l&&l.event_id||'')+'" data-start="'+esc(v||'')+'" data-sport="'+esc(l&&l.sport||'')+'" data-market="'+esc(l&&l.market||'')+'" data-pick="'+esc(l&&l.pick||'')+'" data-correct="'+(c.cls==='finished-correct'?'1':c.cls==='finished-wrong'?'0':'')+'" data-finished="'+(c.cls.indexOf('finished')===0?'1':'')+'"><span class="timerLabel">'+esc(c.label)+'</span><strong class="timerValue">'+esc(c.text)+'</strong></div>';
  }
  function updateTimers() {
    document.querySelectorAll('#oddsBuilder .timer[data-start]').forEach(function(el){
      if(el.getAttribute('data-finished')==='1') return;
      var l={sport:el.getAttribute('data-sport')||'',event_id:el.getAttribute('data-event-id')||'',market:el.getAttribute('data-market')||'',pick:el.getAttribute('data-pick')||''};
      var c=state(el.getAttribute('data-start'),l);
      el.className='timer '+c.cls;
      el.setAttribute('data-correct',c.cls==='finished-correct'?'1':c.cls==='finished-wrong'?'0':'');
      el.setAttribute('data-finished',c.cls.indexOf('finished')===0?'1':'');
      var a=el.querySelector('.timerLabel'),b=el.querySelector('.timerValue');
      if(a)a.textContent=c.label;
      if(b)b.textContent=c.text;
    });
    updateLiveTrackers();
  }
  function ticketTrackHtml(tracker) {
    var tickets=tracker&&Array.isArray(tracker.tickets)?tracker.tickets:[];
    var summary=tracker&&tracker.summary?tracker.summary:{};
    function esc2(v){return esc(v);}
    function n(v,d){var x=Number(v);return isFinite(x)?x:d;}
    function ticketLabel(t){
      if(t.status==='WON') return '<span class="ticket-status won">✓ WON</span>';
      if(t.status==='LOST') return '<span class="ticket-status lost">✕ LOST</span>';
      return '<span class="ticket-status pending">ONGOING</span>';
    }
    function legStatus(leg){
      var s=String(leg&&leg.status||'PENDING').toUpperCase();
      if(s==='WON') return '<span class="ticket-leg-state won">WON</span>';
      if(s==='LOST') return '<span class="ticket-leg-state lost">LOST</span>';
      if(s==='VOID') return '<span class="ticket-leg-state void">VOID</span>';
      return '<span class="ticket-leg-state pending">PENDING</span>';
    }
    function ticketLegs(t){
      var legs=Array.isArray(t.legs)?t.legs:[];
      return legs.map(function(leg,i){
        var status=String(leg.status||'PENDING').toUpperCase();
        var cls=status==='WON'?'won':status==='LOST'?'lost':status==='VOID'?'void':'pending';
        var result=leg.result||((status==='WON'||status==='LOST')?status:'Waiting for settlement');
        var settledAt=leg.settled_at?local(leg.settled_at):'';
        return '<div class="ticket-leg '+cls+'">'+
          '<div class="ticket-leg-index">LEG '+(i+1)+'</div>'+
          '<div class="ticket-leg-core"><strong>'+esc2(leg.match||'Unknown fixture')+'</strong><span>'+esc2(leg.pick||'—')+'</span><small>'+esc2(String(leg.market||'SportyBet market'))+(leg.bookmaker_odds!=null?' · SportyBet '+esc2(leg.bookmaker_odds):'')+'</small></div>'+
          '<div class="ticket-leg-result">'+legStatus(leg)+'<small>'+esc2(result)+(settledAt?' · '+esc2(settledAt):'')+'</small></div>'+
        '</div>';
      }).join('');
    }
    var tracked=Number(summary.tracked_tickets||tickets.length);
    var ongoing=Number(summary.pending||0),won=Number(summary.won||0),lost=Number(summary.lost||0);
    var cards=tickets.slice(0,20).map(function(t,idx){
      var lc=t.leg_counts||{}, total=Number(t.leg_count||((t.legs||[]).length))||0;
      var settled=Number(t.settled_leg_count!=null?t.settled_leg_count:(Number(lc.won||0)+Number(lc.lost||0)+Number(lc.void||0)));
      var pending=Number(t.pending_leg_count!=null?t.pending_leg_count:(lc.pending||0));
      var pctDone=total?Math.max(0,Math.min(100,(settled/total)*100)):0;
      var lostAndPending=t.status==='LOST'&&pending>0;
      var products=(Array.isArray(t.products)?t.products:[]).map(function(x){return String(x||'').toUpperCase();}).filter(Boolean).join(' · ')||'VIRTUAL';
      var created=t.created_at?local(t.created_at):'Unknown';
      var lastSettled=t.last_settled_at?local(t.last_settled_at):'No legs settled yet';
      var headline=(t.batch_id?esc2(t.batch_id)+' · ':'')+ticketLabel(t);
      return '<details class="ticket-card '+(t.status==='LOST'?'ticket-lost':t.status==='WON'?'ticket-won':'ticket-pending')+'" '+(idx===0?'open':'')+'>'+
        '<summary class="ticket-card-summary">'+
          '<div class="ticket-card-title"><span class="ticket-kicker">PAPER TICKET · '+esc2(t.ticket_id||'—')+'</span><strong>'+headline+'</strong><small>'+esc2(products)+' · Created '+esc2(created)+'</small></div>'+
          '<div class="ticket-card-odds"><strong>'+esc2(t.combined_odds==null?'—':Number(t.combined_odds).toFixed(3))+'x</strong><span>'+esc2(t.leg_count||total)+' legs</span></div>'+
        '</summary>'+
        '<div class="ticket-card-body">'+
          '<div class="ticket-card-metrics">'+
            '<div><small>Model rating</small><b>'+esc2(t.combined_model_rating==null?'—':Number(t.combined_model_rating).toFixed(1)+'/100')+'</b></div>'+
            '<div><small>Joint proxy</small><b>'+esc2(t.combined_model_probability==null?'—':pct(t.combined_model_probability))+'</b></div>'+
            '<div><small>Settled</small><b>'+esc2(settled)+' / '+esc2(total)+'</b></div>'+
            '<div><small>Pending</small><b>'+esc2(pending)+'</b></div>'+
          '</div>'+
          '<div class="ticket-progress-wrap">'+
            '<div class="ticket-progress-head"><span>Settlement progress</span><b>'+esc2(Math.round(pctDone))+'%</b></div>'+
            '<div class="ticket-progress-track"><i style="width:'+pctDone.toFixed(1)+'%"></i></div>'+
            '<div class="ticket-progress-legend"><span><b class="won-text">'+esc2(lc.won||0)+'</b> won</span><span><b class="lost-text">'+esc2(lc.lost||0)+'</b> lost</span><span><b>'+esc2(lc.void||0)+'</b> void</span><span><b>'+esc2(pending)+'</b> pending</span></div>'+
          '</div>'+
          '<div class="ticket-state-callout '+(t.status==='LOST'?'lost':t.status==='WON'?'won':'pending')+'">'+
            '<strong>'+headline+'</strong>'+
            '<span>'+(lostAndPending?'A loss has already settled this accumulator. Remaining legs continue to settle for the historical record.':t.status==='WON'?'Every leg is settled without a loss.':t.status==='LOST'?'The accumulator is settled as lost.':'Ticket is still awaiting final settlement.')+'</span>'+
          '</div>'+
          '<div class="ticket-meta-grid">'+
            '<div><small>Created</small><b>'+esc2(created)+'</b></div>'+
            '<div><small>Last settlement update</small><b>'+esc2(lastSettled)+'</b></div>'+
            '<div><small>Lane</small><b>'+esc2(products)+'</b></div>'+
            '<div><small>Mode</small><b>PAPER ONLY</b></div>'+
          '</div>'+
          '<div class="ticket-leg-list">'+ticketLegs(t)+'</div>'+
        '</div>'+
      '</details>';
    }).join('');
    if(!cards) cards='<div class="empty">No generated paper tickets have been tracked yet.</div>';
    return '<section class="ticket-track">'+
      '<div class="ticket-track-head"><div><span class="ticket-track-kicker">PAPER LEDGER</span><b>Paper Ticket Track</b><div class="sub">Every generated accumulator is preserved as its own immutable paper-ticket snapshot. Ticket status and leg settlement are tracked independently.</div></div>'+
      '<div class="ticket-track-stats">'+
        '<span><small>Tracked</small><b>'+esc2(tracked)+'</b></span>'+
        '<span class="ongoing"><small>Ongoing</small><b>'+esc2(ongoing)+'</b></span>'+
        '<span class="won"><small>Won</small><b>'+esc2(won)+'</b></span>'+
        '<span class="lost"><small>Lost</small><b>'+esc2(lost)+'</b></span>'+
      '</div></div>'+
      '<div class="ticket-list">'+cards+'</div>'+
    '</section>';
  }

  function render(data, tracker) {
    var target=document.getElementById('oddsBuilder'); if(!target)return;
    var batches=Array.isArray(data.batches)?data.batches:[];
    window.__matchSignalOddsBuilderBatches=batches;
    var settledLegs=Array.isArray(data.settled_legs)?data.settled_legs:[];
    var sports=[], batchCount=batches.length;
    batches.forEach(function(b){
      (Array.isArray(b.products)?b.products:[]).forEach(function(p){
        var s=String(p||'').toUpperCase();
        if(s&&sports.indexOf(s)<0)sports.push(s);
      });
      (Array.isArray(b.legs)?b.legs:[]).forEach(function(l){
        var s=String(l.product||l.sport||'').toUpperCase();
        if(s&&sports.indexOf(s)<0)sports.push(s);
      });
    });
    var top=batches.length?batches[0]:null;
    var topRating=top&&top.combined_model_rating!=null?Number(top.combined_model_rating):null;
    var topJoint=top&&top.combined_model_probability!=null?Number(top.combined_model_probability):null;
    var status=data.status==='LIVE_VALUE_SET'
      ? batchCount+' RESEARCH BATCH'+(batchCount===1?'':'ES')+' · 4.00+'
      : data.status==='BELOW_4_TARGET_AVAILABLE'
        ? 'BEST AVAILABLE SET BELOW 4.00'
        : data.status==='UPSTREAM_RESEARCH_GATE_BLOCKED'
          ? 'NO QUALIFIED BATCHES'
          : (data.status||'—');

    function legCard(l,i,batchIndex){
      var settled=effectiveSettlement(l),isSettled=!!(settled&&settled.finished);
      var resultText=settled&&settled.correct===true?'✓ WON':settled&&settled.correct===false?'✕ LOST':'ENDED';
      var product=String(l.product||l.sport||'virtual').toUpperCase();
      return '<article class="card '+(isSettled?'settled-card':'')+'"><div class="meta"><span>Leg '+(i+1)+' · '+esc(product)+' · '+esc(l.competition||'—')+'</span><span>'+(isSettled?'<b class="result-badge '+(settled.correct===true?'won':'lost')+'">'+resultText+'</b>':'SportyBet '+esc(l.bookmaker_odds==null?'—':l.bookmaker_odds))+'</span></div><div class="teams">'+esc(l.match||'—')+'</div><div class="pick">Selection: <b>'+esc(l.pick||'—')+'</b><span class="conf">Model '+pct(l.model_probability)+'</span></div>'+timer(l.start_time,l)+liveTrackerHtml(l)+'<div class="startTime">'+(isSettled?'Result confirmed · '+esc(local(l.start_time)):'Start: '+esc(local(l.start_time))+' <span>· your browser time</span>')+'</div><div class="section"><div class="row"><span>Market</span><b>'+esc(l.market||'—')+'</b></div><div class="row"><span>Model probability</span><b>'+pct(l.model_probability)+'</b></div><div class="row"><span>Model fair odds</span><b>'+esc(l.model_fair_odds==null?'—':l.model_fair_odds)+'</b></div><div class="row"><span>SportyBet price</span><b>'+esc(l.bookmaker_odds==null?'—':l.bookmaker_odds)+'</b></div><div class="row"><span>Model edge vs market</span><b>'+esc(l.model_edge==null?'—':pct(l.model_edge))+'</b></div><div class="row"><span>Market price age</span><b>'+esc(l.market_odds_age_seconds==null?'—':Math.round(Number(l.market_odds_age_seconds))+'s')+'</b></div><div class="row"><span>Result</span><b class="'+(isSettled?(settled.correct===true?'won-text':'lost-text'):'')+'">'+(isSettled?resultText:'Pending')+'</b></div></div></article>';
    }

    function batchCard(b,idx){
      var legs=Array.isArray(b.legs)?b.legs:[];
      var joint=b.combined_model_probability==null?'—':pct(b.combined_model_probability);
      var strength=b.leg_strength_rating==null?'—':Number(b.leg_strength_rating).toFixed(1)+'/100';
      var rating=b.combined_model_rating==null?'—':Number(b.combined_model_rating).toFixed(1)+'/100';
      var avgEdge=b.avg_model_edge_percent==null?'—':Number(b.avg_model_edge_percent).toFixed(1)+'%';
      var oddsText=b.combined_odds==null?'—':Number(b.combined_odds).toFixed(3);
      var products=(Array.isArray(b.products)?b.products:[])
        .map(function(x){return String(x||'').toUpperCase();})
        .filter(Boolean)
        .join(' + ') || 'VIRTUAL';
      var laneText=b.primary_lane==='vfootball'?'vFootball priority lane':'fallback virtual lane';
      var batchNum=String(idx+1).padStart(2,'0');
      var body=legs.map(function(l,i){return legCard(l,i,idx);}).join('');
      var bookingPanel=bookingPanelHtml(b);
      return [
        '<details class="batch-card">',
        '<summary class="batch-summary">',
        '<div><span class="batch-kicker">Batch '+batchNum+'</span>',
        '<strong>'+esc(products)+' · Combined Model Rating '+esc(rating)+'</strong>',
        '<small>'+esc(String(b.leg_count||legs.length)+' legs · '+avgEdge+' avg edge · '+laneText)+'</small></div>',
        '<div class="batch-odds">'+esc(oddsText)+'x</div>',
        '</summary>',
        '<div class="batch-metrics">',
        '<div><span>Combined model rating</span><b>'+esc(rating)+'</b></div>',
        '<div><span>Naive joint model probability</span><b>'+esc(joint)+'</b></div>',
        '<div><span>Leg-strength rating</span><b>'+esc(strength)+'</b></div>',
        '<div><span>Average model edge</span><b>'+esc(avgEdge)+'</b></div>',
        '<div><span>Combined SportyBet odds</span><b>'+esc(oddsText)+'</b></div>',
        '</div>',
        '<div class="sub">The joint probability is an independence proxy, not a guarantee of the whole ticket winning. Prices shown are the current SportyBet snapshot used by the Builder.</div>',
        bookingPanel,
        '<div class="grid" style="margin-top:14px">'+(body||'<div class="empty">No legs in this batch.</div>')+'</div>',
        '</details>'
      ].join('');
    }

    var cards=batches.map(batchCard).join('');
    if(!batches.length){
      var fallback=Array.isArray(data.qualified_legs)?data.qualified_legs:[];
      cards=fallback.map(function(l,i){return legCard(l,i,0);}).join('');
    }

    var gate=data.research_gate||{}, virtualCount=Number((data.candidates_considered||{}).virtual||0);
    var gateNote;
    if(batches.length){
      gateNote='<div class="section"><b>Research batch gate active</b><div class="sub">The Builder evaluates Virtual lanes independently of the core tennis gate. vFootball is the primary lane because its existing untouched O/U evidence is currently the strongest active research lane.</div><div class="row"><span>Qualified Virtual candidates</span><b>'+esc(virtualCount)+'</b></div><div class="row"><span>SportyBet price authority</span><b>Fresh Unified Snapshot</b></div></div>';
    } else if(virtualCount>0){
      gateNote='<div class="section warning"><b>Virtual lane evaluated, but no 4.00+ batch survived all gates</b><div class="sub">No weak selections are added just to reach 4.00.</div><div class="row"><span>Virtual candidates</span><b>'+esc(virtualCount)+'</b></div></div>';
    } else if(gate.upstream_blocked){
      gateNote='<div class="section warning"><b>No current batch available</b><div class="sub">The core prediction gate is separate from Virtual and was not allowed to manufacture a slip.</div></div>';
    } else {
      gateNote='<div class="section"><b>Research gate active</b><div class="sub">Only fresh SportyBet prices, calibrated edge and evidence gates can produce a batch.</div></div>';
    }

    var ticketTrack=ticketTrackHtml(tracker);
    target.innerHTML='<div class="builder-console"><div class="builder-console-head"><div><span class="builder-kicker">PAPER RESEARCH DESK</span><h3>Live 4.00+ Builder</h3><p>Fresh SportyBet prices are qualified in-process. Batches stay paper-only and disjoint by event.</p></div><div class="builder-live-state"><span class="pulse-dot"></span><b>'+(batchCount?'LIVE VALUE SET':'NO ACTIVE SET')+'</b><small>'+esc(status)+'</small></div></div><div class="builder-stat-row"><div class="builder-stat builder-stat-main"><small>Active batches</small><strong>'+batchCount+'/6</strong><span>Automatically refreshed</span></div><div class="builder-stat"><small>Sport lanes</small><strong>'+esc(sports.length?sports.join(' · '):'—')+'</strong><span>Current batch set</span></div><div class="builder-stat"><small>Top model rating</small><strong>'+esc(topRating==null?'—':topRating.toFixed(1)+'/100')+'</strong><span>Batch strength proxy</span></div><div class="builder-stat"><small>Top combined odds</small><strong>'+esc(top&&top.combined_odds!=null?Number(top.combined_odds).toFixed(3):'—')+'x</strong><span>SportyBet snapshot</span></div></div></div><div class="builder-batch-panel"><div class="builder-section-head"><div><span class="section-kicker">QUALIFIED SET</span><b>4.00+ paper research batches</b><span>Expand a batch for its booking code, live quote details, timer and legs.</span></div><div class="builder-section-note"><b>'+esc(virtualCount)+'</b><span>virtual candidates evaluated</span></div></div><div class="batch-list">'+(cards||'<div class="empty">No qualified 4.00+ batches are currently available.</div>')+'</div><div class="builder-feedbar"><span><b>SPORTYBET</b> live snapshot</span><span>Top joint proxy <b>'+esc(topJoint==null?'—':pct(topJoint))+'</b></span><span>Price freshness gate <b>&le; 15m</b></span><span>Paper only <b>Yes</b></span></div>'+gateNote+'</div>'+ticketTrack+'<div class="builder-note">The Builder refreshes automatically. Opening a batch reveals its exact selections and current SportyBet booking code.</div>';
    updateTimers();
  }
  function load(){
    var target=document.getElementById('oddsBuilder');if(!target)return;
    target.innerHTML='<div class="empty">Loading Odds Builder data…</div>';
    Promise.all([
      fetch('./data/odds_builder.json?v=20260929-odds-builder-'+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('odds_builder.json HTTP '+r.status);return r.json();}),
      fetch('./data/odds_ticket_tracker.json?v=20260929-ticket-track-'+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)return {tickets:[],summary:{}};return r.json();})
    ]).then(function(results){
      var data=results[0],tracker=results[1];
      var legs=Array.isArray(data.qualified_legs)?data.qualified_legs:[];
      return refreshLiveStatuses(legs).then(function(){return refreshVirtualLiveStatuses((data.batches||[]).reduce(function(all,b){return all.concat(Array.isArray(b.legs)?b.legs:[]);},[]));}).then(function(){render(data,tracker);}).then(function(){return ensureBookingCodes(Array.isArray(data.batches)?data.batches:[]);});
    }).catch(function(e){target.innerHTML='<div class="empty">Accumulator data unavailable: '+esc(e.message)+'</div>';});
  }
  function boot(){
    if(!document.getElementById('odds-builder-result-style')){
      var s=document.createElement('style');s.id='odds-builder-result-style';s.textContent='.batch-list{display:grid;gap:10px}\n.batch-card{border:1px solid rgba(130,150,180,.17);border-radius:15px;background:linear-gradient(145deg,rgba(20,31,47,.96),rgba(8,15,24,.98));overflow:hidden;transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease}\n.batch-card:hover{border-color:rgba(55,231,255,.28);box-shadow:0 12px 28px rgba(0,0,0,.18);transform:translateY(-1px)}\n.batch-summary{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 15px;cursor:pointer;list-style:none}\n.batch-summary::-webkit-details-marker{display:none}\n.batch-summary>div:first-child{min-width:0}\n.batch-kicker{display:inline-block;margin-bottom:4px;color:var(--ms-cyan);font-size:9px;font-weight:950;letter-spacing:.12em;text-transform:uppercase}\n.batch-summary strong{display:block;font-size:14px;line-height:1.25}\n.batch-summary small{display:block;margin-top:5px;color:var(--ms-muted);font-size:9px}\n.batch-odds{font-size:24px;font-weight:950;color:var(--ms-cyan);white-space:nowrap}\n.batch-odds:after{content:\" COMBINED\";display:block;color:var(--ms-muted);font-size:7px;letter-spacing:.1em;text-align:right}\n.batch-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;padding:0 15px 12px}\n.batch-metrics>div{padding:9px 10px;border:1px solid rgba(255,255,255,.06);border-radius:10px;background:rgba(255,255,255,.025)}\n.batch-metrics span{display:block;color:var(--ms-muted);font-size:8px;text-transform:uppercase;letter-spacing:.08em}\n.batch-metrics b{display:block;margin-top:4px;font-size:13px}\n.batch-card>.sub{padding:0 15px 11px;color:var(--ms-muted);font-size:9px;line-height:1.45}\n.batch-card>.grid{padding:0 15px 15px}\n.builder-console{margin-bottom:12px;padding:18px;border:1px solid rgba(55,231,255,.18);border-radius:18px;background:radial-gradient(circle at top right,rgba(55,231,255,.09),transparent 32%),linear-gradient(145deg,#0c1726,#07101a 75%);box-shadow:0 16px 40px rgba(0,0,0,.18)}\n.builder-console-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}\n.builder-kicker,.section-kicker{display:block;color:var(--ms-cyan);font-size:8px;font-weight:950;letter-spacing:.15em;text-transform:uppercase}\n.builder-console h3{margin:4px 0 0;font-size:20px;letter-spacing:-.02em}\n.builder-console p{margin:6px 0 0;color:var(--ms-muted);font-size:10px;line-height:1.5;max-width:650px}\n.builder-live-state{min-width:170px;padding:9px 11px;border:1px solid rgba(53,212,154,.2);border-radius:12px;background:rgba(53,212,154,.045);text-align:right}\n.pulse-dot{display:inline-block;width:7px;height:7px;margin-right:6px;border-radius:50%;background:#35d49a;box-shadow:0 0 0 4px rgba(53,212,154,.09);vertical-align:middle}\n.builder-live-state b{font-size:9px;letter-spacing:.08em}\n.builder-live-state small{display:block;margin-top:4px;color:var(--ms-muted);font-size:8px}\n.builder-stat-row{display:grid;grid-template-columns:1.1fr 1fr 1fr 1fr;gap:8px;margin-top:14px}\n.builder-stat{padding:11px 12px;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.025)}\n.builder-stat small{display:block;color:var(--ms-muted);font-size:8px;text-transform:uppercase;letter-spacing:.09em}\n.builder-stat strong{display:block;margin-top:5px;font-size:17px;overflow-wrap:anywhere}\n.builder-stat span{display:block;margin-top:3px;color:var(--ms-muted);font-size:8px}\n.builder-stat-main strong{color:var(--ms-cyan);font-size:22px}\n.builder-batch-panel{padding:17px;border:1px solid rgba(130,150,180,.13);border-radius:18px;background:linear-gradient(180deg,rgba(11,18,28,.98),rgba(7,12,19,.98))}\n.builder-section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:10px}\n.builder-section-head b{display:block;margin-top:4px;font-size:14px}\n.builder-section-head span{display:block;margin-top:4px;color:var(--ms-muted);font-size:9px}\n.builder-section-note{min-width:130px;text-align:right}\n.builder-section-note b{font-size:17px;color:var(--ms-cyan)}\n.builder-section-note span{font-size:8px}\n.builder-feedbar{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px;padding-top:11px;border-top:1px solid rgba(255,255,255,.06)}\n.builder-feedbar span{padding:6px 8px;border:1px solid rgba(255,255,255,.06);border-radius:999px;background:rgba(255,255,255,.025);color:var(--ms-muted);font-size:8px}\n.builder-feedbar b{color:var(--ms-text)}\n.builder-note{margin-top:8px;padding:8px 10px;color:var(--ms-muted);font-size:8px;text-align:center}\n.live-tracker{margin-top:8px;padding:8px 10px;border-radius:10px;border:1px solid rgba(130,150,180,.12);background:rgba(255,255,255,.018)}\n.live-tracker-label{display:block;color:var(--ms-muted);font-size:7px;font-weight:950;letter-spacing:.11em}.live-tracker-main{display:block;margin-top:3px;font-size:10px;line-height:1.3}.live-tracker-sub{display:block;margin-top:3px;color:var(--ms-muted);font-size:8px}\n.live-tracker.is-upcoming{border-color:rgba(55,231,255,.16)}.live-tracker.is-upcoming .live-tracker-main{color:var(--ms-cyan)}.live-tracker.is-live{border-color:rgba(53,212,154,.28);background:rgba(53,212,154,.04)}.live-tracker.is-live .live-tracker-label,.live-tracker.is-live .live-tracker-main{color:#35d49a}.live-tracker.is-finished{border-color:rgba(169,182,206,.2)}.live-tracker.is-finished .live-tracker-main{color:#eef1fb}.live-tracker.is-waiting{border-color:rgba(255,209,102,.16)}.live-tracker.is-waiting .live-tracker-main{color:#ffd166}\n.timer.finished-correct{border-color:#35d49a;background:#06251a}.timer.finished-correct .timerValue{color:#35d49a}.timer.finished-wrong{border-color:#ff7474;background:#2a0d12}.timer.finished-wrong .timerValue{color:#ff7474}.timer.finished{border-color:#8f98b8}.timer.finished .timerValue{color:#eef1fb}\n.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}\n.card{border-radius:12px!important;background:rgba(255,255,255,.02)!important;border:1px solid rgba(255,255,255,.07)!important;box-shadow:none!important}\n.card .meta{font-size:8px}.card .teams{font-size:13px}.card .pick{font-size:9px}.card .section{padding:9px 0}.card .row{font-size:9px;padding:5px 0}.card .timer{margin-top:8px}.card .startTime{font-size:8px}\n.ticket-track{margin-top:14px;padding:17px;border:1px solid rgba(130,150,180,.14);border-radius:18px;background:linear-gradient(145deg,#0a1420,#071019 75%);box-shadow:0 14px 38px rgba(0,0,0,.16)}\n.ticket-track-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}\n.ticket-track-head>b{display:block;margin-top:4px;font-size:16px}\n.ticket-track-kicker{display:block;color:var(--ms-cyan);font-size:8px;font-weight:950;letter-spacing:.15em;text-transform:uppercase}\n.ticket-track .sub{color:var(--ms-muted);font-size:9px;line-height:1.45;margin-top:4px}\n.ticket-track-stats{display:grid;grid-template-columns:repeat(4,minmax(64px,1fr));gap:6px;min-width:290px}\n.ticket-track-stats span{padding:8px 9px;border-radius:10px;background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.06);text-align:center}\n.ticket-track-stats small{display:block;color:var(--ms-muted);font-size:7px;text-transform:uppercase;letter-spacing:.08em}\n.ticket-track-stats b{display:block;margin-top:2px;font-size:15px}\n.ticket-track-stats .ongoing b{color:var(--ms-amber)}.ticket-track-stats .won b{color:var(--ms-green)}.ticket-track-stats .lost b{color:#ff7474}\n.ticket-list{display:grid;gap:7px;margin-top:12px}\n.ticket-card{border:1px solid rgba(255,255,255,.07);border-radius:12px;background:#0b1622;overflow:hidden;box-shadow:none;transition:border-color .16s ease,background .16s ease}\n.ticket-card:hover{border-color:rgba(55,231,255,.22);background:#0d1926}\n.ticket-card.ticket-lost{border-color:rgba(255,116,116,.24)}.ticket-card.ticket-won{border-color:rgba(53,208,127,.22)}\n.ticket-card-summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:12px;padding:11px 12px;cursor:pointer;list-style:none}\n.ticket-card-summary::-webkit-details-marker{display:none}\n.ticket-card-title{min-width:0}.ticket-kicker{display:block;color:var(--ms-muted);font-size:7px;letter-spacing:.08em;overflow-wrap:anywhere}\n.ticket-card-title strong{display:block;margin-top:3px;font-size:11px}.ticket-card-title small{display:block;margin-top:3px;color:var(--ms-muted);font-size:8px}\n.ticket-status{display:inline-flex;align-items:center;margin-left:5px;padding:3px 6px;border-radius:999px;font-size:7px;letter-spacing:.07em;font-weight:950;vertical-align:middle}\n.ticket-status.pending{color:#ffd166;background:rgba(255,209,102,.07);border:1px solid rgba(255,209,102,.18)}.ticket-status.won{color:#35d49a;background:rgba(53,212,154,.07);border:1px solid rgba(53,212,154,.18)}.ticket-status.lost{color:#ff7474;background:rgba(255,116,116,.07);border:1px solid rgba(255,116,116,.18)}\n.ticket-card-odds{text-align:right;flex:none}.ticket-card-odds strong{display:block;font-size:17px;color:var(--ms-cyan)}.ticket-card-odds span{display:block;color:var(--ms-muted);font-size:7px;margin-top:2px}\n.ticket-card-body{padding:0 12px 12px}.ticket-card-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.ticket-card-metrics>div{padding:8px 9px;border-radius:9px;background:rgba(255,255,255,.022);border:1px solid rgba(255,255,255,.05)}.ticket-card-metrics small{display:block;color:var(--ms-muted);font-size:7px;text-transform:uppercase;letter-spacing:.06em}.ticket-card-metrics b{display:block;margin-top:3px;font-size:11px}\n.ticket-progress-wrap{margin-top:9px;padding:10px 11px;border-radius:10px;background:#07101a;border:1px solid rgba(255,255,255,.06)}.ticket-progress-head{display:flex;justify-content:space-between;gap:8px;color:var(--ms-muted);font-size:8px}.ticket-progress-track{height:6px;margin-top:6px;border-radius:99px;background:#152337;overflow:hidden}.ticket-progress-track i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--ms-cyan),#7c6cff,var(--ms-green))}\n.ticket-progress-legend{display:flex;justify-content:space-between;gap:8px;margin-top:6px;color:var(--ms-muted);font-size:8px}.ticket-state-callout{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-top:9px;padding:9px 10px;border-radius:9px;border:1px solid rgba(255,255,255,.06);background:rgba(255,255,255,.018)}.ticket-state-callout strong{font-size:8px}.ticket-state-callout span{color:var(--ms-muted);font-size:8px;line-height:1.4;text-align:right;max-width:66%}\n.ticket-state-callout.pending{border-color:rgba(255,209,102,.15);background:rgba(255,209,102,.025)}.ticket-state-callout.pending strong{color:#ffd166}.ticket-state-callout.won{border-color:rgba(53,212,154,.16);background:rgba(53,212,154,.025)}.ticket-state-callout.won strong{color:#35d49a}.ticket-state-callout.lost{border-color:rgba(255,116,116,.16);background:rgba(255,116,116,.025)}.ticket-state-callout.lost strong{color:#ff7474}\n.ticket-meta-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:9px}.ticket-meta-grid>div{padding:7px 8px;border-radius:8px;background:rgba(255,255,255,.018);border:1px solid rgba(255,255,255,.045)}.ticket-meta-grid small{display:block;color:var(--ms-muted);font-size:7px;text-transform:uppercase}.ticket-meta-grid b{display:block;margin-top:2px;font-size:8px;overflow-wrap:anywhere}\n.ticket-leg-list{display:grid;gap:5px;margin-top:10px}.ticket-leg{display:grid;grid-template-columns:46px minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px 9px;border-radius:9px;background:#09121d;border:1px solid rgba(255,255,255,.05)}.ticket-leg.won{border-color:rgba(53,212,154,.16)}.ticket-leg.lost{border-color:rgba(255,116,116,.16)}.ticket-leg-index{font-size:7px;font-weight:950;color:var(--ms-muted);letter-spacing:.08em}.ticket-leg-core strong,.ticket-leg-core span,.ticket-leg-core small{display:block;overflow-wrap:anywhere}.ticket-leg-core strong{font-size:9px}.ticket-leg-core span{margin-top:2px;color:#c7d4e7;font-size:8px}.ticket-leg-core small{margin-top:2px;color:var(--ms-muted);font-size:7px}.ticket-leg-result{text-align:right}.ticket-leg-result small{display:block;margin-top:3px;color:var(--ms-muted);font-size:7px;max-width:180px;overflow-wrap:anywhere}.ticket-leg-state{display:inline-flex;padding:3px 5px;border-radius:999px;font-size:7px;font-weight:950;letter-spacing:.06em}\n.ticket-leg-state.pending{color:#ffd166;background:rgba(255,209,102,.07);border:1px solid rgba(255,209,102,.15)}.ticket-leg-state.won{color:#35d49a;background:rgba(53,212,154,.07);border:1px solid rgba(53,212,154,.15)}.ticket-leg-state.lost{color:#ff7474;background:rgba(255,116,116,.07);border:1px solid rgba(255,116,116,.15)}.ticket-leg-state.void{color:#a9b6ce;background:rgba(169,182,206,.06);border:1px solid rgba(169,182,206,.12)}\n.settled-card{border-color:#35d49a!important;background:#092018!important}.settled-card .meta{color:#35d49a}.result-badge{font-weight:900;letter-spacing:.02em}.result-badge.won,.won-text{color:#35d49a}.result-badge.lost,.lost-text{color:#ff7474}\n.booking-panel{margin:10px 15px 0;padding:11px 12px;border:1px solid rgba(55,231,255,.16);border-radius:11px;background:rgba(55,231,255,.035)}\n.booking-panel-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.booking-panel-head b{font-size:11px}.booking-panel-head .sub{padding:0;margin-top:3px;color:var(--ms-muted);font-size:8px;line-height:1.45}\n.booking-status{font-size:8px;font-weight:900;letter-spacing:.08em;white-space:nowrap;padding:5px 7px;border-radius:999px}.booking-status.blocked{color:#a9b6ce;background:rgba(169,182,206,.08)}.booking-status.partial{color:#ffd166;background:rgba(255,209,102,.08)}.booking-status.ready{color:#35d49a;background:rgba(53,212,154,.08)}.booking-status.error{color:#ff7474;background:rgba(255,116,116,.08)}.booking-status.loading{color:#f3c76b;background:rgba(243,199,107,.08)}\n.booking-code-wrap{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:9px}.booking-code{display:block;min-width:150px;padding:8px 10px;border-radius:8px;background:#070b11;border:1px solid rgba(255,255,255,.08);font-size:15px;font-weight:900;letter-spacing:.11em}\n.booking-actions{display:flex;gap:6px;flex-wrap:wrap}.booking-btn{border:1px solid rgba(255,255,255,.1);border-radius:8px;background:rgba(255,255,255,.045);color:inherit;padding:7px 9px;font:inherit;font-size:9px;font-weight:800;cursor:pointer;text-decoration:none}.booking-btn.primary{background:#eef1fb;color:#071018}.booking-btn:disabled,.booking-btn.disabled{opacity:.42;pointer-events:none;cursor:not-allowed}.booking-message{margin-top:6px;color:var(--ms-muted);font-size:8px}\n@media(max-width:900px){.builder-console-head,.builder-section-head,.ticket-track-head{flex-direction:column}.builder-live-state,.builder-section-note{text-align:left;min-width:0}.builder-stat-row{grid-template-columns:repeat(2,minmax(0,1fr))}.batch-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.grid{grid-template-columns:1fr}.ticket-track-stats{min-width:0;width:100%}.ticket-card-metrics,.ticket-meta-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}\n@media(max-width:620px){.builder-console,.builder-batch-panel,.ticket-track{padding:13px}.builder-stat-row{grid-template-columns:1fr 1fr}.batch-summary{padding:12px}.batch-odds{font-size:20px}.ticket-track-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.ticket-card-summary{grid-template-columns:minmax(0,1fr) auto}.ticket-card-summary .ticket-card-title small{display:none}.ticket-card-odds{grid-column:2;grid-row:1}.ticket-card-metrics,.ticket-meta-grid{grid-template-columns:1fr 1fr}.ticket-state-callout{flex-direction:column}.ticket-state-callout span{text-align:left;max-width:none}.ticket-leg{grid-template-columns:40px minmax(0,1fr)}.ticket-leg-result{grid-column:2;text-align:left}.ticket-leg-result small{max-width:none}.booking-panel-head{flex-direction:column}.booking-code{width:100%;min-width:0;text-align:center}.booking-actions{width:100%}.booking-btn{flex:1;text-align:center}}';;document.head.appendChild(s);
    }
    if(!window.__matchSignalBookingHandlers){
      window.__matchSignalBookingHandlers=true;
      document.addEventListener('click',function(e){
        var copy=e.target.closest&&e.target.closest('[data-booking-copy]');
        if(copy){
          var batch=findBatchById(copy.getAttribute('data-booking-copy')),state=batch?readBookingState(batch):null;
          if(state&&state.booking_code&&navigator.clipboard){
            navigator.clipboard.writeText(state.booking_code).then(function(){var old=copy.textContent;copy.textContent='Copied';setTimeout(function(){copy.textContent=old;},1200);}).catch(function(){});
          }
          return;
        }
        var refresh=e.target.closest&&e.target.closest('[data-booking-refresh]');
        if(refresh){var b=findBatchById(refresh.getAttribute('data-booking-refresh'));if(b)requestBookingCode(b,true);}
      });
    }
    load();window.setInterval(load,60000);window.setInterval(function(){var all=[];(window.__matchSignalOddsBuilderBatches||[]).forEach(function(b){all=all.concat(Array.isArray(b.legs)?b.legs:[]);});refreshVirtualLiveStatuses(all).then(updateLiveTrackers);},10000);window.setInterval(updateTimers,1000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}());