# QM Reversal shadow replay — GBPUSD 2026-10-19 (session so far)

- bars_processed: 139
- first_bar: 2026-10-19T00:00:00+00:00
- last_bar: 2026-10-19T11:30:00+00:00
- armed_count_total: 1
- fire_count_total: 1
- fires_allowed_by_nms_v3: 1
- fires_blocked_by_nms_v3: 0

## First structural level map snapshot

- symbol: GBPUSD
- computed_at: 2026-10-19T00:00:00+00:00
- p_level: Level(type='P', price=13320.983333333332, source_ts='2026-10-16T00:00:00+00:00')
- outer_pivots: [('R1', 13374.216666666664), ('R2', 13424.483333333332), ('R3', 13477.716666666664), ('S1', 13270.716666666664), ('S2', 13217.483333333332), ('S3', 13167.216666666664)]
- other_levels: [('SWING_H', 13339.05), ('SWING_L', 13308.45), ('RANGE_H', 13339.05), ('RANGE_L', 13333.849999999999), ('PDH', 13371.25), ('PDL', 13267.75), ('BB_U', 13336.808914606143), ('BB_L', 13320.871085393857), ('R00', 13350.0)]
- clusters: 10
- density: 8

## Armed samples (first 5)

- {'arm_bar_ts': '2026-10-19T08:35:00+00:00', 'side': 'BUY', 'level_type': 'P', 'level_price': 13320.983333333332, 'trigger_price': 13323.349999999999, 'stop_price': 13314.75, 'stop_dist_pips': 8.6, 'arm_reason_codes': ['role_reversal_retest_armed:lt=P', 'trigger=13323.35000', 'stop=13314.75000', 'session_phase=LONDON', 'daily_bias=UNKNOWN']}

## Fire samples (first 10)

- {'fire_ts': '2026-10-19T08:40:00+00:00', 'tick_label': 'high', 'side': 'BUY', 'level_type': 'P', 'level_price': 13320.983333333332, 'entry_price': 13323.349999999999, 'stop_price': 13314.75, 'stop_dist_pips': 8.6, 'broker_compliant_sl_pips': 12.0, 'nms_state': 'RANGE', 'nms_allowed': True, 'reason_codes': ['role_reversal_retest_armed:lt=P', 'trigger=13323.35000', 'stop=13314.75000', 'session_phase=LONDON', 'daily_bias=UNKNOWN', 'nms_v3:nms_v3_direction_pass:state=RANGE'], 'struct_tp_pips': 12.5, 'struct_tp_err': None, 'struct_tp_min_r_1_5_pips': None, 'struct_tp_min_r_1_5_err': 'qm_reversal_tp_struct_below_min_R:actual_R=1.042<min_R=1.500 tp_pips=12.50 broker_sl_pips=12.00'}
