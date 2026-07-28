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
