# The assessment caught inconsistent test data before we did

## Context
The first successful assessment returned `indeterminate` with risk 95 on what we
believed was a straightforward rear-end collision claim.

It was right and we were wrong. The claim record had `loss_type: theft`, because
the test claim was selected with `?limit=1` (newest first) and happened to be one
of the synthetic theft claims. We then attached a collision police report and a
collision repair estimate to it.

The model refused to issue a coverage verdict on a claim whose reported loss type
contradicted its supporting documents, and said so, citing the scope-of-cover and
police-report clauses.

## What this validates
- `indeterminate` earns its place as a verdict. A binary covered/not-covered
  enum would have forced a wrong answer on a genuinely ambiguous input.
- Reasoning over the amounts list beats label matching. The model flagged the
  claimed amount exceeding the documented repair total without being told which
  field to compare, which was the open problem left by Phase 6.
- The two-collection split works. The fraud precedent was cited for risk, the
  collision precedent for amounts. One combined collection could not make that
  distinction.

## Consequences
Seed data needs a consistent claim before the happy path can be demonstrated:
matching loss type, a reported date within the policy's 48-hour notification
window, and documents that corroborate the narrative.

Keeping the inconsistent claim is also worth doing. It is the only case in the
fixture set that exercises the `indeterminate` path.

## Second occurrence

The fix attempt introduced a different inconsistency. A new claim was created
with `loss_date: 2026-07-27` and a matching `loss_type: collision`, but reused
the existing fixture documents, which describe an incident on 14 May 2026.

The assessment returned `indeterminate` again, and explained why: the police
report contradicts the claim record's date of loss, and if the document's date is
correct then Section 3.7's 48-hour notification requirement was not met.

It did not merely detect a mismatched field. It identified which of the two
conflicting facts would change the outcome, and named the clause that makes it
matter.

## Standing note
Two fixture errors, both found by the model rather than by us. Any future seed
data must be internally consistent across the claim record and every attached
document: loss type, loss date, amounts, and parties.
