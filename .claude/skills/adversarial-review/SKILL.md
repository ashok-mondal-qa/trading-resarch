---
name: adversarial-review
description: Independently try to break a strategy or candidate - reproduce results, hunt for look-ahead, survivorship, overfitting and unrealistic fills - and recommend rejection when evidence is weak. Use before accepting any experiment result and at gate 8.
---

# Adversarial strategy review

## Stance
Assume the result is wrong until it survives the checks below. Agreement from other agents is not
evidence; only reproduced numbers and passed tests are.

## Checklist for a strategy result
1. Re-run from the registry row. Do the numbers match exactly?
2. Look-ahead: inspect every input's timestamp; run the perturb-the-future test.
3. Survivorship: universe point-in-time? If not, how big could the bias be?
4. Overfitting: how many variants were tried (registry count)? Is the result an isolated peak in the
   parameter grid, or a plateau? Does it hold in each sub-period?
5. Costs and fills: does it survive 2x costs? Are fills at prices that were actually tradable
   (circuit-locked days, illiquid opens)?
6. Sample size: trades per split; bootstrap CI on expectancy includes zero? -> inconclusive.
7. Baseline: does it beat the simple baseline after costs, out of sample?
8. Holdout hygiene: was the holdout used more than once?

## Checklist for a single candidate (gate 8)
- Is the stop at a level the spec defines, or chosen to fit the size?
- Any event in the holding window the event check could have missed?
- Is the data fresh and consistent across sources?

## Output
A written verdict in `docs/validation/<experiment-id>-audit.md`: ACCEPT, REJECT or INCONCLUSIVE,
with each objection and the evidence. REJECT is a veto.
