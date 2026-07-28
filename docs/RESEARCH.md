# Phase 0 research record

Research date: 2026-07-21. Each commit below was inspected in a local clone. The
rating is an engineering selection for this product, not a general judgment of
the project.

| Project | Revision | License | Evidence / condition | Decision |
|---|---:|---|---|---|
| Remnawave backend | `ba5186814936` (v2.8.1) | AGPL-3.0 | Mature panel/API, active development, users, squads, nodes, HWID and subscriptions | Primary control plane, separately deployed; consume API |
| Remnawave node | `596f015a5c8f` (v2.8.0) | AGPL-3.0 | Maintained node agent and Xray integration | Primary node agent |
| Bedolaga bot | `ec0a2cdddb08` (v3.65.1) | MIT | FastAPI/aiogram/PostgreSQL/Redis; broad billing/referral surface; 216 test files; tightly coupled to Remnawave | Donor/reference; selectively port tested patterns with attribution |
| RemnaShop | `06350c6cb3e1` (v0.8.2) | MIT | Clean provider/payment protocols and dependency injection; small test suite | Architectural reference, not production base |
| VortexUI | `eac637896245` (v1.4.0) | GPL-3.0 | Rich scope and many tests, but project history is very young and adoption is low | Qualification branch only; not default provider yet |
| ProxyCraft | `e30186b537df` (v1.0.0) | MIT | Useful landing/Mini App journey; few tests and direct 3X-UI/SQLite coupling | UX reference only; original frontend |
| rs8kvn_bot | `fdbf40d38370` (v2.3.6) | no license found at inspected HEAD | Subscription concepts and tests; payment path contains stubs | Concepts only; do not copy code without license grant |
| BotMirzaPanel | `92c0ed0676c1` | GPL-3.0 | Procedural PHP and panel coupling | UX comparison only |
| 3x-ui | v3.5.0 (research snapshot) | GPL-3.0 | Established Xray panel and ecosystem | Optional provider/lab fallback |
| mtg | v2.2.8 | MIT | Focused MTProto proxy implementation | Candidate for the later MTProxy phase |
| Xray-core | current research snapshot | MPL-2.0 | Required protocol runtime | Node runtime through the control plane |
| sing-box | current research snapshot | GPL-3.0 plus project naming policy | Hysteria2/alternative runtime where justified | Isolated node component; legal/name review before distribution |

## Selection

The platform uses its own business boundary because no reviewed project combines
the required accounting, payment controls, Telegram auth, provider independence
and test evidence at an acceptable risk level. This does not mean rebuilding the
VPN plane: Remnawave, its node agent and Xray remain externally maintained
components. The business code uses mature Python libraries and explicit ports for
VPN, payments, notifications and jobs.

VortexUI can replace Remnawave only after its migration, restart, usage-delta,
Redis/PostgreSQL failure and reconnect tests pass on our staging topology.

## License boundary

AGPL/GPL services remain separate processes reached over documented network APIs.
If those projects are modified and offered over a network, the corresponding
source and license obligations must be fulfilled. No source from unlicensed
`rs8kvn_bot` is copied. UI is original and does not reuse VPNUS assets.
