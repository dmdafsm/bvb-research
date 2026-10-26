## Problem and result

Related task: Px.n / REPO. Describe the trigger, resulting behavior and acceptance criteria.

Architecture impact: existing pattern (owning module/table), or material change with a linked decision record.

## Validation

| Command or check | Actual result |
| --- | --- |
| `python3 scripts/verify.py` | Passed / failed / not run, with reason |
| Real-data check (collector run, reconciliation, spot check) | Result or not applicable, with reason |
| Dashboard browser check | Result or not applicable, with reason |

## Data and source impact

Affected sources, terms and request volume; schema changes (additive or rebuild procedure); provenance and point-in-time semantics. Use "not applicable" with a reason when appropriate.

## Review notes

Material tradeoffs, dependency changes, known limitations. Review status: self-review / independent review / not run, with scope.

- [ ] The diff is focused; docs and `uv.lock` match the implementation.
- [ ] Acceptance criteria have evidence; incomplete work is stated explicitly.
- [ ] No secrets, collected data or bulk source files; BVB data stays personal-use.
