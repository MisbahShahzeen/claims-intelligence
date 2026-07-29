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
