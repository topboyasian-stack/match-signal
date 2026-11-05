"""Empirical risk gate for Match Signal.

Evaluation is time-safe and product-scoped. WTA is retained as research history,
but only the active ATP singles lane contributes to the tennis release gate.
This module never turns on live betting or changes model probabilities.
"""
import json, math
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
MIN_SETTLED=100
MIN_VALUE_TRIALS=30
MIN_VALUE_ROI=0.0
MAX_TRIAL_QUOTE_AGE_SECONDS=15*60
MAX_MODEL_PREDICTION_AGE_SECONDS=12*60*60
EXPECTED_WINNER_MARKET_ID={'football':'1','tennis':'186'}
ACTIVE_LEAGUE_BY_SPORT={'tennis':'ATP'}


def load(name, default):
    try: return json.loads((DATA/name).read_text(encoding='utf-8'))
    except Exception: return default


def parse_utc(value):
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError,ValueError,OverflowError):
        return None


def settlement_record_eligible(row):
    """Validate the settled outcome independently of the forecast snapshot."""
    return bool(
        isinstance(row,dict)
        and row.get('settled') is True
        and row.get('actual') in {'p1','p2','draw'}
        and str(row.get('event_id') or '')
    )


def evaluation_eligible(row):
    """Only score model forecasts made before kickoff and within 12 hours."""
    if not settlement_record_eligible(row):
        return False
    start_at=parse_utc(row.get('start_time'))
    calculated_at=parse_utc(row.get('calculated_at'))
    if start_at is None or calculated_at is None:
        return False
    model_age=(start_at-calculated_at).total_seconds()
    if model_age < 0 or model_age > MAX_MODEL_PREDICTION_AGE_SECONDS:
        return False
    if str(row.get('sport') or '').lower()=='tennis':
        # Tennis archive classification is immutable; unknown/late captures
        # cannot enter the active ATP training or performance sample.
        if row.get('evaluation_eligible') is not True or row.get('capture_status')!='PRE_EVENT':
            return False
    elif row.get('evaluation_eligible') is False or row.get('capture_status')=='LATE_CAPTURE':
        return False
    return True


def brier(p):
    q=p.get('probabilities') or {}; sport=str(p.get('sport','')).lower(); actual=p.get('actual')
    vals=[float(q.get('p1',0)),float(q.get('draw',0)),float(q.get('p2',0))] if sport=='football' else [float(q.get('p1',0)),float(q.get('p2',0))]
    idx={'p1':0,'draw':1,'p2':2}.get(actual)
    return None if idx is None else sum((v-(i==idx))**2 for i,v in enumerate(vals))


def in_scope(row, sport, league=None):
    if str(row.get('sport','')).lower()!=sport or not evaluation_eligible(row):
        return False
    if league is not None and str(row.get('league') or row.get('tour') or '').upper()!=str(league).upper():
        return False
    return True


def evaluate(rows,sport,league=None):
    r=[p for p in rows if in_scope(p,sport,league)]
    baseline=2/3 if sport=='football' else .5
    if not r: return {'settled':0,'accuracy':None,'brier':None,'baseline_brier':baseline,'bins':[]}
    acc=sum(p.get('pick')==p.get('actual') for p in r)/len(r); bs=[brier(p) for p in r]; bs=[x for x in bs if x is not None]
    bins=[]
    for lo,hi in ((.50,.55),(.55,.60),(.60,.65),(.65,.70),(.70,.80),(.80,1.01)):
        z=[p for p in r if lo<=float(p.get('confidence') or 0)<hi]
        if z: bins.append({'range':f'{lo:.2f}-{min(hi,1):.2f}','n':len(z),'accuracy':round(sum(p.get('pick')==p.get('actual') for p in z)/len(z),4),'mean_confidence':round(sum(float(p.get('confidence') or 0) for p in z)/len(z),4)})
    return {'settled':len(r),'accuracy':round(acc,4),'brier':round(sum(bs)/len(bs),4) if bs else None,'baseline_brier':baseline,'bins':bins}


def american_to_decimal(odds):
    try:
        x=float(odds)
        if x>0:return 1+x/100
        if x<0:return 1+100/abs(x)
    except (TypeError,ValueError,ZeroDivisionError):
        return None
    return None


