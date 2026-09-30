    board=load(DATA/"unified_upcoming.json",{})
    model_rows=board.get("events") if isinstance(board,dict) else []
    # Unified Upcoming is generated directly from the live SportyBet snapshot.
    # Use that fresh exact-line snapshot as the price authority here; a second
    # network call can expose a different virtual ladder and can also stall the
    # Builder without adding evidence.
    refreshed_rows, quote_diag = refresh_virtual_quotes(model_rows if isinstance(model_rows,list) else [])

    def row_key(row):
        try:
            return (
                str(row.get("product") or ""),
                str(row.get("event_id") or ""),
                f"{float(row.get('line')):g}" if row.get("line") is not None else "",
            )
        except (TypeError,ValueError):
            return (str(row.get("product") or ""),str(row.get("event_id") or ""),"")
    
    original_map={}
    for row in model_rows if isinstance(model_rows,list) else []:
        if not isinstance(row,dict):
            continue
        original_map[row_key(row)]=row

    merged=[]
    for row in refreshed_rows if isinstance(refreshed_rows,list) else []:
        x=dict(row)
        original=original_map.get(row_key(row))
        if isinstance(original,dict):
            # The direct endpoint may expose a different line ladder for the same
            # recurring fixture. Preserve a fresh exact SportyBet quote from the
            # Unified Board when the direct refresh does not contain that exact line.
            if not x.get("sportybet_over_odds") or not x.get("sportybet_under_odds"):
                age=odds_age(original)
                if (
                    age is not None and age<=MAX_ODDS_AGE_SECONDS
                    and str(original.get("bookmaker_source") or "")=="SportyBet NG"
                    and original.get("sportybet_over_odds") is not None
                    and original.get("sportybet_under_odds") is not None
                ):
                    for key in (
                        "bookmaker_available","bookmaker_source","sportybet_over_odds",
                        "sportybet_under_odds","bookmaker_odds","sportybet_odds",
                        "market_odds_timestamp","sportybet_event_id","sportybet_match"
                    ):
                        if key in original:
                            x[key]=original.get(key)
                    x["price_snapshot_source"]="fresh_unified_sportybet_snapshot"
            else:
                x["price_snapshot_source"]="fresh_direct_sportybet_match"
        merged.append(x)

    # The refreshed list can be smaller than the board when its endpoint uses a
    # narrower current ladder. Add fresh board rows that have exact SportyBet
    # quotes and were not returned by the direct refresh.
    seen={row_key(x) for x in merged}
    for original in model_rows if isinstance(model_rows,list) else []:
        if not isinstance(original,dict):
            continue
        key=row_key(original)
        if key in seen:
            continue
        age=odds_age(original)
        if (
            age is not None and age<=MAX_ODDS_AGE_SECONDS
            and str(original.get("bookmaker_source") or "")=="SportyBet NG"
            and original.get("sportybet_over_odds") is not None
            and original.get("sportybet_under_odds") is not None
        ):
            x=dict(original)
            x["price_snapshot_source"]="fresh_unified_sportybet_snapshot"
            merged.append(x)
            seen.add(key)

    def template_key(product,line,pick):
        return (str(product or ""),f"{float(line):g}",str(pick or "").lower())

    # Discovery universe: every current SportyBet eFootball event/line is
    # inspected independently of whether the older model board marked it
    # betting_qualified. Qualification still requires exact settled evidence.
    recent_index=_load_recent_virtual_evidence()
    templates={}
    discovery_events=set()
    discovery_lines=set()
    discovery_modelable=set()
    discovery_no_evidence=set()
    for row in merged:
        if not isinstance(row,dict) or row.get("sport")!="virtual":
            continue
        product=str(row.get("product") or "")
        if not product.startswith("efootball_"):
            continue
        line=row.get("line")
        if line is None:
            continue
        try:
            line_key=f"{float(line):g}"
        except (TypeError,ValueError):
            continue
        discovery_events.add(str(row.get("event_id") or ""))
        discovery_lines.add((product,line_key))
        for side in ("over","under"):
            exact=recent_index.get((product,line_key,side),[])
            n=len(exact)
            if n<8:
                discovery_no_evidence.add((product,line_key,side))
                continue
            wins=sum(1 for item in exact if item.get("win") is True)
            # Conservative Bayesian empirical probability. This is a fallback
            # model for newly observed lines only; it never lowers the existing
            # evidence threshold and does not create a pick without history.
            prob=(wins+2.0)/(n+4.0)
            key=template_key(product,line,side)
            candidate={**row,"probabilities":{"over":prob if side=="over" else 1.0-prob,
                                             "under":prob if side=="under" else 1.0-prob},
                       "probability":prob,"pick":side,
                       "model":"Virtual Lab exact-line empirical fallback"}
            prev=templates.get(key)
            if prev is None or prob>float(prev.get("probability") or 0):
                templates[key]=candidate
            discovery_modelable.add((product,line_key,side))

    out=[]
    diagnostics={
        "seen":0,"qualified":0,"evidence_pass":0,"rejected_evidence":0,"rejected_ticket_performance":0,
        "current_feed_events":0,"model_templates":len(templates),
        "current_market_candidates":0,"reasons":{}
    }
    diagnostics["current_feed_events"]=len({str(x.get("event_id") or "") for x in merged if isinstance(x,dict) and x.get("event_id")})
    diagnostics["model_template_keys"]=[list(k) for k in sorted(templates.keys())]
    diagnostics["discovery_universe"]={
        "scope":"all current SportyBet eFootball events and every observed O/U line inside the Builder horizon",
        "events_scanned":len([x for x in discovery_events if x]),
        "product_line_pairs_scanned":len(discovery_lines),
        "modelable_product_line_side_pairs":len(discovery_modelable),
        "product_line_side_pairs_without_8_settled_observations":len(discovery_no_evidence),
        "note":"No-evidence lines remain discovery-only and cannot qualify; no gate is weakened."
    }
    diagnostics["current_product_counts"]={}
    diagnostics["current_market_line_counts"]={}
    diagnostics["price_snapshot_sources"]={}
    diagnostics["live_quote_refresh"]={
        "source":quote_diag.get("source") if isinstance(quote_diag,dict) else None,
        "live_events":quote_diag.get("live_events",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_id":quote_diag.get("matched_by_id",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_match":quote_diag.get("matched_by_match",0) if isinstance(quote_diag,dict) else 0,
        "matched_by_participant_time":quote_diag.get("matched_by_participant_time",0) if isinstance(quote_diag,dict) else 0,
        "unmatched":quote_diag.get("unmatched",0) if isinstance(quote_diag,dict) else 0
    }

    for event in merged:
        if not isinstance(event,dict):
            continue
        if event.get("sport")!="virtual" or event.get("product") not in {"efootball_gt","efootball_adriatic","vfootball","zoom"}:
            continue
        if not within_builder_horizon(event,now):
            continue
        product=str(event.get("product") or "")
        line=event.get("line")
        pick=str(event.get("pick") or "").lower()
        if line is None:
            continue
        if not product.startswith("efootball_") and pick not in {"over","under"}:
            continue
        try:
            line=float(line)
        except (TypeError,ValueError):
            continue
        over=event.get("sportybet_over_odds")
        under=event.get("sportybet_under_odds")
        try:
            over=float(over) if over is not None else None
            under=float(under) if under is not None else None
        except (TypeError,ValueError):
            over=under=None
        if over is None or under is None:
            continue

        diagnostics["seen"]+=1
        diagnostics["qualified"]+=1
        diagnostics["current_market_candidates"]+=2
        diagnostics["current_product_counts"][product]=diagnostics["current_product_counts"].get(product,0)+1
        lk=f"{product}|{float(line):g}"
        diagnostics["current_market_line_counts"][lk]=diagnostics["current_market_line_counts"].get(lk,0)+1
        source=str(event.get("price_snapshot_source") or "fresh_unified_sportybet_snapshot")
        diagnostics["price_snapshot_sources"][source]=diagnostics["price_snapshot_sources"].get(source,0)+1

        # eFootball construction is direction-neutral: compare Over and Under
        # on every exact SportyBet line in the discovery universe. Other virtual
        # products retain their existing model-board direction.
        sides=["over","under"] if product.startswith("efootball_") else [pick]

        for side in sides:
            template=templates.get(template_key(product,line,side))
            if not template:
                diagnostics["reasons"]["no_exact_line_model"] = diagnostics["reasons"].get("no_exact_line_model",0)+1
                continue
            probabilities=template.get("probabilities") or {}
            try:
                prob=probabilities.get(side)
                if prob is None:
                    if side==str(template.get("pick") or "").lower():
                        prob=template.get("probability")
                    else:
                        preferred=probabilities.get(str(template.get("pick") or "").lower())
                        if preferred is not None:
                            prob=1.0-float(preferred)
                prob=float(prob)
            except (TypeError,ValueError):
                continue
            if not 0.0<prob<1.0:
                continue

            y={**template}
            y.update({
                "sport":"virtual","product":product,
                "league":event.get("league") or template.get("league"),
                "event_id":str(event.get("event_id") or ""),
                "start_time":event.get("start_time"),
                "participant_1":event.get("participant_1") or event.get("player_1") or event.get("team_1"),
                "participant_2":event.get("participant_2") or event.get("player_2") or event.get("team_2"),
                "player_1":event.get("player_1") or event.get("participant_1") or event.get("team_1"),
                "player_2":event.get("player_2") or event.get("participant_2") or event.get("team_2"),
                "match":event.get("match") or f"{event.get('player_1') or event.get('participant_1') or ''} vs {event.get('player_2') or event.get('participant_2') or ''}",
                "line":line,"pick":side,
                "probability":prob,"builder_probability":prob,
                "bookmaker_available":True,
                "sportybet_over_odds":over,"sportybet_under_odds":under,
                "bookmaker_odds":over if side=="over" else under,
                "sportybet_odds":over if side=="over" else under,
                "bookmaker_source":"SportyBet NG",
                "sportybet_event_id":str(event.get("sportybet_event_id") or event.get("event_id") or ""),
                "sportybet_match":event.get("sportybet_match") or event.get("match"),
                "market_odds_timestamp":event.get("market_odds_timestamp"),
                "sportybet_identity_match":True,
                "sportybet_market_id":event.get("sportybet_market_id"),
                "sportybet_specifier":event.get("sportybet_specifier"),
                "sportybet_over_outcome_id":event.get("sportybet_over_outcome_id"),
                "sportybet_over_outcome_name":event.get("sportybet_over_outcome_name"),
                "sportybet_under_outcome_id":event.get("sportybet_under_outcome_id"),
                "sportybet_under_outcome_name":event.get("sportybet_under_outcome_name"),
                "sportybet_selection_side":side,
                "sportybet_outcome_id":(
                    event.get("sportybet_over_outcome_id") if side=="over" else event.get("sportybet_under_outcome_id")
                ),
                "sportybet_outcome_name":(
                    event.get("sportybet_over_outcome_name") if side=="over" else event.get("sportybet_under_outcome_name")
                ),
                "builder_pick":side,"builder_market":"virtual_total",
                "price_snapshot_source":source,
                "directional_candidate_derived":bool(side!=pick),
                "source_model_pick":pick,
            })

            passed,recent=virtual_recent_gate(product,line,side)
            if not passed:
                diagnostics["rejected_evidence"]+=1
                reason=str(recent.get("reason") or "recent_evidence_below_threshold")
                diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1
                continue

            ticket_pass,ticket_perf=ticket_performance_gate(product,line,side)
            if not ticket_pass:
                diagnostics["rejected_ticket_performance"]+=1
                reason="ticket_performance_below_threshold"
                diagnostics["reasons"][reason]=diagnostics["reasons"].get(reason,0)+1