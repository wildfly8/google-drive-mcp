# Error taxonomy

Canonical envelope and category enum:

[`specs/001-access-control/contracts/error-taxonomy.md`](../../001-access-control/contracts/error-taxonomy.md)

This feature MUST NOT define a second enum. Tool contracts only add mapping rows. Completeness (`PARTIAL` / `EMPTY` / `COMPLETE`) is [result-status.md](./result-status.md), not an error category.
