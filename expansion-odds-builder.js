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
  var bookingMemory = {};

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
  function bookingPanelHtml(batch) {
    var state=readBookingState(batch);
    var status=state&&state.error?'error':(state&&state.booking_code&&bookingStillValid(state)?'ready':'loading');
    var code=state&&state.booking_code?state.booking_code:'';
    var expiry=state&&state.expires_at?dateOf(state.expires_at):null;
    var text=state&&state.error?String(state.error):(status==='ready'?'Copy the code, open SportyBet, and confirm the live slip before placing it.':'Preparing a live SportyBet booking code from the current ticket selections…');
    var id=esc(String(batch&&batch.batch_id||'').replace(/[^A-Za-z0-9_-]/g,''));
    var share=state&&state.share_url?String(state.share_url):'#';
    var openClass=code?'':' disabled';
    var openAttrs=code?'':' aria-disabled="true" tabindex="-1"';
    return '<div class="booking-panel" data-booking-panel="'+id+'">'+
      '<div class="booking-panel-head"><div><b>SportyBet Booking Code</b><div class="sub">Prepared from this exact Builder ticket. Match Signal only creates the betslip/share code; it does not stake or place the wager.</div></div>'+
      '<span class="booking-status '+status+'">'+(status==='ready'?'READY':status==='error'?'REFRESH NEEDED':'PREPARING')+'</span></div>'+
      '<div class="booking-code-wrap"><code class="booking-code" data-booking-code>'+esc(code||'Waiting…')+'</code>'+
      '<div class="booking-actions"><button type="button" class="booking-btn primary" data-booking-copy="'+id+'" '+(code?'':'disabled')+'>Copy code</button>'+
      '<a class="booking-btn link'+openClass+'" data-booking-open="'+id+'" href="'+esc(share)+'" target="_blank" rel="noopener"'+openAttrs+'>Open SportyBet</a>'+
      '<button type="button" class="booking-btn" data-booking-refresh="'+id+'">Refresh code</button></div></div>'+
      '<div class="booking-message">'+esc(text)+(expiry?' · Valid until '+esc(local(expiry.toISOString())):'')+'</div></div>';
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
    var live=state||readBookingState(batch)||{},ready=!!(live.booking_code&&bookingStillValid(live)),error=!!live.error;
    var statusEl=panel.querySelector('.booking-status'),codeEl=panel.querySelector('[data-booking-code]'),msgEl=panel.querySelector('.booking-message'),copy=panel.querySelector('[data-booking-copy]'),open=panel.querySelector('[data-booking-open]');
    if(statusEl){statusEl.className='booking-status '+(error?'error':ready?'ready':'loading');statusEl.textContent=ready?'READY':error?'REFRESH NEEDED':'PREPARING';}
    if(codeEl)codeEl.textContent=ready?live.booking_code:(error?'Unavailable':'Preparing…');
    if(copy)copy.disabled=!ready;
    if(open){
      open.classList.toggle('disabled',!ready);open.setAttribute('aria-disabled',ready?'false':'true');
      if(ready){open.removeAttribute('tabindex');open.href=live.share_url||('https://www.sportybet.com/ng/?c=ng&shareCode='+encodeURIComponent(live.booking_code));}
      else{open.href='#';open.setAttribute('tabindex','-1');}
    }
    if(msgEl){
      var msg=live.error||(ready?'Copy the code, open SportyBet, and confirm the live slip before placing it.':'Preparing a live SportyBet booking code from the current ticket…');
      var ex=live.expires_at?dateOf(live.expires_at):null;if(ex)msg+=' · Valid until '+local(ex.toISOString());
      msgEl.textContent=msg;
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
      .then(function(r){return r.json().catch(function(){return {ok:false,error:'Invalid booking response'};}).then(function(payload){
        if(!r.ok||!payload.ok)throw new Error(String(payload&&payload.message||payload&&payload.error||('HTTP '+r.status)));
        var ready={booking_code:String(payload.booking_code||''),share_url:String(payload.share_url||''),expires_at:payload.expires_at||null,generated_at:new Date().toISOString(),selection_count:Number(payload.selection_count||0)};
        writeBookingState(batch,ready);updateBookingPanel(batch,ready);return ready;
      });})
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
  }
  function ticketTrackHtml(tracker) {
    var tickets=tracker&&Array.isArray(tracker.tickets)?tracker.tickets:[];
    var summary=tracker&&tracker.summary?tracker.summary:{};
    function esc2(v){return esc(v);}
    function ticketStatus(t){
      if(t.status==='WON') return '<b class="ticket-status won">✓ WON</b>';
      if(t.status==='LOST') return '<b class="ticket-status lost">✕ LOST</b>';
      return '<b class="ticket-status pending">ONGOING</b>';
    }
    function ticketRows(t){
      var lc=t.leg_counts||{};
      var bits=[];
      if(Number(lc.won||0)) bits.push(lc.won+' won');
      if(Number(lc.lost||0)) bits.push(lc.lost+' lost');
      if(Number(lc.void||0)) bits.push(lc.void+' void');
      if(Number(lc.pending||0)) bits.push(lc.pending+' pending');
      return bits.join(' · ')||'—';
    }
    var cards=tickets.slice(0,10).map(function(t){
      var activeLoss=t.status==='LOST' && Number((t.leg_counts||{}).pending||0)>0;
      return '<div class="ticket-row '+(t.status==='LOST'?'ticket-lost':t.status==='WON'?'ticket-won':'ticket-pending')+'">'+
        '<div class="ticket-main"><span class="ticket-id">'+esc2(t.ticket_id||'—')+'</span><strong>'+(t.batch_id?esc2(t.batch_id)+' · ':'')+ticketStatus(t)+'</strong>'+
        '<small>'+esc2(t.leg_count||((t.legs||[]).length))+' legs · '+esc2(t.combined_odds==null?'—':Number(t.combined_odds).toFixed(3))+'x · rating '+esc2(t.combined_model_rating==null?'—':Number(t.combined_model_rating).toFixed(1)+'/100')+'</small></div>'+
        '<div class="ticket-progress">'+esc2(ticketRows(t))+(activeLoss?' · loss confirmed while other legs remain pending':'')+'</div>'+
        '</div>';
    }).join('');
    if(!cards) cards='<div class="empty">No generated paper tickets have been tracked yet.</div>';
    return '<section class="ticket-track"><div class="ticket-track-head"><div><b>Paper Ticket Track</b><div class="sub">Each generated batch is tracked independently. A single losing leg changes an ongoing ticket to LOST immediately; remaining legs continue settling for the record.</div></div>'+
      '<div class="ticket-track-stats"><span>Ongoing <b>'+esc2(summary.pending||0)+'</b></span><span>Won <b>'+esc2(summary.won||0)+'</b></span><span>Lost <b>'+esc2(summary.lost||0)+'</b></span></div></div>'+
      '<div class="ticket-list">'+cards+'</div></section>';
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
      return '<article class="card '+(isSettled?'settled-card':'')+'"><div class="meta"><span>Leg '+(i+1)+' · '+esc(product)+' · '+esc(l.competition||'—')+'</span><span>'+(isSettled?'<b class="result-badge '+(settled.correct===true?'won':'lost')+'">'+resultText+'</b>':'SportyBet '+esc(l.bookmaker_odds==null?'—':l.bookmaker_odds))+'</span></div><div class="teams">'+esc(l.match||'—')+'</div><div class="pick">Selection: <b>'+esc(l.pick||'—')+'</b><span class="conf">Model '+pct(l.model_probability)+'</span></div>'+timer(l.start_time,l)+'<div class="startTime">'+(isSettled?'Result confirmed · '+esc(local(l.start_time)):'Start: '+esc(local(l.start_time))+' <span>· your browser time</span>')+'</div><div class="section"><div class="row"><span>Market</span><b>'+esc(l.market||'—')+'</b></div><div class="row"><span>Model probability</span><b>'+pct(l.model_probability)+'</b></div><div class="row"><span>Model fair odds</span><b>'+esc(l.model_fair_odds==null?'—':l.model_fair_odds)+'</b></div><div class="row"><span>SportyBet price</span><b>'+esc(l.bookmaker_odds==null?'—':l.bookmaker_odds)+'</b></div><div class="row"><span>Model edge vs market</span><b>'+esc(l.model_edge==null?'—':pct(l.model_edge))+'</b></div><div class="row"><span>Market price age</span><b>'+esc(l.market_odds_age_seconds==null?'—':Math.round(Number(l.market_odds_age_seconds))+'s')+'</b></div><div class="row"><span>Result</span><b class="'+(isSettled?(settled.correct===true?'won-text':'lost-text'):'')+'">'+(isSettled?resultText:'Pending')+'</b></div></div></article>';
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
        '<details class="batch-card" '+(idx===0?'open':'')+'>',
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
    target.innerHTML='<div class="metrics"><div class="metric"><small>Active batches</small><strong>'+batchCount+'/6</strong></div><div class="metric"><small>Sports</small><strong>'+esc(sports.length?sports.join(' + '):'—')+'</strong></div><div class="metric"><small>Top combined model rating</small><strong>'+esc(topRating==null?'—':topRating.toFixed(1)+'/100')+'</strong></div><div class="metric"><small>Top combined SportyBet odds</small><strong>'+esc(top&&top.combined_odds!=null?Number(top.combined_odds).toFixed(3):'—')+'</strong></div></div><div class="panel"><b>Ranked 4.00+ Paper Research Batches</b><div class="sub">Separate batches are kept disjoint by event. Higher combined model rating means a stronger naive joint model-probability proxy; it is not a guarantee.</div><div class="batch-list">'+(cards||'<div class="empty">No qualified 4.00+ batches are currently available.</div>')+'</div><div class="section"><div class="row"><span>Bookmaker feed</span><b>Fresh SportyBet snapshot · paper only</b></div><div class="row"><span>Top batch joint-model probability proxy</span><b>'+esc(topJoint==null?'—':pct(topJoint))+'</b></div><div class="row"><span>Candidate pool</span><b>'+esc(virtualCount)+'</b></div></div>'+gateNote+'</div>';
    updateTimers();
    var host=document.createElement('div');
    host.innerHTML=ticketTrack;
    target.appendChild(host.firstElementChild);
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
      return refreshLiveStatuses(legs).then(function(){render(data,tracker);}).then(function(){return ensureBookingCodes(Array.isArray(data.batches)?data.batches:[]);});
    }).catch(function(e){target.innerHTML='<div class="empty">Accumulator data unavailable: '+esc(e.message)+'</div>';});
  }
  function boot(){
    if(!document.getElementById('odds-builder-result-style')){
      var s=document.createElement('style');s.id='odds-builder-result-style';s.textContent='.batch-list{display:grid;gap:14px}.batch-card{border:1px solid rgba(255,255,255,.1);border-radius:16px;background:#0c121c;overflow:hidden}.batch-summary{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 20px;cursor:pointer;list-style:none}.batch-summary::-webkit-details-marker{display:none}.batch-kicker{display:block;font-size:11px;letter-spacing:.12em;text-transform:uppercase;opacity:.7;margin-bottom:4px}.batch-summary strong{display:block;font-size:16px}.batch-summary small{display:block;opacity:.72;margin-top:5px}.batch-odds{font-size:22px;font-weight:900;white-space:nowrap}.batch-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;padding:0 20px 14px}.batch-metrics>div{padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.035)}.batch-metrics span{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em;opacity:.65}.batch-metrics b{display:block;margin-top:4px;font-size:15px}.batch-card>.sub{padding:0 20px 14px}.batch-card>.grid{padding:0 20px 20px}@media(max-width:900px){.batch-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}};\'.timer.finished-correct{border-color:#35d49a;background:#06251a}.timer.finished-correct .timerValue{color:#35d49a}.timer.finished-wrong{border-color:#ff7474;background:#2a0d12}.timer.finished-wrong .timerValue{color:#ff7474}.timer.finished{border-color:#8f98b8}.timer.finished .timerValue{color:#eef1fb}.ticket-track{margin-top:18px;padding:18px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:#0c121c}.ticket-track-head{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}.ticket-track-stats{display:flex;gap:8px;flex-wrap:wrap}.ticket-track-stats span{padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.04);font-size:11px}.ticket-list{display:grid;gap:8px;margin-top:14px}.ticket-row{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,255,255,.08);background:rgba(255,255,255,.025)}.ticket-row.ticket-lost{border-color:rgba(255,116,116,.38)}.ticket-row.ticket-won{border-color:rgba(53,208,127,.38)}.ticket-main strong{display:block;margin-top:3px}.ticket-main small,.ticket-progress{font-size:11px;opacity:.72}.ticket-id{font-size:10px;letter-spacing:.08em;opacity:.65}.ticket-status.won,.ticket-row.ticket-won .ticket-progress{color:#35d49a}.ticket-status.lost,.ticket-row.ticket-lost .ticket-progress{color:#ff7474}.ticket-status.pending{color:#f3c76b}.ticket-progress{text-align:right}.settled-card{border-color:#35d49a;background:#092018}.settled-card .meta{color:#35d49a}.result-badge{font-weight:900;letter-spacing:.02em}.result-badge.won,.won-text{color:#35d49a}.result-badge.lost,.lost-text{color:#ff7474}.booking-panel{margin:16px 20px 0;padding:14px 16px;border:1px solid rgba(255,255,255,.1);border-radius:14px;background:rgba(255,255,255,.025)}.booking-panel-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.booking-panel-head b{font-size:13px}.booking-status{font-size:10px;font-weight:900;letter-spacing:.08em;white-space:nowrap;padding:6px 8px;border-radius:999px}.booking-status.ready{color:#35d49a;background:rgba(53,212,154,.1)}.booking-status.error{color:#ff7474;background:rgba(255,116,116,.1)}.booking-status.loading{color:#f3c76b;background:rgba(243,199,107,.1)}.booking-code-wrap{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px}.booking-code{display:block;min-width:170px;padding:11px 13px;border-radius:10px;background:#070b11;border:1px solid rgba(255,255,255,.08);font-size:18px;font-weight:900;letter-spacing:.12em}.booking-actions{display:flex;gap:8px;flex-wrap:wrap}.booking-btn{border:1px solid rgba(255,255,255,.12);border-radius:9px;background:rgba(255,255,255,.05);color:inherit;padding:9px 11px;font:inherit;font-size:11px;font-weight:800;cursor:pointer;text-decoration:none}.booking-btn.primary{background:#eef1fb;color:#071018}.booking-btn:disabled,.booking-btn.disabled{opacity:.4;pointer-events:none;cursor:not-allowed}.booking-message{margin-top:8px;font-size:10px;opacity:.7}@media(max-width:700px){.booking-panel-head{flex-direction:column}.booking-code{width:100%;min-width:0;text-align:center}.booking-actions{width:100%}.booking-btn{flex:1;text-align:center}}';;document.head.appendChild(s);
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
    load();window.setInterval(load,60000);window.setInterval(updateTimers,1000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
}());