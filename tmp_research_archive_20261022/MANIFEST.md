# /tmp Research Archive — 2026-10-22

Captured research artefacts from the AutoBot host's `/tmp/` directory
on `AutoBotV1` before clean-up. Preserves markdown reports, named text
reports, dated research code, and small JSON "results" files that back
dated reports.

## Contents

* `reports/` — 72 markdown research reports.
* `text_reports/` — 16 named `.txt` reports (findings, audits, verdicts).
* `code/` — 21 dated research Python scripts.
* `results/` — 4 JSON results files that back dated reports.

## Explicit exclusions (safety)

* No `.env*` files.
* No files containing literal API keys / JWT tokens.
* No files from active git worktrees (verified against `git worktree list`).
* No pytest fixture dirs (`pytest-candidate-corpus-*`, see SAFE_DELETE.md).

## Verification

Each row's `sha256` is computed on the archive copy. The matching line
in the paired `MANIFEST_SOURCE.md` records the SHA-256 of the original
`/tmp/<file>`. These two SHAs are byte-identical for every row.

| Original path | Archive path | Size (B) | SHA-256 (archive) |
|---|---|---|---|
| `/tmp/A6_required_timeline.md` | `tmp_research_archive_20261022/reports/A6_required_timeline.md` | 3529 | `86a90ce86268ed65fd783b20cada31390cdc14de63063ca938b76ce4cc2a3f35` |
| `/tmp/audit_autobot_behaviour_20260925.md` | `tmp_research_archive_20261022/reports/audit_autobot_behaviour_20260925.md` | 26980 | `ab3eb93ef25a4ce91167b9f51bec7a12f00f49f6c875fcc52b5642162c72b0b8` |
| `/tmp/audit_historical_counterfactual_20260925.md` | `tmp_research_archive_20261022/reports/audit_historical_counterfactual_20260925.md` | 9895 | `e8ae22ccfb040e794b7c3addf3ff6d0455a3b543aaf7930e730af5bce8999812` |
| `/tmp/audit_price_story_20260925.md` | `tmp_research_archive_20261022/reports/audit_price_story_20260925.md` | 16932 | `c0666860c6b2a691704690f2e57f0ccf38858049fd74f3c916128c19c63cd546` |
| `/tmp/baseline_report.md` | `tmp_research_archive_20261022/reports/baseline_report.md` | 6163 | `1ec7708b62dd57d2512fad2fb78119d09aa066f6f2dc4aa4f774a8e1f7b5dc8a` |
| `/tmp/bb_band2outer_REPORT.md` | `tmp_research_archive_20261022/reports/bb_band2outer_REPORT.md` | 17972 | `d0e3f6b9019d2b3e51cb91a6739ca2865921452450785afaf06028414dd4bd3d` |
| `/tmp/bb_level_report_v2.md` | `tmp_research_archive_20261022/reports/bb_level_report_v2.md` | 13838 | `96a3b24a5cf587e009fee9a62c05b08df77294b8841b8a63ddcea2b2ee21cd1b` |
| `/tmp/bb_pierce_REPORT.md` | `tmp_research_archive_20261022/reports/bb_pierce_REPORT.md` | 10990 | `cc46a076191418bb3bdcc0e4f4f5c53119a15a190db804885a37b0d3f9d4d7a6` |
| `/tmp/bb_pierce_RERUN_REPORT.md` | `tmp_research_archive_20261022/reports/bb_pierce_RERUN_REPORT.md` | 13415 | `cbe757172a2a2412b6c5cfde207be17556c9d5bd2fe9f0153b8b81bb3567b5d3` |
| `/tmp/bb_pierce_entry_timing_REPORT.md` | `tmp_research_archive_20261022/reports/bb_pierce_entry_timing_REPORT.md` | 9508 | `ca1d0d59c2e2f70c0baf2883bcf680dd97849bda62efa66a5cef3376f3b917f9` |
| `/tmp/bb_pivot_boundary_REPORT.md` | `tmp_research_archive_20261022/reports/bb_pivot_boundary_REPORT.md` | 10013 | `b3308f7cde64b13b76fe5b2fe67af55899cba92f5a6338ebae8e1b80901fb9dd` |
| `/tmp/bb_width_out.md` | `tmp_research_archive_20261022/reports/bb_width_out.md` | 20907 | `846e2f572b2915fc0d6823a92e2db36fbaaa414cb8f733c2d5de27d47b9b5b51` |
| `/tmp/bounce_reversal_report.md` | `tmp_research_archive_20261022/reports/bounce_reversal_report.md` | 7473 | `1c35b836f7b8440a9463b7017b5858e79c3fbf563fa4e645c6817b93fe1a1ff1` |
| `/tmp/briefing_exec_part1_2026-05-13.md` | `tmp_research_archive_20261022/reports/briefing_exec_part1_2026-05-13.md` | 27406 | `e8241da76383b9fd934d8be131b62fdf38d09b96c9752f858a2ca0432200ff39` |
| `/tmp/calendar_session_results.md` | `tmp_research_archive_20261022/reports/calendar_session_results.md` | 10576 | `54fc33574f10f8bf640fafeedecbc127794f8f5c0a68b39bfe962a91b0e572fb` |
| `/tmp/carve_out_adx_override.md` | `tmp_research_archive_20261022/reports/carve_out_adx_override.md` | 2901 | `1d06b85ab02f2ebcebc2d899844e47c17ef63db85833e6741d8e6576b9324343` |
| `/tmp/carve_out_drift.md` | `tmp_research_archive_20261022/reports/carve_out_drift.md` | 8748 | `84023ff33604c592a314ce60c90a67c007020dbf8ef38c8a1642408df0f8b305` |
| `/tmp/carve_out_htf_exempt.md` | `tmp_research_archive_20261022/reports/carve_out_htf_exempt.md` | 5403 | `b99821578d704b4f581c8df7610840fa8e0fce192e36343e170723fec1fa1eee` |
| `/tmp/carve_out_structure_lead.md` | `tmp_research_archive_20261022/reports/carve_out_structure_lead.md` | 12136 | `23fda1d455921fa69cf646af0130251c0c107583c564798d367a2ce51930e83f` |
| `/tmp/carve_out_trend_confirmed.md` | `tmp_research_archive_20261022/reports/carve_out_trend_confirmed.md` | 4825 | `b1f4b6513f6cdc34923dcb0479b7e0fdbbb384141587789ef22c448b24605c69` |
| `/tmp/combinations_and_trend_v3_comparison.md` | `tmp_research_archive_20261022/reports/combinations_and_trend_v3_comparison.md` | 6013 | `35aed06e1adcc8ada2bc61440310d91faac8e3075ff45e37b9fdb62feca26de1` |
| `/tmp/correction_body.md` | `tmp_research_archive_20261022/reports/correction_body.md` | 22613 | `6acf532e513c29df1364803b4e2f1e3af083d2e4702a213f7bff62e405d2f5ba` |
| `/tmp/day_type_audit.md` | `tmp_research_archive_20261022/reports/day_type_audit.md` | 22061 | `0283ec59b8eb1232cc20e0dc95f92d4f06e14d20ac4d11103a1264705993e89f` |
| `/tmp/dead_flags_audit_20260823.md` | `tmp_research_archive_20261022/reports/dead_flags_audit_20260823.md` | 32129 | `abaa5e419670fad2446f4f1ee550179fa1cd94ae64fb1e3817ca57c32467ecd1` |
| `/tmp/dead_flags_audit_20260823_addendum.md` | `tmp_research_archive_20261022/reports/dead_flags_audit_20260823_addendum.md` | 47145 | `0152e8392faf7ba56c60b827acb12c7b521a1224d196b20791a5c04fc98d2df3` |
| `/tmp/discriminator_report.md` | `tmp_research_archive_20261022/reports/discriminator_report.md` | 3822 | `6bd15cd82f6c7e4ff9cd033e736a0cf807ac56e27d93b37dfa45d864b79331bf` |
| `/tmp/exec.md` | `tmp_research_archive_20261022/reports/exec.md` | 10637 | `1e33f328e46a0002159e6a74f3341b8ed497a5c67ef09e207a3e28b7a9f653aa` |
| `/tmp/h1_h2_results.md` | `tmp_research_archive_20261022/reports/h1_h2_results.md` | 2621 | `0fe089097b46c0cfdfb470022b69cc9c23df518c3a8aa98dbbd7a0b7da355369` |
| `/tmp/h1_pierce_BUILD_REPORT.md` | `tmp_research_archive_20261022/reports/h1_pierce_BUILD_REPORT.md` | 12243 | `24f95d1b20ebccdfb774cc7a2f966604351dd8c4e68b145bbc598a57a8f3fb1a` |
| `/tmp/launches_table.md` | `tmp_research_archive_20261022/reports/launches_table.md` | 10571 | `3dd6dbc366e87935f3f9fb0ecdfcc4193992cd95a853f4f6ee3374dabf2496e2` |
| `/tmp/live_brief.md` | `tmp_research_archive_20261022/reports/live_brief.md` | 6498 | `0ccd20676bfdd5a6d0a71f7d0bcf2cd150871017eac737f233af0348c260741a` |
| `/tmp/master_spec_20260911.md` | `tmp_research_archive_20261022/reports/master_spec_20260911.md` | 87038 | `10882c5f1047eae096fe55c3e2bb92bc8e75aa581168e22e4d7380a6cd19d8e7` |
| `/tmp/mode_ab_3day.md` | `tmp_research_archive_20261022/reports/mode_ab_3day.md` | 2276 | `adb26c0856ed2aeb4c96191f40ecd9a95527ae87c72dad9b022c11c5e1f94a56` |
| `/tmp/mode_abc_pilot.md` | `tmp_research_archive_20261022/reports/mode_abc_pilot.md` | 2969 | `04eb5539af54ac6b5474f1e3d22171f4ce5d8ef60a529ab3c53123c87f966912` |
| `/tmp/monday_restore_readback.md` | `tmp_research_archive_20261022/reports/monday_restore_readback.md` | 14042 | `d16ea23ef666edfccfdd1b49dd4cb348bd17bf509ae61a8dad6dd48c79f85528` |
| `/tmp/outer_fade_correction.md` | `tmp_research_archive_20261022/reports/outer_fade_correction.md` | 8814 | `3035a5b0b2fcd31ff2e1f3e52877baa32a8bf2c2040c1ee329761d039cdad4f3` |
| `/tmp/outer_fade_report.md` | `tmp_research_archive_20261022/reports/outer_fade_report.md` | 16270 | `f7e1b4cff5aee5d4ef2ab8f470023257dfe1dff4bf118949bda58ded5956fee1` |
| `/tmp/pass_a_report.md` | `tmp_research_archive_20261022/reports/pass_a_report.md` | 13668 | `501415f2a63799f5c9c429d4341feb1edbacc7b6c74128e2ca8dd040dc643cc6` |
| `/tmp/pass_b_report.md` | `tmp_research_archive_20261022/reports/pass_b_report.md` | 16630 | `5a9a7bd65900b7740d80b455dca8091673f44c340eb822c386a4c47ff2624e98` |
| `/tmp/phase6_original.md` | `tmp_research_archive_20261022/reports/phase6_original.md` | 3047 | `2399135fdc59a432f01b7421bece023c13b7f33cad8a4b83820f47f09f873be1` |
| `/tmp/pia_part2_2026-05-13.md` | `tmp_research_archive_20261022/reports/pia_part2_2026-05-13.md` | 38699 | `e5f5f6005306964845c75767656810c0049414834849dcc3ca26ed2bfe970112` |
| `/tmp/picks_disposition_report.md` | `tmp_research_archive_20261022/reports/picks_disposition_report.md` | 8703 | `70f3162c52e332e42c25772c762e6e90063da85909e76fde290328dcbcd5780f` |
| `/tmp/pivot_break_sweep_report_20260812.md` | `tmp_research_archive_20261022/reports/pivot_break_sweep_report_20260812.md` | 11285 | `5eb9ef7e677c6ab42b5cbcb361aad9980b6f290d4bc81de1f771d7ffb8fca8e3` |
| `/tmp/pivot_derivation_report_20260812.md` | `tmp_research_archive_20261022/reports/pivot_derivation_report_20260812.md` | 10402 | `2bc9279cfe609d73a1314ba93508d499cd5baead694f7854aa6242baecaabd58` |
| `/tmp/pivot_moves_REPORT.md` | `tmp_research_archive_20261022/reports/pivot_moves_REPORT.md` | 9893 | `c20e8acbcb41de121ef472a9109b1b5da8a5d9893ed9c086fab6e0cedfb3861e` |
| `/tmp/pivot_scale_REPORT.md` | `tmp_research_archive_20261022/reports/pivot_scale_REPORT.md` | 13161 | `869277d046634e99459ecaf6553a481d0d052c90b5c6e487e14bc43cb1775d79` |
| `/tmp/qm_reversal_demo_activation_plan.md` | `tmp_research_archive_20261022/reports/qm_reversal_demo_activation_plan.md` | 25451 | `7c12b323027d7c471f08953febebe1aaa51046a34553f8b8fd06d6c3eb5ce4f4` |
| `/tmp/qm_shadow_report_20261019.md` | `tmp_research_archive_20261022/reports/qm_shadow_report_20261019.md` | 1998 | `0191e94e1b4f42ef3fb23ba3fab045a37509f59037bac75abc61ad4b6327302a` |
| `/tmp/qm_v2_audit.md` | `tmp_research_archive_20261022/reports/qm_v2_audit.md` | 17290 | `47e865c5521a39d152248382ca06ebf61ac963ed0c18e0ed06a8584d9d266210` |
| `/tmp/report_header.md` | `tmp_research_archive_20261022/reports/report_header.md` | 7787 | `9ec45d64b04494315e316494c569c4b58135f0ed6af508ee99ee35055472a2fa` |
| `/tmp/single_feature_results.md` | `tmp_research_archive_20261022/reports/single_feature_results.md` | 8685 | `10e60eaf8f5678680d32a3afc36e68a31201d3fdad52aa268f32b272ef603d17` |
| `/tmp/slr_diag_report.md` | `tmp_research_archive_20261022/reports/slr_diag_report.md` | 45802 | `ebad5ed2df218a9d7a8cc127fb21e19581f0a28da8afee110aaf34d230757c17` |
| `/tmp/slr_v3_summary.md` | `tmp_research_archive_20261022/reports/slr_v3_summary.md` | 1540 | `8465500b485c287c61ced7cd84d0e587adf119578f93a135e49441303931c8a3` |
| `/tmp/slr_v3b_summary.md` | `tmp_research_archive_20261022/reports/slr_v3b_summary.md` | 1534 | `7bf4cb8c76e850e74d4a1ee08c05693c4e870498ed6ed847cd569a0d5e0431ed` |
| `/tmp/slr_v4_summary.md` | `tmp_research_archive_20261022/reports/slr_v4_summary.md` | 4511 | `98cae29b733212ed69fff43d850f62e8bd450e2434e3cb64b835509ecd806d54` |
| `/tmp/spec.md` | `tmp_research_archive_20261022/reports/spec.md` | 6534 | `a6c15e63a17eb150add5f77f00c7b5844080423c78a1982410ed4eaf5bda1ba7` |
| `/tmp/stage0_report.md` | `tmp_research_archive_20261022/reports/stage0_report.md` | 28855 | `84e0f6968238f54815cea11a8882e879e992817e736c94b90910260ffe422a93` |
| `/tmp/stage5_runbook.md` | `tmp_research_archive_20261022/reports/stage5_runbook.md` | 3831 | `3ee7af0048832e59e43f407c2c7586fd5ac1b3fff43cf5589f1ebc98c463a365` |
| `/tmp/stage6_runbook.md` | `tmp_research_archive_20261022/reports/stage6_runbook.md` | 3750 | `947794978db4274aaf563a178abc17f72a7a45c7fbcdfd82167b037d54040443` |
| `/tmp/stage7_runbook.md` | `tmp_research_archive_20261022/reports/stage7_runbook.md` | 6130 | `a9af773eb7dcc6c36e25378da76631838885dea98b4668b9f84063acd2369a3e` |
| `/tmp/stage7a_exec.md` | `tmp_research_archive_20261022/reports/stage7a_exec.md` | 3328 | `13d5bdf77cacdf03c0a37df1387a8b8db55098b8317f02f16295893f6f40925e` |
| `/tmp/stage7b.md` | `tmp_research_archive_20261022/reports/stage7b.md` | 3630 | `245910d5afaba35fe2731acf53dd402700d7832ea55eddc74d63d10dca46ea89` |
| `/tmp/stage7b2.md` | `tmp_research_archive_20261022/reports/stage7b2.md` | 5222 | `9896105416b48a506978c708b75a2c2ac7b8956c79bee84a0e6ad0ce7eea2a8f` |
| `/tmp/stage7bA1.md` | `tmp_research_archive_20261022/reports/stage7bA1.md` | 4021 | `04da16acfe15016b1a93384294d06d57539d60fa689e06412bd9418793fd62d6` |
| `/tmp/stage7bS.md` | `tmp_research_archive_20261022/reports/stage7bS.md` | 4329 | `e9776852c4702d3c6398a86abbc03ef925c3f4b84a4f820834b00bd594527c7d` |
| `/tmp/three_leg_report_body.md` | `tmp_research_archive_20261022/reports/three_leg_report_body.md` | 25620 | `560a02adebeedf6d2812cccca1afd93b29077a14440d4497a1307e5f72c5f2ca` |
| `/tmp/trend_ground_truth_summary.md` | `tmp_research_archive_20261022/reports/trend_ground_truth_summary.md` | 6101 | `6f05db07e93d419285ed23828f701ab74ea307367dde84f1840f4e1ef7a10e42` |
| `/tmp/trend_v3_vs_nms_cohort.md` | `tmp_research_archive_20261022/reports/trend_v3_vs_nms_cohort.md` | 6911 | `2320fc8faa89e4bd5215d27818c04ae447cac605b686c55d4bcda690d3c23d1f` |
| `/tmp/v3_replay_report.md` | `tmp_research_archive_20261022/reports/v3_replay_report.md` | 14952 | `f619d5af7a391e4dcf82ce6384e91a7443c3f2512bb8155ef47c8456b68250e4` |
| `/tmp/v6_summary.md` | `tmp_research_archive_20261022/reports/v6_summary.md` | 3184 | `bbf1ba2e368448244bbfec78af2173833a36b9cf600915109ddfe3754b4a37a7` |
| `/tmp/v8_summary.md` | `tmp_research_archive_20261022/reports/v8_summary.md` | 2829 | `121a13c13cb9a9e6503681e75ffc5887522a48937ff91e5dfda1d6ee84989bfc` |
| `/tmp/v9_disc.md` | `tmp_research_archive_20261022/reports/v9_disc.md` | 7552 | `2121c3647ba923e73108008c0b0ce690721ef1ac024ed1c8568710c3d138bd45` |
| `/tmp/FINDINGS.txt` | `tmp_research_archive_20261022/text_reports/FINDINGS.txt` | 6016 | `5614af76d0899c4a77ac3c8786e049732c49580d6fe92d12acab66cfa97387c0` |
| `/tmp/_3c_day_type_recut_report_20260813.txt` | `tmp_research_archive_20261022/text_reports/_3c_day_type_recut_report_20260813.txt` | 16005 | `d39df37ca81f3a9be8eac7b3d5e27c215bcb6009e4b380227eb2c654ef5a3ea2` |
| `/tmp/_3c_level_bounce_report_20260813.txt` | `tmp_research_archive_20261022/text_reports/_3c_level_bounce_report_20260813.txt` | 16122 | `372f71454ed73abd0192d58fabe2ac7ea95637f773931ef426f8ce9d343e50fb` |
| `/tmp/_lb_concurrency_report_20260813.txt` | `tmp_research_archive_20261022/text_reports/_lb_concurrency_report_20260813.txt` | 11444 | `c2a1841829167f08f952ffc8683b53da1c6eeb629e293cf1758685e8d6f8b4f4` |
| `/tmp/audit_2026-04-29_full.txt` | `tmp_research_archive_20261022/text_reports/audit_2026-04-29_full.txt` | 50398 | `74338fbf2284372def53d0e86b874c3b00e30d16b899eb6ee992b6e3f9bfee72` |
| `/tmp/bignews_report.txt` | `tmp_research_archive_20261022/text_reports/bignews_report.txt` | 94077 | `8c40df281e1ede348a11f35252dac009bfc4b36561ad8bcf5c2e81e4f7c1cad8` |
| `/tmp/c_timeline.txt` | `tmp_research_archive_20261022/text_reports/c_timeline.txt` | 55368 | `931fc175f653c8c66496d09f710f9ffb8b1b006ad360be8201f1080480bc1f84` |
| `/tmp/confluence_map_report.txt` | `tmp_research_archive_20261022/text_reports/confluence_map_report.txt` | 28292 | `522641ce2e79b5916c422664b65678192c7a5dd74d410db568f4fba845c343f4` |
| `/tmp/final_report.txt` | `tmp_research_archive_20261022/text_reports/final_report.txt` | 7848 | `366752538716d50dddba05e7ba073a1101a6fc92f332315ddc2b10c5cf11de14` |
| `/tmp/pierce_coincidence_entry_report.txt` | `tmp_research_archive_20261022/text_reports/pierce_coincidence_entry_report.txt` | 8747 | `a4530e6e9ae92eaeb1be19889d17d6b6464540de0a6c1f92eea583fdcddf5ccc` |
| `/tmp/pivot_rsi_report.txt` | `tmp_research_archive_20261022/text_reports/pivot_rsi_report.txt` | 19606 | `56ccf30ffa44f7fc972c24c96617fb7f611f0d0ad36286714c780fa0295de9f3` |
| `/tmp/pn_report.txt` | `tmp_research_archive_20261022/text_reports/pn_report.txt` | 16071 | `a40071c56f5d9230a7214bbda01822903bd6f44bf678b3244f38e8b18f20ad68` |
| `/tmp/report_stats.txt` | `tmp_research_archive_20261022/text_reports/report_stats.txt` | 6341 | `782297bc015397a11075a808ae0a109fe65dfdfccf7ad4742f3e416998f6d705` |
| `/tmp/report_v2_stdout.txt` | `tmp_research_archive_20261022/text_reports/report_v2_stdout.txt` | 5563 | `a25e8343351d84feeae6d5e8878e5166b8f785e31886171c4e59e9db11368ed8` |
| `/tmp/stage2_report.txt` | `tmp_research_archive_20261022/text_reports/stage2_report.txt` | 8908 | `d93dd8d654db808362293a868dbb10ebf0b0af166cb34e384205b77f2591dada` |
| `/tmp/trace_report.txt` | `tmp_research_archive_20261022/text_reports/trace_report.txt` | 14100 | `f437a99535108e8616e12839a1887daf1a16623e99d8a6c4c8a377150bc67e8f` |
| `/tmp/audit_2026_04_30.py` | `tmp_research_archive_20261022/code/audit_2026_04_30.py` | 22935 | `808a2118df2827de702662c6d47277395a54cb46f3f70636a2a9d1c8090a1cb1` |
| `/tmp/audit_bb_pierces.py` | `tmp_research_archive_20261022/code/audit_bb_pierces.py` | 10722 | `5de388c30a611b396c65fe862a81d2b07d1c4137bdd07cd54c267bd10c895be9` |
| `/tmp/audit_bbpr_2026-05-01.py` | `tmp_research_archive_20261022/code/audit_bbpr_2026-05-01.py` | 8982 | `2ccf6eec2663996e3e61d69bb83ec897c3b9231d3bf8b438f80781bb0f0ce1f8` |
| `/tmp/audit_csv_summary.py` | `tmp_research_archive_20261022/code/audit_csv_summary.py` | 5735 | `2348161cd20690b467e5c56f3945d9c6b108f99a5758cc90ec60129f6ae7fc92` |
| `/tmp/audit_full_month.py` | `tmp_research_archive_20261022/code/audit_full_month.py` | 10623 | `61af1e70cb5c0ba176e0ee6e37aa37bb7145e7cc7f42f751d320bbe086a9fe1c` |
| `/tmp/audit_funnel.py` | `tmp_research_archive_20261022/code/audit_funnel.py` | 4500 | `2a8d7b7510cba9fb1dc1ddaac6fbe22ca54d560611dbba0af711a38fce9ba3f3` |
| `/tmp/audit_recon.py` | `tmp_research_archive_20261022/code/audit_recon.py` | 4916 | `070ee994f5a629720e3da4e5fa7672d922b531726826928c01cb035e811414d9` |
| `/tmp/audit_runs.py` | `tmp_research_archive_20261022/code/audit_runs.py` | 11750 | `81f4070341df6eb59543876d1323152bdb5d4326b44018c3d7f57436d706cb8a` |
| `/tmp/audit_s2.py` | `tmp_research_archive_20261022/code/audit_s2.py` | 5074 | `56c939e4f635a34a8e0c7a2e5997d458a3860e6cccc811733ed2ad0ce6cfe44d` |
| `/tmp/audit_s2b.py` | `tmp_research_archive_20261022/code/audit_s2b.py` | 4181 | `8ef1db2c78185fdad58c423decad72abd3df58cc75e5087112c9014ad88a4690` |
| `/tmp/audit_s3.py` | `tmp_research_archive_20261022/code/audit_s3.py` | 3635 | `3051ffaac65069bad92acc5521c0528499713574a1fee4b71e6196ea67d5108b` |
| `/tmp/audit_s4.py` | `tmp_research_archive_20261022/code/audit_s4.py` | 6181 | `504d399633f3029b029e34c6d9eb01662edc66a5b9faa4061e49bdbf6e46ce5c` |
| `/tmp/audit_s4b.py` | `tmp_research_archive_20261022/code/audit_s4b.py` | 6383 | `a3af7d188e21c7b6c94d3393b4f420db9a55b677071c035cfe0af579655fff45` |
| `/tmp/audit_s5.py` | `tmp_research_archive_20261022/code/audit_s5.py` | 10178 | `fbd08b7614b55de309512bbce744bc1b499627577679b423357f631d64c554f5` |
| `/tmp/audit_s6.py` | `tmp_research_archive_20261022/code/audit_s6.py` | 3957 | `735ee2ae9858329cfe5807c044a22b348cf57d78a9109b902c2b4a250336179d` |
| `/tmp/audit_trend_v3.py` | `tmp_research_archive_20261022/code/audit_trend_v3.py` | 22489 | `beab183b94532f75f4f7acd6a0ca62c1139efd113ce7116d7f3af249bc1fd2cf` |
| `/tmp/bb_approach_report.py` | `tmp_research_archive_20261022/code/bb_approach_report.py` | 19440 | `6412df53751df6ca3c1d9ea5cf40f0370d9c2594075d5666e1967ac9fb3fd17e` |
| `/tmp/bb_band2outer_report.py` | `tmp_research_archive_20261022/code/bb_band2outer_report.py` | 7459 | `5de027239599ace75447595bd52a520ea1acb9ffb29de4a7f83643bc22ceb639` |
| `/tmp/bb_cluster_analysis.py` | `tmp_research_archive_20261022/code/bb_cluster_analysis.py` | 30298 | `1efe00218c8d05827d6970ba0bf060055d688de60926b6d0a80a8c1bf4890068` |
| `/tmp/bb_three_legs_audit.py` | `tmp_research_archive_20261022/code/bb_three_legs_audit.py` | 14889 | `bc3c39c9060b5c7917fc97423d0133629685d9673546d99a9972b03d9e106753` |
| `/tmp/bbpr_feature_analysis.py` | `tmp_research_archive_20261022/code/bbpr_feature_analysis.py` | 23882 | `51119ae93b634ebf2b49741eb32d58cde9fcd3e129feb7c951a8b67bd894db94` |
| `/tmp/A6_replay_20261007.json` | `tmp_research_archive_20261022/results/A6_replay_20261007.json` | 23913 | `b662e7917b816fd725026b4e77fbeb19455ddf3290c616edf6b45cb44224634e` |
| `/tmp/_3c_day_type_recut_results_20260813.json` | `tmp_research_archive_20261022/results/_3c_day_type_recut_results_20260813.json` | 887176 | `be7b331a81bdb52d5f1c4cedfb4310035fa0e5484820b67520defff0479b959b` |
| `/tmp/_3c_level_bounce_results_20260813.json` | `tmp_research_archive_20261022/results/_3c_level_bounce_results_20260813.json` | 1642764 | `94df5d1587cec2ea73c17522e6004a78d12818aafa3c7064c2767bdee24fa510` |
| `/tmp/_lb_concurrency_results_20260813.json` | `tmp_research_archive_20261022/results/_lb_concurrency_results_20260813.json` | 508119 | `54c640a783a774f651c08bff8fc4b3a3fd5994ec8098e4e261b33d35b283bc3c` |
