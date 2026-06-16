# Changelog

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
