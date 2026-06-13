# Changelog

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
