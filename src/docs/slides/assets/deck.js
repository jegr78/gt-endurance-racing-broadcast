/* Shared Reveal init for every onboarding deck. UMD globals come from the
   vendored dist/plugin scripts each deck includes before this file. */
Reveal.initialize({
  width: 1280,
  height: 720,
  margin: 0.06,
  hash: true,
  slideNumber: 'c/t',
  controls: true,
  progress: true,
  transition: 'slide',
  backgroundTransition: 'none',
  plugins: [RevealMarkdown, RevealHighlight, RevealNotes],
});