def value_trial(row):
    """Enroll a frozen pregame value trial; never backfill a post-kickoff quote."""
    if not evaluation_eligible(row):
        return None
    pick=str(row.get('pick') or '')
    if pick not in {'p1','p2','draw'}:
        return None
    insights=row.get('market_insights') or {}
    winner_odds=row.get('sportybet_winner_odds') or {}
    snapshot_at=(
        insights.get('snapshot_at')
        or (row.get('sportybet_market_snapshot') or {}).get('fetched_at')
        or row.get('value_evidence_frozen_at')
    )
    start_at=parse_utc(row.get('start_time'))
    quote_at=parse_utc(snapshot_at)
    sport=str(row.get('sport') or '').lower()
    expected_market=EXPECTED_WINNER_MARKET_ID.get(sport)
    market_id=str(winner_odds.get('market_id') or '')
    source=str(insights.get('source') or row.get('market_source') or '')
    if (
        start_at is None
        or quote_at is None
        or not expected_market
        or market_id != expected_market
        or 'sportybet' not in source.lower()
    ):
        return None
    quote_age_seconds=(start_at-quote_at).total_seconds()
    # Only exact SportyBet winner quotes captured during the final 15 minutes
    # before the scheduled start count as a settled value trial. Historical
    # odds fields without a source timestamp are not retroactively accepted.
    if quote_age_seconds < 0 or quote_age_seconds > MAX_TRIAL_QUOTE_AGE_SECONDS:
        return None
    odds_map={'p1':winner_odds.get('p1'),'p2':winner_odds.get('p2'),'draw':winner_odds.get('draw')}
    book=odds_map.get(pick)
    model_prob=(row.get('probabilities') or {}).get(pick)
    try:
        dec=float(book) if book is not None else None
        if dec is not None and dec<=1.0: dec=None
    except (TypeError,ValueError):
        dec=None
    try:
        prob=float(model_prob) if model_prob is not None else None
    except (TypeError,ValueError):
        prob=None
    try:
        conf=float(row.get('confidence'))
    except (TypeError,ValueError):
        conf=None

    # Precommitted cohort includes all moderate-confidence picks with valid
    # pregame prices; it is not filtered by whether the price later proved +EV.
    if dec is None or prob is None or prob<=0 or prob>=1:
        return None
    if conf is None or conf < 0.55:
        return None

    implied=1.0/dec
    book_edge=prob-implied
    expected_value=prob*dec-1.0
    realized_roi=(dec-1.0) if row.get('actual')==pick else -1.0
    return {
        'event_id':row.get('event_id'),'sport':row.get('sport'),'league':row.get('league') or row.get('tour'),
        'pick':pick,'roi':realized_roi,'won':row.get('actual')==pick,
        'model_probability':round(prob,6),'confidence':round(conf,6),
        'edge':round(book_edge,6),'expected_value':round(expected_value,6),
        'frozen_odds':float(book),'frozen_odds_at':quote_at.isoformat(),
        'kickoff_at':start_at.isoformat(),
        'model_age_seconds':round((start_at-parse_utc(row.get('calculated_at'))).total_seconds(),3),
        'quote_age_seconds':round(quote_age_seconds,3),
        'market_id':market_id,
        'source':'SportyBet NG frozen winner snapshot',
        'trial_enrollment':'precommitted_confidence_0.55_plus_frozen_pregame_odds',
        'approval_hurdle':'30_active_scope_trials_and_positive_realized_roi'
    }


