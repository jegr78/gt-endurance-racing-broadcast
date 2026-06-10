# Changelog

## [1.2.2](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v1.2.1...v1.2.2) (2026-06-10)


### Bug Fixes

* **cli:** force UTF-8 console output (Windows cp1252 + Linux C-locale) ([#24](https://github.com/jegr78/IRO_Broadcast_Setup/issues/24)) ([#28](https://github.com/jegr78/IRO_Broadcast_Setup/issues/28)) ([fdfbb2c](https://github.com/jegr78/IRO_Broadcast_Setup/commit/fdfbb2c4723f11cf58ca9fbe2f17ca17f32956c8))
* **relay:** hide console windows for relay-spawned children on Windows ([#30](https://github.com/jegr78/IRO_Broadcast_Setup/issues/30)) ([#31](https://github.com/jegr78/IRO_Broadcast_Setup/issues/31)) ([bae3bda](https://github.com/jegr78/IRO_Broadcast_Setup/commit/bae3bda67b81c604b3dcd7e80b3232c04bc928ce))
* **relay:** swallow benign client disconnects instead of crashing ([#25](https://github.com/jegr78/IRO_Broadcast_Setup/issues/25)) ([#29](https://github.com/jegr78/IRO_Broadcast_Setup/issues/29)) ([a740fed](https://github.com/jegr78/IRO_Broadcast_Setup/commit/a740fed4d3061f0a9f7eed1f395cd4137a2a8e51))
* **ui:** resolve real folder out of macOS App Translocation ([#22](https://github.com/jegr78/IRO_Broadcast_Setup/issues/22)) ([#26](https://github.com/jegr78/IRO_Broadcast_Setup/issues/26)) ([fd604ed](https://github.com/jegr78/IRO_Broadcast_Setup/commit/fd604ed90138816128d8c024f1b8b1c685dfbf43))
* **ui:** stop Windows console-window flicker in the windowed app ([#23](https://github.com/jegr78/IRO_Broadcast_Setup/issues/23)) ([#27](https://github.com/jegr78/IRO_Broadcast_Setup/issues/27)) ([d306561](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d30656146e891f65bbd9620be0084c1e102efa8d))

## [1.2.1](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v1.2.0...v1.2.1) (2026-06-08)


### Bug Fixes

* **update:** install the iro-ui launcher alongside iro on self-update ([#19](https://github.com/jegr78/IRO_Broadcast_Setup/issues/19)) ([b47fd94](https://github.com/jegr78/IRO_Broadcast_Setup/commit/b47fd949e4ef74a7ad9988b017099b9610f90485))

## [1.2.0](https://github.com/jegr78/IRO_Broadcast_Setup/compare/v1.1.0...v1.2.0) (2026-06-08)


### Features

* auto-refresh OBS browser sources when relay pages change ([#17](https://github.com/jegr78/IRO_Broadcast_Setup/issues/17)) ([445c418](https://github.com/jegr78/IRO_Broadcast_Setup/commit/445c4182b0248ed0ec86f1ebd724fc69212f353f))
* **event:** director_urls helper for the share-with-directors block ([9ab30b8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9ab30b853f42b60e8a03334930d227f66df43865))
* **init:** step kind/op table for the Control Center wizard ([3509568](https://github.com/jegr78/IRO_Broadcast_Setup/commit/35095681b35d6e25a255ca3ce9a8e1401100e984))
* intra-wiki link/anchor checker, gated through the test suite ([78439e9](https://github.com/jegr78/IRO_Broadcast_Setup/commit/78439e979b7be8cef84860ff5ba0bda15a48f664))
* **iro:** cookies + sheet-asset readiness as structured data ([7d96803](https://github.com/jegr78/IRO_Broadcast_Setup/commit/7d968032ad083d7ac200dd150f617285485d8357))
* **iro:** event start prints share-with-directors URL block ([526dfb3](https://github.com/jegr78/IRO_Broadcast_Setup/commit/526dfb310d63a08a6a287eedacf12afe949b074a))
* **iro:** local graphics/media file listing provider + ctx asset roots ([7a11628](https://github.com/jegr78/IRO_Broadcast_Setup/commit/7a1162853ab047831f2e127c9a58f7c716bbebcc))
* **iro:** OBS/Discord running-state in the status poll (Event overview) ([ecf6d92](https://github.com/jegr78/IRO_Broadcast_Setup/commit/ecf6d9248c1e7ac4e39082d7b9c5b439f83c1d1a))
* **iro:** read/write .env as validated entries (Settings editor backend) ([ee5c1ec](https://github.com/jegr78/IRO_Broadcast_Setup/commit/ee5c1ec95d2ffa26d7362abb3abfecc778c6ecc4))
* **iro:** structured tools/apps/preflight readiness providers ([48c4b34](https://github.com/jegr78/IRO_Broadcast_Setup/commit/48c4b34b5559d2c0ecf317876e359ff2c54e2075))
* **iro:** ui subcommand — local Control Center server (IRO_UI_PORT, single-instance probe) ([bcfa06b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/bcfa06bf983019d06b22bc864705e07a16ee9bd4))
* **panel:** confirm on RELOAD, NEXT double-press guard, FEEDS → STINT… rename ([c8d394c](https://github.com/jegr78/IRO_Broadcast_Setup/commit/c8d394c52df863dfd5603e1a97d1898704421705))
* **panel:** feed health pills + FEEDS health line; relay/cookie state banners ([bf9aa85](https://github.com/jegr78/IRO_Broadcast_Setup/commit/bf9aa8573991da54f6f7b0056c961eba7743491e))
* **panel:** state-banner + toast plumbing; toasts on action failures; sync banners ([4aa9ab9](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4aa9ab9d93c99582a335ec5e389bf83fe63630d4))
* **preflight:** Google Sheet readability check + clearer port-in-use hint ([668d562](https://github.com/jegr78/IRO_Broadcast_Setup/commit/668d562d5e5a09f16e054d056cedd916cbb470a3))
* refuse to publish the wiki over broken intra-wiki links ([cb442e8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/cb442e87673a21263d70faf9fe3b1ed419851aea))
* **relay:** /status carries feed state + state_age_s + last_error and cookies_health ([ad73037](https://github.com/jegr78/IRO_Broadcast_Setup/commit/ad73037b05c532fdd8fd1761c7f03eb4da825a2f))
* **relay:** cookie_health() — on-demand cookie staleness (12 h, mirrors preflight) ([87059bf](https://github.com/jegr78/IRO_Broadcast_Setup/commit/87059bfefc42ff4f9c3e7b62c60c267ec710cae0))
* **relay:** feed phase machine + yt-dlp error propagation (resolve_hls returns (url, error)) ([ed5d41e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/ed5d41effde67f1d344889ecf274d59de9713d3d))
* **relay:** startup WARN on stale cookies + actionable bind-failure message ([bf8830e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/bf8830e720b31e34d841c2f798c87a8efb4aa4fc))
* **ui:** /api/assets/files listing + path-safe asset file serving ([50f7235](https://github.com/jegr78/IRO_Broadcast_Setup/commit/50f7235d9a6298a545e7f399b3ea081745f5e969))
* **ui:** /api/init/plan + /api/init/step routes ([5f2c9de](https://github.com/jegr78/IRO_Broadcast_Setup/commit/5f2c9de4d2d925190dd005edbddc0538d69d0210))
* **ui:** auto-connect the Director panel to OBS from the Control Center ([419ab05](https://github.com/jegr78/IRO_Broadcast_Setup/commit/419ab0574c256c59d3b6954afdddb6c5bc02548a))
* **ui:** Control Center HTTP server — status API, job control, quit (ui_server) ([d6c944b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d6c944bdcc238df038e8cdfc13c943f3be279b5c))
* **ui:** Control Center page — dashboard, job log, service log tails ([b802c68](https://github.com/jegr78/IRO_Broadcast_Setup/commit/b802c68d0d6de83f8fb068f3379546f45893b63c))
* **ui:** event row, Setup & Assets section, job cancel button ([e49aa3d](https://github.com/jegr78/IRO_Broadcast_Setup/commit/e49aa3d8aff8dab9480072a188b71b62b8296736))
* **ui:** Event view becomes a live stack overview + Start/Stop ([4d4d6f4](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4d4d6f43a0f16342c3a9cee9ecf75b50c3b33d93))
* **ui:** expose init-wizard plan/step in the server ctx ([7bc82e9](https://github.com/jegr78/IRO_Broadcast_Setup/commit/7bc82e9ba84e603d851ace39cd9c1a7dc2721d0a))
* **ui:** GET/POST /api/env routes for the Settings editor ([498b20c](https://github.com/jegr78/IRO_Broadcast_Setup/commit/498b20c58e5713f1ff5be988e34e27e496aaa770))
* **ui:** Help & Docs view (cheat sheet, local READMEs, wiki links) ([8a0b47b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/8a0b47bc53586331d0b2a8e7440238ed8e0ac491))
* **ui:** Home dashboard, app-centric control, live relay stats, update check ([71a0cf2](https://github.com/jegr78/IRO_Broadcast_Setup/commit/71a0cf22220d06da8288aad7adb7ad42cdb952c4))
* **ui:** iro-ui windowed launcher entrypoint ([41ef4d5](https://github.com/jegr78/IRO_Broadcast_Setup/commit/41ef4d5db1def8b6dc5c3f7df20854e8d2c9bcee))
* **ui:** job cancellation (terminate direct child, cancelled flag) ([a08859e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/a08859e538019a9ea769b70371429001f1382503))
* **ui:** job manager — iro child processes with line buffer (ui_jobs) ([3b519d8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3b519d82abe162e2f8db683051f881d67b14a311))
* **ui:** native fatal-error dialog for the windowed launcher ([4a93bea](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4a93bea5b88da4c86e2bbfc3318806b7b984ee0b))
* **ui:** on-demand /api/setup + /api/preflight routes ([3b8d598](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3b8d59827e8794d1c2b8cc8e27212b9ad8e24600))
* **ui:** one-shot ops + validated params in the registry (build_argv) ([fa45f62](https://github.com/jegr78/IRO_Broadcast_Setup/commit/fa45f6213081a1ed459ad3a1798fff108d1472f9))
* **ui:** op params via JSON body, job cancel route, on-demand /api/assets ([f456b9b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/f456b9b13565667a8fb724a6e54a743da5cca9f5))
* **ui:** operation registry + child argv helper (ui_ops) ([2fc9b54](https://github.com/jegr78/IRO_Broadcast_Setup/commit/2fc9b54c3fe9a3ec3cccfeee5d7f0e5103c592f6))
* **ui:** ops-console visual design — status dots, SVG icons, mono data, job chips ([e920559](https://github.com/jegr78/IRO_Broadcast_Setup/commit/e920559c0dda09c4de82eb740955dadaa3c003e5))
* **ui:** per-item Tools/Apps status + Preflight checklist view ([3753016](https://github.com/jegr78/IRO_Broadcast_Setup/commit/375301635114bafb605e8105349da5cbc7dc0575))
* **ui:** rename Dashboard-&gt;Services below Event, Preflight on top, OBS pages onto OBS ([65bc2e1](https://github.com/jegr78/IRO_Broadcast_Setup/commit/65bc2e1b7c549118ea7010683d51010179e5b7c3))
* **ui:** render Help-page Markdown docs as styled HTML ([217ed74](https://github.com/jegr78/IRO_Broadcast_Setup/commit/217ed74267f7b7773b460e9b714c107584e66356))
* **ui:** Settings view — masked .env key/value table editor ([782e5c9](https://github.com/jegr78/IRO_Broadcast_Setup/commit/782e5c98bbde0fc71924a07068953f0550ae1fc1))
* **ui:** Setup wizard view driving init steps ([f0a48dc](https://github.com/jegr78/IRO_Broadcast_Setup/commit/f0a48dc479c08a4b9fff334e6ef9ae5c8fcc80a6))
* **ui:** shareable Companion/Director-panel links + clearer Companion note ([78b039b](https://github.com/jegr78/IRO_Broadcast_Setup/commit/78b039be0e04a819db1cd1da4973e9c1f49b2370))
* **ui:** sidebar navigation + docked console (declutter, fix job-panel placement) ([9bff8d6](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9bff8d69e70875b84db6b3861ca376637691a9f4))
* **ui:** split nav into Dashboard/Preflight/Event/Apps/Tools/Assets/Logs + asset previews ([3478b11](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3478b110c11259b429294c4769f2f46c12a7c64f))
* **ui:** Static Streams page, uniform app start/stop, visible update check ([77ad4f1](https://github.com/jegr78/IRO_Broadcast_Setup/commit/77ad4f144bd188142706fe3d5adae5a70d3d572a))
* **ui:** structured init-wizard plan + action providers ([b58b2f7](https://github.com/jegr78/IRO_Broadcast_Setup/commit/b58b2f70d0d44bcd9fb03cd89998199831ee4404))
* **ui:** tailscale up/down buttons on the dashboard ([9cba973](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9cba973f23c77a681be659bbb4d000284e95d8cb))
* **ui:** wizard progress summary + Re-check feedback ([460a52f](https://github.com/jegr78/IRO_Broadcast_Setup/commit/460a52f06d00fdf0d5e4bb95968e7e797a1cc0c9))


### Bug Fixes

* **build:** bundle src/ui into the binary + ui smoke coverage ([2176f59](https://github.com/jegr78/IRO_Broadcast_Setup/commit/2176f59adee8fb38688e17f2b238c78045cb74d1))
* **build:** bundle the Help-page docs into the binary ([cbeedf4](https://github.com/jegr78/IRO_Broadcast_Setup/commit/cbeedf41feca13a50fec121bd748a55c4fb5de61))
* **ci:** join sibling iro path with target separator, not host's ([d5f7c86](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d5f7c863c2c40fe351d8b893ce4e395f9ec6a526))
* **ci:** Windows path split, stub smoke marker, path-injection sanitizer ([3afd2ec](https://github.com/jegr78/IRO_Broadcast_Setup/commit/3afd2ec3681f7cbbce50ff850fd91f6b989661e1))
* **event:** plain-language Tailscale warning (drop 'tailnet IP' jargon) ([be00318](https://github.com/jegr78/IRO_Broadcast_Setup/commit/be0031881442a790ead2ad043a4a2ea8cf443dbf))
* **event:** wait for Companion before the readiness report ([4a9599e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4a9599e0d1bb2f248055d599283c279fe4d49e8f))
* **iro:** harden companion_status_data never-raises contract (review follow-up) ([d366e00](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d366e0089b5136b65b385a61d1056fbc0f3fe60a))
* **iro:** never-raise guard on cookies probe, guard event-module load (review) ([782260d](https://github.com/jegr78/IRO_Broadcast_Setup/commit/782260da2f4e2b3ee0a41864ee2bc5370163522f))
* **panel:** guard POV pill against missing state; reset stale pill class when POV disabled ([d5aeaab](https://github.com/jegr78/IRO_Broadcast_Setup/commit/d5aeaabb7303ea2cbf89d2344e3d4b2d6af3bcef))
* **preflight:** BOM-prefixed sign-in page no longer defeats the HTML sniff ([9394648](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9394648e73700d76a653cf59be2fb08e93630ac3))
* **relay:** cookie_health never raises when the cookies file vanishes mid-poll ([e370830](https://github.com/jegr78/IRO_Broadcast_Setup/commit/e370830849d2c7fd0b833a22a85eef65430c37df))
* **relay:** no-store on served panel/HUD/timer pages ([9382e74](https://github.com/jegr78/IRO_Broadcast_Setup/commit/9382e74387c663c9ecdf068598ae5523ff5b902d))
* **security:** use CodeQL-recognized path sanitizer for asset route ([51ecae2](https://github.com/jegr78/IRO_Broadcast_Setup/commit/51ecae289cf2d402438be528047c26aed57a11d3))
* **tests:** move ui_ops import to the top-of-file block (review follow-up) ([da42540](https://github.com/jegr78/IRO_Broadcast_Setup/commit/da42540f0a58f5e5a7bd2ada6fb5f46aff49cd6a))
* **ui:** ASCII-guard stint validation, explicit params default (review) ([e137c07](https://github.com/jegr78/IRO_Broadcast_Setup/commit/e137c0776030d39248b9b70f6b95fdf1a8ab023e))
* **ui:** guard empty route segments, JSON-safe status errors (review follow-up) ([0ffec88](https://github.com/jegr78/IRO_Broadcast_Setup/commit/0ffec88a53b5981613b9f5e2e819ad594bf0ccd8))
* **ui:** guard Save against re-entry + disabled-button styling (review) ([4aea040](https://github.com/jegr78/IRO_Broadcast_Setup/commit/4aea040ec95e95632f735cd5e9bbe5b21b21bf15))
* **ui:** resolve sibling iro + runtime/.env next to the macOS .app ([7148775](https://github.com/jegr78/IRO_Broadcast_Setup/commit/71487758c88e9143060a0f89410b0ea2d0aaff2c))
* **ui:** Tailscale start/stop, preflight ports as INFO, drop legacy notes ([14c6541](https://github.com/jegr78/IRO_Broadcast_Setup/commit/14c6541911c5c5a5d2b022675302ae3c2b97233b))
* **ui:** tool/app check error message spans the row (review) ([53260e2](https://github.com/jegr78/IRO_Broadcast_Setup/commit/53260e202e42917763c807ee18f309184578dce5))
* **ui:** unblock op on reader-thread start failure; pipe/locking hygiene (review follow-up) ([dcbf7e8](https://github.com/jegr78/IRO_Broadcast_Setup/commit/dcbf7e86ad4da2a942b03c09e617a378c55bf8f4))
* **ui:** wizard setup stays done across restarts; drop preflight step ([8f3b6de](https://github.com/jegr78/IRO_Broadcast_Setup/commit/8f3b6de11e8e66a165ac517a3341acbc10569bd8))
* **ui:** wizard updates on job completion; show run result not stuck pending ([c1f3d0e](https://github.com/jegr78/IRO_Broadcast_Setup/commit/c1f3d0e451051cb3f42237866e254e279d355741))

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
