# LESR v1 Canonical example

This synthetic example uses the v1 Logical Object and immutable Revision
contracts. It is input material for a Canonical Git tree, not a legacy YAML
project and not an independently authoritative database.

```powershell
python scripts/verify_construction_schemas.py
```

Formal changes must be submitted as a Semantic Transaction, reviewed as an
immutable package, signed by a trusted human Ed25519 key and applied through the
canonical ref.