def capture_value_trials(rows, snapshots):
    """Join immutable final-15-minute quote snapshots to settled results."""
    settled_by_event = {}
    for row in rows:
        if not settlement_record_eligible(row):
            continue
        event_id = str(row.get('event_id') or '')
        if not event_id:
            continue
        prior = settled_by_event.get(event_id)
        if prior is None or str(row.get('settled_at') or '') > str(prior.get('settled_at') or ''):
            settled_by_event[event_id] = row

    latest_by_event = {}
    for snapshot in snapshots if isinstance(snapshots, list) else []:
        if not isinstance(snapshot, dict):
            continue
        event_id = str(snapshot.get('event_id') or '')
        if not event_id or event_id not in settled_by_event:
            continue
        actual_row = settled_by_event[event_id]
        sport = str(snapshot.get('sport') or '').lower()
        if str(actual_row.get('sport') or '').lower() != sport:
            continue
        if str(snapshot.get('league') or '').upper() != str(actual_row.get('league') or actual_row.get('tour') or '').upper():
            continue
        market_id = str(snapshot.get('market_id') or '')
        if market_id != EXPECTED_WINNER_MARKET_ID.get(sport):
            continue
        captured_at = parse_utc(snapshot.get('captured_at'))
        start_at = parse_utc(snapshot.get('start_time'))
        result_start = parse_utc(actual_row.get('start_time'))
        model_calculated_at = parse_utc(snapshot.get('model_calculated_at'))
        if captured_at is None or start_at is None or result_start is None or model_calculated_at is None:
            continue
        age = (start_at - captured_at).total_seconds()
        model_age = (start_at - model_calculated_at).total_seconds()
        if age < 0 or age > MAX_TRIAL_QUOTE_AGE_SECONDS:
            continue
        if model_age < 0 or model_age > MAX_MODEL_PREDICTION_AGE_SECONDS:
            continue
        # The bookmaker fixture must resolve to the same scheduled event in
        # the settled ledger, not merely to a similar player/team name.
        if abs((start_at - result_start).total_seconds()) > 120:
            continue
        if str(snapshot.get('source') or '').lower() != 'sportybet ng':
            continue
        pick = str(snapshot.get('pick') or '')
        if pick not in {'p1', 'p2', 'draw'} or (sport == 'tennis' and pick == 'draw'):
            continue
        try:
            probability = float(snapshot.get('model_probability'))
            confidence = float(snapshot.get('confidence'))
            price = float((snapshot.get('prices') or {}).get(pick))
        except (TypeError, ValueError):
            continue
        if not (0 < probability < 1 and 0 < confidence <= 1 and price > 1):
            continue
        if confidence < 0.55:
            continue

        candidate = {
            'event_id': event_id,
            'sport': sport,
            'league': snapshot.get('league'),
            'pick': pick,
            'roi': (price - 1.0) if actual_row.get('actual') == pick else -1.0,
            'won': actual_row.get('actual') == pick,
            'model_probability': round(probability, 6),
            'confidence': round(confidence, 6),
            'edge': round(probability - (1.0 / price), 6),
            'expected_value': round(probability * price - 1.0, 6),
            'frozen_odds': price,
            'frozen_odds_at': captured_at.isoformat(),
            'kickoff_at': start_at.isoformat(),
            'quote_age_seconds': round(age, 3),
            'market_id': market_id,
            'source': 'SportyBet NG immutable pregame capture ledger',
            'trial_enrollment': 'precommitted_confidence_0.55_plus_final_15m_quote',
            'approval_hurdle': '30_active_scope_trials_and_positive_realized_roi',
        }
        prior = latest_by_event.get(event_id)
        if prior is None or candidate['frozen_odds_at'] > prior['frozen_odds_at']:
            latest_by_event[event_id] = candidate

    return list(latest_by_event.values())


def merge_unique_trials(*trial_groups):
    latest_by_event = {}
    for group in trial_groups:
        for trial in group or []:
            event_id = str(trial.get('event_id') or '')
            if not event_id:
                continue
            prior = latest_by_event.get(event_id)
            stamp = str(trial.get('frozen_odds_at') or '')
            if prior is None or stamp > str(prior.get('frozen_odds_at') or ''):
                latest_by_event[event_id] = trial
    return list(latest_by_event.values())


def value_testing(rows,sport,league=None,captured_trials=None):
    legacy=[x for r in rows if in_scope(r,sport,league) for x in [value_trial(r)] if x]
    captured=[x for x in (captured_trials or []) if str(x.get('sport') or '').lower()==sport and (league is None or str(x.get('league') or '').upper()==str(league).upper())]
    trials=merge_unique_trials(legacy,captured)
    if not trials:
        return {'trials':0,'wins':0,'roi_units':0.0,'roi':None,'status':'NO_VALUE_TRIALS','required_trials':MIN_VALUE_TRIALS}
    units=sum(x['roi'] for x in trials)
    roi=units/len(trials)
    return {'trials':len(trials),'wins':sum(bool(x['won']) for x in trials),'roi_units':round(units,6),'roi':round(roi,6),'status':'PASS' if len(trials)>=MIN_VALUE_TRIALS and roi>MIN_VALUE_ROI else 'INSUFFICIENT_OR_NONPOSITIVE','required_trials':MIN_VALUE_TRIALS,'latest_frozen_snapshot':max((x.get('frozen_odds_at') or '' for x in trials),default=None)}


