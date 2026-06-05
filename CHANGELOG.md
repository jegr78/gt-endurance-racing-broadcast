# Changelog

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
