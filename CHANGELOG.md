# Changelog

## [0.9.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.8.0...v0.9.0) (2026-06-21)


### Features

* **cli:** `racecast links` (Crew ∪ Schedule) + Crew Console ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 5) ([#231](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/231)) ([cd2586e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/cd2586e5044ab0de0ca5ee3bc6369362638fd8c0))
* **cli:** public Funnel mounts /console + `racecast funnel` command ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 4) ([#230](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/230)) ([e998d4b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e998d4b3c817bfe5940692f8b9479297d57974c8))
* **console:** Companion Web Buttons over the Funnel (/console/buttons) ([#241](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/241)) ([81e3a05](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/81e3a0570cefd6ec7de515570adc998a890fc430))
* **console:** Discord OAuth login for /console + cockpit→console rename ([#242](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/242)) ([f751e76](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/f751e766b34dde8d8a565ee5c11da513e9509d51))
* **console:** distribute the shared console link from Crew Console (Copy / Post to Discord) ([#249](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/249)) ([89439e5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/89439e597a5349ccb1937bb02f05aec076acd120))
* **console:** Race Control crew role — read-only monitoring desk ([#244](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/244)) ([#248](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/248)) ([7fe05c5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7fe05c554655af9f7202bcbc70bf0edd33fa5ead))
* **event:** producer takeover over the public Funnel ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216)) ([#234](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/234)) ([7901eca](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7901eca7d621b90ff982df0aa52daf0d461b22b5))
* **panel:** preview button on pending stream submissions ([#247](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/247)) ([48f892f](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/48f892f09e6d46f64b20bae1d7d18d037e18c663)), closes [#245](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/245)
* **panel:** relay-mediated OBS control — credential-free, Funnel-complete Director Panel ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216)) ([#238](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/238)) ([5cc7333](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/5cc733310ba4e11ac1fc13f94c214a2ae19eb613))
* **relay:** /console auth gate + role-gated API mirror ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 3a) ([#228](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/228)) ([d9c4cc5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/d9c4cc5538d1ce9628ab61582dba832efc246bd7))
* **relay:** /console authorization policy ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 2) ([#227](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/227)) ([3f62ed8](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/3f62ed8507e343c8732cd63b66ad57c290bd835a))
* **relay:** crew roster + role resolution ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 1) ([#226](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/226)) ([e7c5f2e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e7c5f2e6fcf1ba0af1a1d3a971848654d978122a))
* **relay:** director→talent text-cue channel (IFB-lite) ([#243](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/243)) ([#246](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/246)) ([06fcd90](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/06fcd90a647baa66291dbc61187603908d737e7f))
* **relay:** role-adaptive /console pages + launcher ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216) phase 3b) ([#229](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/229)) ([280d7ac](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/280d7acf89b9aee58221d4fc27e5ece56225672f))
* **ui:** Control Center crew editor for the Crew-tab roster ([#216](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/216)) ([#233](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/233)) ([7e7460a](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7e7460a6691cbbf6d350f2e6e59dd406488e1c6b))
* **ui:** optional "stop event" on Control Center quit, waiting for completion ([#221](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/221)) ([1766287](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/176628700f163a891d84e9fef5592620cd9434d0)), closes [#218](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/218)
* **ui:** replace native confirm()/alert() with custom Control Center modals ([#224](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/224)) ([42a1cae](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/42a1cae4a1030fd34d759d3b07a8cdf3018e0c6f))


### Bug Fixes

* **logs:** keep timestamped logging through a blocked Windows log rotation ([#223](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/223)) ([152f80a](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/152f80a8db915c749b92dd6f786d511ecdfed871))
* **relay:** resolve py/mixed-returns in do_GET/do_POST (CodeQL) ([#232](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/232)) ([1bab505](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1bab505aefce38121f7b70f7e9b0e93b7c064e09))
* **ui:** style Control Center event-title input (was browser default) ([#225](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/225)) ([37d7652](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/37d76526bb279c872bdbc2c57c0f7f35c325c9ca))
* **ui:** widen Crew editor actions column so Save/Delete fit the card ([#251](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/251)) ([27c50a6](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/27c50a6db0299a9f3813544c0208f892719b33a5))

## [0.8.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.7.0...v0.8.0) (2026-06-18)


### Features

* **cockpit:** Commentator Cockpit — talent monitor, tally, chat & timer ([#191](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/191)) ([75dafc6](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/75dafc6c000ceb884804f4cb2150825835e4c3eb))
* **cockpit:** commentator stream-link submission with director approval ([#202](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/202)) ([c429bfe](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/c429bfeda9285b64801e81f94fb5f923cfeb23de)), closes [#193](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/193)
* **cockpit:** Discord note (no [@here](https://github.com/here)) when a stream link is approved ([#205](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/205)) ([c9cf02d](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/c9cf02db92f410416a7476680549236103fa4ef9))
* **cockpit:** zero-config — remove the enable flag, auto-provision the secret ([#215](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/215)) ([07db52b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/07db52b89121308078f2e7f21623fc153120e9e5))
* **e2e:** drive the harness against the frozen binary (binary-only bug guard) ([#212](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/212)) ([f9da5f5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/f9da5f5b098db99bdab918007a56eea73d0b2842))
* **e2e:** e2e/regression harness — drive relay + cockpit + Control Center headlessly ([#208](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/208)) ([007fa33](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/007fa332ab6147d045b57790db3dc72a718b7667))
* free-text event title across Director Panel, Cockpit & Discord ([#209](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/209)) ([c97b63c](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/c97b63c29c07d13e35c7129ec1ac615661b491ca)), closes [#207](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/207)
* **logs:** timestamps, daily rotation + 7-day cleanup, archive browsing, OBS/Companion/Tailscale sources, and an aggregated live view ([#217](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/217)) ([3b4626e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/3b4626e1f3f66da06911413f54895e1894b6ddb0))
* **ui:** "Copy internal link" option in the Control Center Cockpit view ([#213](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/213)) ([106bed1](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/106bed131f66b98683d481cb507da2d0c029692b))
* **ui:** editable event title on the Control Center Home view ([#207](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/207)) ([#210](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/210)) ([da02a74](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/da02a7490bff2ab226df4a2e1722deb4b7e8711b))


### Bug Fixes

* **binary:** bundle src/cockpit/ so /cockpit loads in frozen builds ([#211](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/211)) ([035cb26](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/035cb268f94c233229b85a5f0c9e2127302204ad))
* **cockpit:** tear down the funnel with `funnel reset` ([#201](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/201)) ([7c2806a](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7c2806abbd49ee364b8e21b8ca6e6a127fe816e9)), closes [#200](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/200)
* **logs:** close tail_merged handles via `with open()` (CodeQL py/file-not-closed) ([#220](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/220)) ([8337557](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/8337557c04775d9f921e2e8c226fe135fca897f3))
* **logs:** resolve CodeQL alerts from [#217](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/217)'s tail_merged + close the gate gap ([#219](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/219)) ([c45abf7](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/c45abf7c65f284347b4f7bc72aae30fcfffabd7d))
* **panel:** clear only the URL in the schedule editor, keeping streamer + stint ([#203](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/203)) ([ec6fe42](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ec6fe4298f89552a583a35775a9b1bb5dbbeb493))
* **security:** resolve open code-scanning alerts + add procedure-return lint guard ([#204](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/204)) ([1945134](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1945134e4f8523237f738262498cc7b9916017ce))

## [0.7.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.6.0...v0.7.0) (2026-06-16)


### Features

* **event:** one-command producer takeover ([#189](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/189)) ([594f5cb](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/594f5cb4c38a0e723493cd17f759e1ee52a49ef1))
* **event:** pre-flight gate before event start bring-up ([#185](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/185)) ([32e8431](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/32e8431fcd4c88e1f0047ef1b4cb2395e6bda68d))
* **panel:** add a "D" favicon to the director panel ([#194](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/194)) ([8527f2e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/8527f2e311dcaf549bd520c5ee3e185a3ab663fd))
* **panel:** live preview multiview in the director panel ([#190](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/190)) ([0e3bed4](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/0e3bed42a6e9323f9b7644ec77862589ce4e069d))
* **relay:** [@here-ping](https://github.com/here-ping) the crew on every Discord health change ([#196](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/196)) ([af37e2b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/af37e2bb321ed4dbf9668b318bd68112baedddc0))
* **relay:** feed-down alert when a live feed drops unexpectedly ([#186](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/186)) ([ab05810](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ab058108fce2c207668dac1ee46373b4bb6a148b))
* **relay:** live health heartbeat with Discord alerts ([#188](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/188)) ([0011833](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/0011833362074eb9645aa9502922e360cafe44f9))


### Bug Fixes

* **relay:** send a User-Agent so Discord health alerts are not 403'd ([#195](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/195)) ([e3fbed5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e3fbed579bee44fc40711c2a66e3521bd5dd4865))

## [0.6.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.5.0...v0.6.0) (2026-06-16)


### Features

* **profile:** open the league Google Sheet from CLI + Control Center ([#183](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/183)) ([8153469](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/8153469df21046b363037d609faa4029c9636f62))


### Bug Fixes

* **companion:** scrub _MEIPASS off LD_LIBRARY_PATH for bare systemctl in frozen binary ([#180](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/180)) ([9b274cc](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/9b274ccf9fb5a17239c944658eeff7831e01e7b5))

## [0.5.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.4.0...v0.5.0) (2026-06-16)


### Features

* bandwidth speed test option (CLI + Control Center) — closes [#131](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/131) ([#160](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/160)) ([1290787](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1290787a0feeb881dab1d91f2b3d9367de6420d6))
* **companion:** control the companion-pi systemd service on native Linux ([#174](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/174)) ([bd3a843](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/bd3a8430ba79e654141d28f1e9d64ae01726a4a5))
* **install-tools:** sudo apt + auto-install deno on Linux ([#163](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/163)) ([4916402](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/491640224bc306cd82a024a804d1c8a09fae1af1))
* **obs-browser:** build & install the Browser Source plugin from source on Linux ([#177](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/177)) ([6d40604](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/6d40604114901e72ae5cce96b25cbab41849ed82))
* **obs:** Discord-web browser audio fallback for Linux without native Discord ([#179](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/179)) ([3837f1d](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/3837f1d339c85208c3ac0a4b9eb03dc8bcf93c88))
* **overlay:** label splitscreen feeds CURRENT/NEXT ([#129](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/129)) ([#156](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/156)) ([615b9b5](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/615b9b51935c84d2cf049e9a1696edde91225b9c))
* **overlay:** POV box name + relay-driven PiP toggle ([#158](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/158)) ([a2e46ab](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/a2e46ab4fd3d4af84e00a5a5aa17dce88b270880))
* **overlay:** standard properties for all builder slots ([#176](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/176)) ([1def62b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1def62b486e7ed9c4d2617517e0361f7af743558))
* **release:** build ARM64 Linux binaries ([#161](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/161)) ([fe2b828](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/fe2b828c081ef7dabf5ccef59f3ffc082f12ff77))


### Bug Fixes

* **frozen:** sanitize subprocess env for external tools (LD_LIBRARY_PATH leak) ([#165](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/165)) ([497c3a2](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/497c3a2431d0ba746807b228f11f7b3af8246fa2))
* **frozen:** strip all _MEIPASS dirs from the external-tool spawn path ([#166](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/166)) ([1252e78](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1252e78b19e4dcbe49944246e422bd804cc77673))
* **install-apps:** clean env for vendor scripts + skip Discord on ARM64 Linux ([#168](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/168)) ([01d616e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/01d616e569d2c58b919218a78809f2206aee5f86))
* **install-apps:** send a real User-Agent for vendor downloads (Discord 403) ([#167](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/167)) ([8e7eaeb](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/8e7eaebfa91dfd96294fe06a411cd62772974df0))
* **panel:** style schedule + qualifying streamer dropdowns like the HUD section ([#154](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/154)) ([444d235](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/444d2356bd6c149adaf46b698d841e2bc8875954)), closes [#152](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/152)
* **preflight:** don't blame Sheet sharing for a network timeout ([#169](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/169)) ([0f88f2f](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/0f88f2ff83d42bf2f240a16e5203ad1d06d044d8))
* **racecast:** consistent returns in companion_start/stop (py/mixed-returns) ([#178](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/178)) ([f36ca2e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/f36ca2e1c1a00f23adc111851456d2ed2ccf5ef7))
* **tailscale:** correct Linux UX — no GUI app, first login is `sudo tailscale up` ([#170](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/170)) ([e1c66f1](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e1c66f1bf2eefd7b5fa38f15591214385a8ce066))
* **tailscale:** Linux operator hint + document the Linux first-login ([#171](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/171)) ([d3cdb06](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/d3cdb06e7af8007734a2891f3d3c5a4a592e2b36))
* **ui:** refresh asset gallery on profile switch/import ([#164](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/164)) ([6c23129](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/6c2312945aec75f238efd328c8b3819208d09b39)), closes [#162](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/162)

## [0.4.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.3.0...v0.4.0) (2026-06-14)


### Features

* **fonts:** bundle curated overlay fonts into builds, auto-seed on start ([#132](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/132)) ([bc2a916](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/bc2a91655364e7f5b29bfd4bed6876c140868f51))
* **overlay:** editable timer position, split team slots, slot picker, POV box ([#146](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/146)) ([dbeef73](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/dbeef7368f4e5181cf40cc2fb34d8b63a9be6e5d))
* **overlay:** merge race timer into HUD, POV frame, property prefill ([#153](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/153)) ([ed27bbf](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ed27bbfa360926d783b580873e3d81e94f65a160))
* **relay:** qualifying mode — separate tab served on Feed A ([#127](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/127)) ([02263ee](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/02263ee46448abf2942217b49edb87f4d91cf388)), closes [#124](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/124)
* **relay:** schedule-driven HUD stint & streamer on handover ([#125](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/125)) ([cc4695b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/cc4695b370bafbab9cbc83d0ba1f941db20867b3)), closes [#112](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/112)
* **relay:** show pre-planned stints (blank URL) in the Director Panel ([#148](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/148)) ([e7da64d](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e7da64df86f4e011e687812b98655ffd07efbfe4)), closes [#137](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/137)
* **streams:** add a freeport recovery action for the feed ports ([#142](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/142)) ([9c9a038](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/9c9a0384b00bfdc6d88c8c8c87c5d97dcbd3d860))
* **ui:** visual overlay builder for league overlays ([#114](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/114)) ([#128](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/128)) ([cf05ebf](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/cf05ebf164aa11ffddc034f9f9d19476b44c85b1))


### Bug Fixes

* **lint:** enforce CodeQL py/empty-except locally; comment 5 silent swallows ([#150](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/150)) ([2f97cea](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/2f97cea1062c09f4e3b8185288cafa9d50ba18bd))
* **panel:** style the Qualifying section like the Schedule section ([#144](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/144)) ([4475729](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/4475729e574e465a21de8072fe035547b3461436)), closes [#134](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/134)
* **relay:** surface an immediate feed bind failure into /status last_error ([#147](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/147)) ([1f106de](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/1f106de9fc2dabeab6fc478e371a46d9d98c0b85)), closes [#143](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/143)
* **ui:** font library rows show one self-rendered preview, no overlap ([#149](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/149)) ([e84a3ed](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e84a3ed19e123f7d3d2c2da34073d5fd0f2cb0fc)), closes [#145](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/145)

## [0.3.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.2.0...v0.3.0) (2026-06-13)


### Features

* Twitch parity across relay and static mode ([#105](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/105)) ([13c4c0e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/13c4c0e276dda31242458f7d71971b4be9f32c5e))


### Bug Fixes

* **services:** verify process identity before kill ([#118](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/118)) ([a0e360e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/a0e360e2d696a64792d8e56561d7812a8dfa30c4))
* **ui:** render release notes as plaintext + add CSP ([#117](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/117)) ([85b498d](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/85b498d63cfe9afe8c48324dadfa7f86ecd0e35b))
* **ui:** restrict machine .env editor to RACECAST_ keys ([#120](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/120)) ([7ccef1f](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7ccef1f748ece8c5b6c2c86826d8558a91995ba5))
* **update:** filter tar symlinks + cap decompression ([#116](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/116)) ([b6ac332](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/b6ac33221b6864b1b2817ceeebecb9aeea5f266a))

## [0.2.0](https://github.com/jegr78/gt-endurance-racing-broadcast/compare/v0.1.0...v0.2.0) (2026-06-13)


### Features

* **chat:** crew chat in the director panel ([#72](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/72)) ([8806c44](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/8806c44d4d01eed602adda0c6558decc63b97b8e))
* **hud:** HUD design preview — overlay over a GT backdrop ([#85](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/85)) ([#90](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/90)) ([8253989](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/82539894e8ad73d182359dd7ae2ca9a2326c7b5c))
* **install-apps:** show installed app versions (CLI + Control Center) ([#97](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/97)) ([2c8c189](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/2c8c189a61ea8423c38f6668c9d58f88293f0acb))
* **panel:** persistent right-column chat on desktop + styled Send ([#82](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/82)) ([#89](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/89)) ([c79c471](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/c79c471df23c25a3d1da38e44df8f8715c608c00))
* per-league overlay identity — team name/number split + panel Top-3 ([#80](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/80)) and look backup/restore ([#81](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/81)) ([#86](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/86)) ([61b2529](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/61b25298c2f56e9c0c50c03339898e711da62e46))
* **profile:** export/import a whole league profile (producer onboarding) ([#93](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/93)) ([800903c](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/800903c537d2ad8c1b80b4a7e68d2220e600126c))


### Bug Fixes

* **install-apps:** don't fail --update on apps installed outside Homebrew ([#96](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/96)) ([e6d0174](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e6d0174243f8f97d328aa4d56c04e5ea3988c9e0)), closes [#92](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/92)
* **panel:** write Top-3 teams to the Setup tab, not the Overlay tab ([#95](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/95)) ([7c749ae](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/7c749aeaff290c57a0fc5e4a3d0db0422bfe4922))
* **relay:** clear Race Control on the /next handover cut ([#107](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/107)) ([89ebb35](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/89ebb35a48f50f8ecd61f9bbe1d23aeb3a3e3cbc))
* **relay:** live OBS-reachability probe in /status (no stale 'OBS NOT REACHABLE' banner) ([#94](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/94)) ([ec7031e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ec7031ed08da98670e1a6c6eba7e1ca79f80d24b))
* **relay:** make the loopback bind mandatory — no silent split-brain ([#84](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/84)) ([#87](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/87)) ([d8fe085](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/d8fe08523e72d335a29e86e4e41cdb5b6b964c35))
* **relay:** no visible console window when starting the daemon on Windows ([#110](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/110)) ([e77442f](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/e77442f27e3436d64f99695002137d27c614532a))
* **security:** close CSRF→RCE, update integrity, SSRF + arg-injection (review [#1](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/1)–[#4](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/4)) ([#106](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/106)) ([befefbd](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/befefbd6d8c8cde564e4a8aaeabfb326652d0556))
* **security:** document the two best-effort empty-except blocks (CodeQL) ([#79](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/79)) ([a58cc13](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/a58cc137290dafe6d982d17cdcad6cf1fc2757cb))
* **ui:** offer updates on frozen preview/dev builds in the Control Center ([#75](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/75)) ([69a5f6f](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/69a5f6f583aa7bd68aa53f7f82779d99985f4a07))
* **ui:** open the Director panel on the Tailscale host when available ([#83](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/83)) ([#88](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/88)) ([db0418e](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/db0418ed9276f71317800733f721595042416583))
* **ui:** refresh active-profile env in Control Center preflight/asset checks ([#108](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/108)) ([b47ce33](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/b47ce33e7cf6b461337c1af75bb07cdf958436f9))
* **ui:** suppress Windows console flash from in-process probes ([#109](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/109)) ([95e5329](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/95e5329cb41ce4fa7d4228d1a3b7eb1adbb4558c))
* **update:** self-update can replace the running Control Center on Windows ([#111](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/111)) ([32e001a](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/32e001a7b708d5ccec41cae8779dd65addafb7aa))

## 0.1.0 (2026-06-11)


### Features

* **build:** embed the racecast app icon in the binaries ([#58](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/58)) ([#67](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/67)) ([4c25fc8](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/4c25fc85bc84bbc8e099ee3e45ea033e456e1636))
* **ui:** add a racecast favicon for the Control Center ([#57](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/57)) ([#66](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/66)) ([ebbd931](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ebbd931df45989036dae66dd14f54257cd9ba6a5))
* **ui:** remove the monogram badge from the Control Center header ([#69](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/69)) ([f2cd3e1](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/f2cd3e179c3df978bf44e4e96b4902437d3b0aca))
* **ui:** show the active league logo in the Control Center header ([#60](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/60)) ([bfc09b7](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/bfc09b723f71ef07297a6728e085ba1cacc2cc62))


### Bug Fixes

* **docs:** drop the stale "v4 setup" version from the cheat sheet ([#56](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/56)) ([#65](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/65)) ([ad75a99](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ad75a99ed6ec0c72ec01df6c6009cab1669d260c))
* **ui:** inject active-profile env in the windowed launcher ([#54](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/54)) ([#63](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/63)) ([ee8c45a](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ee8c45ac2fe9da958981a57e28993ba91e1340ae))
* **ui:** resolve asset-serving root live per request, not at startup ([#55](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/55)) ([#64](https://github.com/jegr78/gt-endurance-racing-broadcast/issues/64)) ([ff3413b](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/ff3413bf35335648b556727502995af3ff2dac86))


### Miscellaneous Chores

* pin the next release to 0.1.0 ([94a4148](https://github.com/jegr78/gt-endurance-racing-broadcast/commit/94a414871a3c73356f1e9a3131595520f6c5aa42))

## Changelog

<!-- Maintained by release-please. The first 0.1.0 entry is written by the bot
     on the first release after the version baseline reset. Earlier history
     (the IRO line and 1.x/2.0.0) lives in docs/CHANGELOG-archive.md. -->
