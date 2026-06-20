# The Console launcher

`/console` is the **single personal link** every crew member opens. Instead of
separate URLs for each surface, one link adapts to the signed-in person's role and
shows only the cards they are allowed to use — nothing more.

![The /console launcher — role-adaptive cards: Commentator Cockpit, Director Panel, Web Buttons](images/console-landing.png)

## How it works

`racecast links` generates one signed `/console` link per person (union of the Crew tab
and the live schedule). The producer shares each link with the relevant person. Opening it
in any browser authenticates the person and renders their personalised landing page.

The same link works **over the tailnet** (e.g. a phone with the Tailscale app) **or over
the public Funnel** (`racecast funnel on` — no Tailscale account needed on the crew
member's side). See [Remote access & the Funnel boundary](Remote-access) for the full
security model.

## The cards

| Card | Path | Who sees it |
|---|---|---|
| **Commentator Cockpit** | `/console/cockpit` | any authenticated person |
| **Director Panel** | `/console/panel` | directors |
| **Web Buttons** | `/console/buttons` | directors (requires Companion ≥ v4.1.0) |

Each card leads to the same page as its tailnet equivalent — `/cockpit`, `/panel`, and
the Companion Web Buttons board at `:8000/tablet` respectively — but reached through
the role-gated `/console` mirror, with API calls transparently routed to the correct
endpoints.

A person can hold multiple roles (e.g. a commentator who is also a director); all
their cards appear on one landing page. Roles are resolved live from the Crew tab and
the active schedule on every request, so a role change takes effect immediately without
re-issuing the link.

## Further reading

- [League-Owner Setup](League-Owner-Setup) — how to configure Discord OAuth, register
  redirect URIs, and maintain the Crew tab so crew members can log in with Discord.
- [Remote access & the Funnel boundary](Remote-access) — security model, the Funnel
  mount, and how roles are authorised.
- [Commentator Cockpit](Commentator-Cockpit) — the talent-facing cockpit in detail.
- [Director guide](Director) — the full Director Panel reference.
- [Companion (button config)](Companion) — the Web Buttons board and how to configure
  Companion buttons.

---

> This page is generated from `src/docs/wiki/` in the
> [main repository](https://github.com/jegr78/gt-endurance-racing-broadcast) — don't edit it
> here by hand. See [Build & maintenance](Build-and-maintenance).
