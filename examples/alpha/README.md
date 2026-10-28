# Frozen synthetic alpha corpus

These are complete, byte-preserved native search evidence bundles from the
owner-accepted S08-01 implementation. No success report was fabricated for this
corpus, and using the corpus does not run another research attempt.

Source: [Engineering 40662769753](https://github.com/Darrenus/tickwitness/actions/runs/40662769753),
[Ubuntu artifact 12804098468](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804098468).
Functional head: `1623aaccaa8f4e8f6432989e6a877e4b1790e4c8`.
Actual merge checkout: `42af1e23987835a9975cff1225175cbf3eec0bfb`.
The source artifact calls these cases `source-normal` and `all-true`.

| Directory | Bundle ID | Finding report ID |
| --- | --- | --- |
| `counterexample` | `2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369` | `398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb` |
| `clean-control` | `c5c3080fc6ab0ebd81b71373faee2f282e99feb95b904dd36bbc9631bd2b2c5e` | `8b902a687eeeb6897aa9237074b8a4fe7e5b336264a47bf52a9cc8427c20b3da` |

The counterexample uses the frozen `gt 0 USD` predicate; the clean control uses
`gt -3 USD`. Both cover their complete declared candidate plans. These are
different frozen questions, without a matched causal-pair claim, real-market
performance evidence, or global robustness guarantee. The kit assembler's
revision is recorded separately from the original corpus producer.

Re-audit the content using the current core installation. Native replay is not
reexecuted by the alpha scorecard. Keep these exact original bytes when adding a
new corpus version; a changed case needs a new identity and provenance record.
