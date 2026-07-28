# Alembic autogenerate output is a draft, not an authority

## Status
Accepted

## Context
Every migration in this project is generated with `alembic revision --autogenerate`.
Three separate times it produced output that was incomplete or broken:

1. **Sequences.** `claim_number_seq` was declared on the model but never appeared
   in the migration. Applying it would have succeeded, then failed at the first
   claim insert with "relation does not exist".
2. **HNSW indexes.** Vector indexes are not expressible in SQLAlchemy model
   metadata, so autogenerate cannot see them. Without them, similarity search
   silently falls back to a sequential scan.
3. **Missing imports.** The pgvector migration referenced
   `pgvector.sqlalchemy.vector.VECTOR` but autogenerate emitted no matching
   import, so the migration raised `NameError` on execution.

The pattern is consistent: autogenerate diffs *table structure* (tables, columns,
btree indexes, constraints) reliably, and is unreliable or silent about
everything else — sequences, index types, raw SQL, imports for third-party
column types.

## Decision
Every generated migration is read before it is applied. Anything autogenerate
cannot express — sequences, HNSW indexes, extensions — is written by hand in a
separate, clearly named migration.

## Consequences
- Slower: one review step per migration.
- Two migrations where one would do, when hand-written DDL is involved.
- In exchange: no migration reaches the database without a human having read the
  DDL it will execute.

## Alternatives considered
**Hand-write every migration.** Removes the failure mode entirely, but discards
autogenerate's genuine strength — it catches model/schema drift a human would
miss. Rejected: the review step keeps the benefit and removes the risk.

**Trust autogenerate and fix failures as they surface.** Two of the three
failures above (the sequence, the missing HNSW index) would not have failed at
migration time. They would have failed later, somewhere else, looking like a
different bug.

## Addendum: the destructive case

A fourth failure appeared when generating the assessments migration. Autogenerate
emitted `drop_index` for both HNSW indexes on the vector columns, and matching
`create_index` calls in `downgrade()`.

The mechanism: autogenerate diffs the live database against SQLAlchemy model
metadata. HNSW indexes exist in the database but cannot be expressed in model
metadata, so every future autogenerate run sees them as indexes that should not
exist and proposes dropping them.

This is worse than the earlier three failures in kind, not just degree. The
others produced errors or absent objects, which surface quickly. This one
silently removes a working index. Similarity search would still return results,
just via sequential scan, with no error raised anywhere.

**Standing rule:** every autogenerate run on this project is checked with
`grep -n "hnsw" <migration>` before applying. Expected result: no matches. Any
match is removed from both `upgrade()` and `downgrade()`.
