# Open-source license policy

- MIT/Apache/BSD/MPL dependencies may be used subject to notice and source-file
  obligations.
- GPL/AGPL components are isolated services unless legal review approves another
  integration form. Modified AGPL network services require corresponding source
  availability.
- Dependencies without an explicit license are not copied, vendored or linked.
- CI will generate an SBOM and license report from pinned Python, Node, Go and
  container lockfiles. Unknown or denied licenses fail the release gate.
- Product branding, copy, illustrations and UI code are original. VPNUS assets are
  neither included nor treated as open source.

Full license texts for deployed external services must ship with the deployment
bundle. Package-level license texts are generated after dependency locking in
Phase 2.
