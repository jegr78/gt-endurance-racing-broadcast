# Changelog

## [1.1.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v1.0.0...v1.1.0) (2026-06-07)


### Features

* panel sheet control — HUD/Schedule/POV writes, Race-Control combos, RED FLAG ([#16](https://github.com/jegr78/IRO_Broadcast_Setup/issues/16)) ([d420bdc](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d420bdc265d02c04c363125a3070eaab8c2851af))

## [1.0.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v0.4.0...v1.0.0) (2026-06-06)


### Features

* **install:** --update upgrades installed tools/apps; docs consistency pass ([499ec4d](https://github.com/jegr78/IRO_Broadcast_Setup/commit/499ec4d798da2af63bb03cf5ffed8038f3ecf348))
* **panel:** mixer-bus redesign — Companion-synced actions, relay feed control, dB audio ([a21c2e4](https://github.com/jegr78/IRO_Broadcast_Setup/commit/a21c2e41bfd7c2436e7436dfead9911f6be6d9cf))
* **timer:** relay-hosted race timer replaces stagetimer (director-controlled, handover-safe) ([7776e15](https://github.com/jegr78/IRO_Broadcast_Setup/commit/7776e1598d62d31de1779258d74dc4033ad1f4db))
* **timer:** stopwatch semantics — stop pauses, new reset; context-sensitive adjust ([c935a22](https://github.com/jegr78/IRO_Broadcast_Setup/commit/c935a2252f6ae31c9377302e02483861de4d42e7))


### Bug Fixes

* **panel:** audio sliders cover OBS's full -60..+26 dB range (parity with Companion VOL UP) ([453d8c4](https://github.com/jegr78/IRO_Broadcast_Setup/commit/453d8c41bc4e8a12dc5e176d4d7954f5c92d3cca))
* **panel:** refresh reentrancy guard, offline ON-AIR pill styling, instant mute feedback ([3b60fb7](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3b60fb77bba8a27cf76efdced4b754e9b8fe5eac))
* **relay:** explanatory comment in TimerStore makedirs except clause (CodeQL py/empty-except) ([f5a1f50](https://github.com/jegr78/IRO_Broadcast_Setup/commit/f5a1f50bfce34ce97ee796da84191468a8469031))
* **relay:** timer push success requires the webhook's {"ok":true} (Apps Script errors are HTTP 200) ([5b2d799](https://github.com/jegr78/IRO_Broadcast_Setup/commit/5b2d799e94a4339f2427de86b8b4f77a4fb7ee69))


### Miscellaneous Chores

* release 1.0.0 ([37ef7e8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/37ef7e83290a3e4d2b1856108bb37829a7fd5235))

## [0.4.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v0.3.0...v0.4.0) (2026-06-06)


### Features

* **init:** guided first-time setup wizard (iro init) ([0601326](https://github.com/jegr78/IRO_Broadcast_Setup/commit/0601326ba78430833416ca72751d8f84adbb6d3c))
* **tailscale:** connection-aware detection + iro tailscale up/down/status ([d89283e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d89283e18e06da6c17be9744d93b2b54c3d2962c))


### Bug Fixes

* clear the two remaining code-scanning alerts ([#12](https://github.com/jegr78/IRO_Broadcast_Setup/issues/12)) ([0934eb0](https://github.com/jegr78/IRO_Broadcast_Setup/commit/0934eb004e236d0937be534364426ac2dca2ae50))
* resolve all open CodeQL code-scanning alerts ([#10](https://github.com/jegr78/IRO_Broadcast_Setup/issues/10)) ([b507858](https://github.com/jegr78/IRO_Broadcast_Setup/commit/b507858aed3549afbbd3f931dc8a2732f9805a3c))
* **update:** offer the latest release on frozen dev binaries ([#13](https://github.com/jegr78/IRO_Broadcast_Setup/issues/13)) ([f785250](https://github.com/jegr78/IRO_Broadcast_Setup/commit/f7852501c72203041ae5d59ce6bb4d2bea268bae))

## [0.3.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v0.2.1...v0.3.0) (2026-06-05)


### Features

* **event:** iro event status/start/stop — event-day readiness check and bring-up ([62fa86d](https://github.com/jegr78/IRO_Broadcast_Setup/commit/62fa86d80904f4f5b2807a945dde5f5d4ec5ee9f))
* **relay:** producer handover — start at the stint on air ([1bd071b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/1bd071bac4a2692972284724c0ec9f5bdfb1f76f))


### Bug Fixes

* **event:** wait for launched services before the closing readiness report ([41d9353](https://github.com/jegr78/IRO_Broadcast_Setup/commit/41d93535f2747eba805afbe9d2634a6fd0cfc3d5))
* **stop:** release OBS feed connections so the feed ports tear down cleanly ([9b843b7](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9b843b71d1394f5575582265ff2532b329d37d0f))

## [0.2.1](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v0.2.0...v0.2.1) (2026-06-05)


### Bug Fixes

* **binary:** point SSL_CERT_FILE at the system CA bundle when the build paths are missing ([3a4eab0](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3a4eab08a92eb0cfa617cd42c0f7a3909c78ed9f))

## [0.2.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v0.1.0...v0.2.0) (2026-06-05)


### Features

* **ci:** automated release management via release-please ([077ec23](https://github.com/jegr78/IRO_Broadcast_Setup/commit/077ec23de398a3116bcbff2cfdd22df09ca95d2a))
* **export:** companion config defaults into runtime/ ([6678909](https://github.com/jegr78/IRO_Broadcast_Setup/commit/6678909a2689ac805fec0874d868b3e88f2ea4ff))
* **obs:** iro setup localizes the Discord audio source per platform ([4a2aec3](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4a2aec30f7099ade68dba3c4061d97256595e734))
* **obs:** platform-dependent Discord audio source transforms ([bcbdf1a](https://github.com/jegr78/IRO_Broadcast_Setup/commit/bcbdf1a9234b8f5bb6d195510a7208ac97fd97ea))
* **update:** self-updating binary via GitHub Releases ([2cbf78a](https://github.com/jegr78/IRO_Broadcast_Setup/commit/2cbf78a7604810b16436e8f518a0c61e49003c93))


### Bug Fixes

* **binary:** iro setup works frozen - bundle layout + _MEIPASS paths ([a78bb00](https://github.com/jegr78/IRO_Broadcast_Setup/commit/a78bb0013b7099410d4a8645c9a5d9897fbb02c1))
* **companion:** first launch starts Companion instead of erroring ([15c0048](https://github.com/jegr78/IRO_Broadcast_Setup/commit/15c0048346004b0550edd7bd5e3d0baafdd6d238))
* **cookies:** surface the real yt-dlp error + actionable hints ([362b59f](https://github.com/jegr78/IRO_Broadcast_Setup/commit/362b59f57adba2fafee75e9ff59fd47ce040eb93))
* **install-apps:** document IRO_COMPANION_EXE + detect OBS in (x86) ([8f10623](https://github.com/jegr78/IRO_Broadcast_Setup/commit/8f10623bf46cd7191fd9717d2f41180dfebfa5ee))
* **install-apps:** install Companion via winget --interactive ([72c29fc](https://github.com/jegr78/IRO_Broadcast_Setup/commit/72c29fc4c470b58f4f2ef9c1b6b26cc935550d2e))
* **install-tools:** winget already-installed codes + stale-PATH detection ([d6d30fd](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d6d30fd0c56113894865a9783097df6df15bdab5))
* **preflight:** RAM slack so nominal 16/32 GB machines classify right ([df061ed](https://github.com/jegr78/IRO_Broadcast_Setup/commit/df061ed89338507e80cdfdbcb93e9ce746e40ea3))
* **subprocess:** tolerate non-ANSI bytes in captured console output ([3edead8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3edead806bc20351350ad02b7eafe38d08b9fa53))
