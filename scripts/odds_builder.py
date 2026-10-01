def build_value_batches(candidates):
    """Build one results-first paper ticket using the best proven 2/3/4-leg shape.

    A shape is promoted only when its own settled-ticket sample, realized odds,
    historical ROI, exact-line evidence, and current expected ROI all pass.
    No extra leg is added merely to reach a target.
    """
    built=[make_leg(x) for x in candidates]
    # Diagnostic-only snapshot of the settled 2/3/4-leg construction lane.
    # This does not alter eligibility or selection; it makes the blocking
    # construction requirement visible when no batch can currently qualify.
    construction_shapes=construction_shape_diagnostics("vfootball")
    eligible_all=[x for x in built if x.get("builder_eligible")]
    eligible_results=[
        x for x in eligible_all
        if RESULTS_FIRST_ENABLED
        and (x.get("results_first") or {}).get("eligible") is True
    ]
    vfootball_pool=[x for x in eligible_results if str(x.get("product") or "")=="vfootball"]
    ordered=sorted(vfootball_pool,key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")))

    promoted_shape=None
    if ordered:
        gate_info=(ordered[0].get("results_first") or {})
        promoted_shape=gate_info.get("construction_leg_count")
        try:
            promoted_shape=int(promoted_shape) if promoted_shape is not None else None
        except (TypeError,ValueError):
            promoted_shape=None

    window_candidates=[]
    for anchor in ordered:
        window=_near_kickoff_window(ordered,anchor)
        max_legs=promoted_shape if promoted_shape in RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS else RESULTS_FIRST_MAX_LEGS
        candidate=_construct_results_first_batch(window,max_legs=max_legs)
        if promoted_shape and len(candidate)!=promoted_shape:
            continue
        if len(candidate)>=BATCH_MIN_LEGS and _batch_kickoff_span_minutes(candidate)<=MAX_BATCH_KICKOFF_SPAN_MINUTES:
            window_candidates.append(candidate)

    batches=[]
    used_events=set()
    if window_candidates:
        batch=max(window_candidates,key=lambda rows:(
            math.prod(max(0.0005,min(0.9995,float(x.get("model_probability") or 0.0))) for x in rows),
            min(_kickoff_timestamp(x) for x in rows if _kickoff_timestamp(x) is not None)
        ))
        batch=sorted(batch,key=lambda x:(_kickoff_timestamp(x) if _kickoff_timestamp(x) is not None else float("inf")))
        metrics=_batch_metrics(batch)
        combined=math.prod(float(x.get("bookmaker_odds") or 1.0) for x in batch)
        current_expected_roi=(float(metrics.get("combined_model_probability") or 0.0)*combined)-1.0
        if combined < RESULTS_FIRST_MIN_COMBINED_ODDS or current_expected_roi < RESULTS_FIRST_MIN_EXPECTED_ROI:
            # This batch is below the results-first construction gate. Do not
            # use `continue` here because this branch is outside the anchor loop.
            return batches,built,{
                "batch_count":0,
                "max_batches":1,
                "disjoint":True,
                "min_combined_odds":RESULTS_FIRST_MIN_COMBINED_ODDS,
                "target_combined_odds":TARGET_COMBINED_ODDS,
                "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
                "construction_priority":"settled_results_first",
                "priority_product":"vfootball",
                "max_legs":RESULTS_FIRST_MAX_LEGS,
                "construction_shapes_considered":list(RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS),
                "promoted_construction_leg_count":promoted_shape,
                "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
                "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
                "used_unique_events":0,
                "eligible_results_first_legs":len(eligible_results),
                "rejection_reason":"combined_odds_or_expected_roi_below_results_first_gate",
                "construction_shape_diagnostics":construction_shapes
            }
        batch_events={str(x.get("event_id") or "") for x in batch if x.get("event_id")}
        used_events.update(batch_events)
        batches.append({
            "batch_id":"BATCH-01",
            "label":f"BATCH-01 · Results-first Model Rating {metrics['model_rating']:.1f}/100",
            "rank_pending":False,
            "rank":1,
            "legs":batch,
            "leg_count":len(batch),
            "combined_odds":round(combined,3),
            "combined_model_rating":metrics["model_rating"],
            "combined_model_probability":metrics["combined_model_probability"],
            "leg_strength_rating":metrics["leg_strength_rating"],
            "avg_model_probability":metrics["avg_model_probability"],
            "avg_model_edge_percent":metrics["avg_model_edge_percent"],
            "products":sorted({str(x.get("product") or "") for x in batch if x.get("product")}),
            "primary_lane":"vfootball",
            "paper_only":True,
            "real_money_execution":False,
            "correlation_policy":"same-event and participant reuse prevented; only results-first qualified legs",
            "construction_objective":"maximize settled-results-backed whole-ticket probability; odds are secondary and never force weaker legs"
        })

    return batches,built,{
        "batch_count":len(batches),
        "max_batches":1,
        "disjoint":True,
        "min_combined_odds":RESULTS_FIRST_MIN_COMBINED_ODDS,
        "target_combined_odds":TARGET_COMBINED_ODDS,
        "accuracy_preservation_ratio":ACCURACY_PRESERVATION_RATIO,
        "construction_priority":"settled_results_first",
        "priority_product":"vfootball",
        "max_legs":RESULTS_FIRST_MAX_LEGS,
        "construction_shapes_considered":list(RESULTS_FIRST_CONSTRUCTION_LEG_COUNTS),
        "promoted_construction_leg_count":promoted_shape,
        "max_kickoff_span_minutes":MAX_BATCH_KICKOFF_SPAN_MINUTES,
        "builder_horizon_minutes":MAX_BUILDER_HORIZON_MINUTES,
        "used_unique_events":len(used_events),
        "eligible_results_first_legs":len(eligible_results),
        "capacity":_batch_capacity_diagnostic(eligible_results),
        "construction_shape_diagnostics":construction_shapes,
        "ranking_metric":"settled exact-line/side hit rate first; calibrated probability second; odds only tie-breaker"
    }


def select_value(candidates):
    built=[make_leg(x) for x in candidates]
    eligible=[x for x in built if x["builder_eligible"]]
    eligible.sort(key=lambda x:(x.get("selection_score") or -1,x.get("model_edge") or -1,x.get("model_probability") or 0,x.get("bookmaker_odds") or 0),reverse=True)
    selected=[];events=set();participants=set();combined=1.0
    skipped_participant=0
    for leg in eligible:
        eid=str(leg.get("event_id") or "")
        if eid and eid in events:continue
        pids=_participants(leg)
        if any(pid in participants for pid in pids):
            skipped_participant+=1
            continue
        selected.append(leg)
        if eid:events.add(eid)
        participants.update(pids)
        combined*=float(leg.get("bookmaker_odds") or 1)
        if combined>=MIN_COMBINED_ODDS or len(selected)>=MAX_LEGS:break
    return selected,built,combined,{"participant_correlation_skips":skipped_participant,"unique_participants":len(participants)}