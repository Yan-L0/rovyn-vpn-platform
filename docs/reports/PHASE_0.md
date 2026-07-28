# Phase 0 report — Research

Date: 2026-07-21

## Completed

- Analysed the public VPNUS website, Telegram entry points, cabinet assets, Android
  package metadata and publicly visible operating model.
- Inspected local clones of VortexUI, ProxyCraft, rs8kvn_bot, BotMirzaPanel,
  Remnawave backend/node, Bedolaga and RemnaShop.
- Recorded exact inspected revisions, licenses, strengths and blocking risks in
  `docs/RESEARCH.md` and `THIRD_PARTY_NOTICES.md`.
- Selected Remnawave as the initial external VPN control plane. VortexUI remains a
  qualification candidate because its age/adoption and failure-mode evidence are
  not yet adequate for the default path.
- Selected an original React Mini App and a Python modular business platform; no
  VPNUS assets or unlicensed source were copied.

## Files changed

- `docs/RESEARCH.md`
- `docs/ARCHITECTURE.md`
- `docs/THREAT_MODEL.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `THIRD_PARTY_NOTICES.md`
- `OPEN_SOURCE_LICENSES.md`

## Verification

- Repository revisions were read directly from the inspected Git clones.
- Licenses were checked in the corresponding snapshots.
- Remnawave v2.8.1 route and DTO contracts were read before implementing the
  adapter.

## Problems found and decisions

- `rs8kvn_bot` has no license at the inspected HEAD and contains a stub payment
  path: no code is reused.
- ProxyCraft and BotMirzaPanel are too tightly coupled to their panel/storage
  choices: retained only as UX references.
- VortexUI is feature-rich but very young: it cannot become the primary provider
  until migration, usage accounting and dependency failure tests pass.
- Bedolaga offers broad functionality and a strong test inventory but is tightly
  coupled to Remnawave: use selective patterns, not a wholesale fork.

## Remaining risks

- GitHub activity/security state changes over time and must be rechecked before
  each dependency upgrade.
- AGPL/GPL deployment obligations need final legal review for the chosen hosting
  model and any future control-plane modifications.
- VPNUS behaviour is inferred from public surfaces; private operational details
  are neither available nor required for a functionally comparable product.

## Next phase

Finish Phase 1 architecture ADRs and freeze the explicit Alembic baseline, then
complete Phase 3 with a real PostgreSQL/Redis container smoke test.
