MAIN
| workload | mode | ROI cycles median | min | max | cycles/lap | reduction vs NO-PREDICTION | ROI insts | checksum = NO-PRED | L1D read misses |
|---|---|---|---|---|---|---|---|---|---|
| stable | NO-PREDICTION | 34547 | 34547 | 34547 | 172.74 | - | 7248 | True | 800 |
| stable | LVP-ONLY | 24047 | 24047 | 24047 | 120.23 | 30.39% | 7248 | True | 800 |
| stable | V-ASTRA-ONLY | 5043 | 5043 | 5043 | 25.21 | 85.40% | 7248 | True | 0 |
| randbase | NO-PREDICTION | 35608 | 35608 | 35608 | 178.04 | - | 17793 | True | 800 |
| randbase | LVP-ONLY | 30620 | 30620 | 30620 | 153.1 | 14.01% | 17793 | True | 800 |
| randbase | V-ASTRA-ONLY | 18249 | 18249 | 18249 | 91.25 | 48.75% | 17793 | True | 205 |
| altvalue | NO-PREDICTION | 31344 | 31344 | 31344 | 156.72 | - | 9057 | True | 800 |
| altvalue | LVP-ONLY | 25944 | 25944 | 25944 | 129.72 | 17.23% | 9057 | True | 800 |
| altvalue | V-ASTRA-ONLY | 12819 | 12819 | 12819 | 64.09 | 59.10% | 9057 | True | 0 |
| vcmiss | NO-PREDICTION | 31144 | 31144 | 31144 | 155.72 | - | 11748 | True | 800 |
| vcmiss | LVP-ONLY | 24944 | 24944 | 24944 | 124.72 | 19.91% | 11748 | True | 800 |
| vcmiss | V-ASTRA-ONLY | 31144 | 31144 | 31144 | 155.72 | 0.00% | 11748 | True | 800 |

MECH
| workload | mode | mechanism counters in the ROI |
|---|---|---|
| stable | LVP-ONLY | LVP confident predictions 801, correct 800, incorrect 0, speculative loads issued 600, committed 600, recovery squashes 0 |
| stable | V-ASTRA-ONLY | V-ASTRA candidates 800, synthetic responses (memory requests suppressed) 800, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 0 |
| randbase | LVP-ONLY | LVP confident predictions 800, correct 800, incorrect 0, speculative loads issued 429, committed 429, recovery squashes 0 |
| randbase | V-ASTRA-ONLY | V-ASTRA candidates 595, synthetic responses (memory requests suppressed) 595, forwarded dependents 0, base wrong 205, V$ tag-miss fallbacks 0 |
| altvalue | LVP-ONLY | LVP confident predictions 600, correct 600, incorrect 0, speculative loads issued 400, committed 400, recovery squashes 0 |
| altvalue | V-ASTRA-ONLY | V-ASTRA candidates 801, synthetic responses (memory requests suppressed) 801, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 0 |
| vcmiss | LVP-ONLY | LVP confident predictions 800, correct 800, incorrect 0, speculative loads issued 600, committed 600, recovery squashes 0 |
| vcmiss | V-ASTRA-ONLY | V-ASTRA candidates 800, synthetic responses (memory requests suppressed) 0, forwarded dependents 0, base wrong 0, V$ tag-miss fallbacks 800 |

SENS
| workload | warm laps | ROI laps | NO-PRED cycles | LVP cycles (reduction) | V-ASTRA cycles (reduction) | same instruction count |
|---|---|---|---|---|---|---|
| altvalue | 0 | 200 | 31964 | 26672 (16.6%) | 13607 (57.4%) | yes |
| altvalue | 5 | 200 | 31344 | 25944 (17.2%) | 12858 (59.0%) | yes |
| altvalue | 20 | 200 | 31344 | 25944 (17.2%) | 12819 (59.1%) | yes |
| altvalue | 100 | 100 | 15694 | 12994 (17.2%) | 6419 (59.1%) | yes |
| altvalue | 100 | 200 | 31344 | 25944 (17.2%) | 12819 (59.1%) | yes |
| altvalue | 100 | 400 | 62644 | 51844 (17.2%) | 25619 (59.1%) | yes |
| altvalue | 100 | 800 | 125244 | 103644 (17.2%) | 51219 (59.1%) | yes |
| randbase | 0 | 200 | 36655 | 31771 (13.3%) | 19593 (46.5%) | yes |
| randbase | 5 | 200 | 35599 | 30639 (13.9%) | 18375 (48.4%) | yes |
| randbase | 20 | 200 | 35607 | 30619 (14.0%) | 18282 (48.7%) | yes |
| randbase | 100 | 100 | 17853 | 15341 (14.1%) | 8989 (49.6%) | yes |
| randbase | 100 | 200 | 35608 | 30620 (14.0%) | 18249 (48.8%) | yes |
| randbase | 100 | 400 | 71109 | 61175 (14.0%) | 36423 (48.8%) | yes |
| randbase | 100 | 800 | 142221 | 122303 (14.0%) | 72254 (49.2%) | yes |
| stable | 0 | 200 | 35087 | 24797 (29.3%) | 5844 (83.3%) | yes |
| stable | 5 | 200 | 34545 | 24050 (30.4%) | 5043 (85.4%) | yes |
| stable | 20 | 200 | 34547 | 24047 (30.4%) | 5043 (85.4%) | yes |
| stable | 100 | 100 | 17297 | 12047 (30.4%) | 2543 (85.3%) | yes |
| stable | 100 | 200 | 34547 | 24047 (30.4%) | 5043 (85.4%) | yes |
| stable | 100 | 400 | 69047 | 48047 (30.4%) | 10043 (85.5%) | yes |
| stable | 100 | 800 | 138047 | 96047 (30.4%) | 20043 (85.5%) | yes |
| vcmiss | 0 | 200 | 31950 | 25874 (19.0%) | 31950 (0.0%) | yes |
| vcmiss | 5 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 20 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 100 | 100 | 15594 | 12494 (19.9%) | 15594 (0.0%) | yes |
| vcmiss | 100 | 200 | 31144 | 24944 (19.9%) | 31144 (0.0%) | yes |
| vcmiss | 100 | 400 | 62244 | 49844 (19.9%) | 62244 (0.0%) | yes |
| vcmiss | 100 | 800 | 124444 | 99644 (19.9%) | 124444 (0.0%) | yes |