def main():
    history=load('prediction_history.json',[])+load('basketball_history.json',[])
    capture_ledger=load('sportybet_pregame_snapshots.json',{})
    capture_snapshots=capture_ledger.get('snapshots',[]) if isinstance(capture_ledger,dict) else []
    captured_trials=capture_value_trials(history,capture_snapshots)
    metrics={}
    gate={}
    scope_diagnostics={}
    for sport in ('football','tennis','basketball'):
        active_league=ACTIVE_LEAGUE_BY_SPORT.get(sport)
        metrics[sport]=evaluate(history,sport,league=active_league)
        value=value_testing(history,sport,league=active_league,captured_trials=captured_trials)
        enough=metrics[sport]['settled']>=MIN_SETTLED
        better=metrics[sport]['brier'] is not None and metrics[sport]['brier']<metrics[sport]['baseline_brier']
        reasons=[]
        if not enough:
            reasons.append(f"need >={MIN_SETTLED} settled picks in active scope (have {metrics[sport]['settled']})")
        if metrics[sport]['brier'] is not None and not better:
            reasons.append(f"Brier {metrics[sport]['brier']} has not beaten baseline {metrics[sport]['baseline_brier']}")
        if value['trials']<MIN_VALUE_TRIALS:
            reasons.append(f"need >={MIN_VALUE_TRIALS} settled active-scope value trials with frozen pregame odds (have {value['trials']})")
        elif value['roi'] is None or value['roi']<=MIN_VALUE_ROI:
            reasons.append(f"value-test realized ROI {value['roi']} is not > {MIN_VALUE_ROI}")
        model_risk_approval_passed=bool(
            enough and better and value['trials']>=MIN_VALUE_TRIALS and
            value['roi'] is not None and value['roi']>MIN_VALUE_ROI
        )
        gate[sport]={
            'active_scope':active_league or 'all',
            'live_eligible':False,
            'model_risk_approval_passed':model_risk_approval_passed,
            'live_trading_enabled':False,
            'paper_only':True,
            'value_testing':value,
            'reasons':reasons,
        }
        if active_league:
            inactive={}
            seen=sorted({str(r.get('league') or r.get('tour') or '').upper() for r in history if str(r.get('sport') or '').lower()==sport})
            for tour in seen:
                if tour and tour!=active_league.upper():
                    inactive[tour]={
                        'metrics':evaluate(history,sport,league=tour),
                        'value_testing':value_testing(history,sport,league=tour,captured_trials=captured_trials),
                        'status':'RESEARCH_ONLY_INACTIVE_SCOPE'
                    }
            scope_diagnostics[sport]={'active_scope':active_league,'inactive_scopes':inactive,'pooling_disabled':True}

    for name in ('predictions.json','basketball_predictions.json'):
        path=DATA/name; rows=load(name,[])
        for p in rows:
            g=gate.get(str(p.get('sport','')).lower(),{'live_eligible':False})
            p['live_eligible']=bool(g['live_eligible']); p['testing_mode']='paper'
        path.write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
    legacy_trials=[x for r in history for x in [value_trial(r)] if x]
    trial_ledger=merge_unique_trials(legacy_trials,captured_trials)
    now=datetime.now(timezone.utc).isoformat()
    ledger_path=DATA/'value_trial_ledger.json'
    ledger={'generated_at':now,'mode':'PAPER_ONLY','policy':'Frozen SportyBet prices strictly within the final 15 minutes before kickoff; late/ineligible captures excluded. Immutable capture-ledger snapshots are joined by exact event identity to settled outcomes. Active tennis qualification uses ATP only; WTA remains separately reported research evidence.','trials':trial_ledger}
    prior_ledger=load('value_trial_ledger.json',{})
    if isinstance(prior_ledger,dict) and prior_ledger.get('trials')==ledger['trials'] and prior_ledger.get('policy')==ledger['policy']:
        ledger['generated_at']=prior_ledger.get('generated_at') or now
    ledger_path.write_text(json.dumps(ledger,indent=2,ensure_ascii=False),encoding='utf-8')

    out={'generated_at':now,'mode':'PAPER_ONLY','metrics':metrics,'scope_diagnostics':scope_diagnostics,'gate':gate}
    prior_gate=load('risk_gate.json',{})
    if isinstance(prior_gate,dict):
        old_comparison=dict(prior_gate); old_comparison.pop('generated_at',None)
        new_comparison=dict(out); new_comparison.pop('generated_at',None)
        if old_comparison==new_comparison:
            out['generated_at']=prior_gate.get('generated_at') or now
    (DATA/'risk_gate.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
