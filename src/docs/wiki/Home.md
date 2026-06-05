# IRO Endurance Broadcast

This wiki is for everyone who runs the **IRO Endurance** sim-racing broadcast — whether
you set up the machine, run the show, or direct it remotely.

**In one picture:** each stint has a commentator streaming the race on their own YouTube
channel. One PC pulls those streams in, adds the on-screen graphics and the Discord
interview audio, and pushes a single, clean broadcast to the IRO YouTube channel. A
**Producer** runs that PC; a **Director** decides what viewers see — from a browser,
anywhere.

```mermaid
flowchart LR
  C1["Commentator 1"] --> PC
  C2["Commentator 2"] --> PC
  C3["... one per stint"] --> PC
  PC["Producer's PC<br/>mixes video, audio<br/>and the on-screen graphics"] --> YT["YouTube<br/>the IRO channel"]
  Prod(["Producer<br/>runs the PC"]) -.-> PC
  Dir(["Director<br/>remote, chooses what is shown"]) -.-> PC
```

- **Get the tool:** download the `iro` binary for your OS from the
  [latest release](https://github.com/jegr78/IRO_Broadcast_Setup/releases/latest)
  — then follow [Set up the broadcast PC](Set-up-the-broadcast-PC).

## Pick your path

- **Setting up a machine for the first time?** → [Set up the broadcast PC](Set-up-the-broadcast-PC)
- **Running a show today?** → [Run an event](Run-an-event)
- **You're the remote director?** → [Director guide](Director)
- **Not sure who does what?** → [Who does what](Who-does-what)
- **Something's broken?** → [If something goes wrong](If-something-goes-wrong)
- **Developer / want the technical detail?** → [Architecture](Architecture) and the
  **Technical reference** section in the sidebar.

---

> This wiki is generated from `src/docs/wiki/` in the
> [main repository](https://github.com/jegr78/IRO_Broadcast_Setup) — don't edit pages
> here by hand. See [Build & maintenance](Build-and-maintenance).
