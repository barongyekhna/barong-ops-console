# K03 Runtime Boundary Rules (FINAL)

## 1. Allowed Root

/opt/barong-ops-console-worktrees/k-series-product-knowledge

## 2. Forbidden Roots

- /opt/barong-ops-console
- /opt/barong-ops-console-worktrees/barong-ops-console
- any non-k-series-product-knowledge workspace

## 3. Execution Isolation Rule

K-series operations MUST remain inside allowed root.

Cross-directory operations are strictly forbidden.

## 4. Dual Terminal Context Rule

If terminal prompt contains:
barong-ops-console#

THEN:
- Treat as C-series context
- DO NOT execute writes
- ONLY notify user

## 5. Git Isolation Rule

K-series repo operations MUST NOT affect C-series repositories.

## 6. Enforcement Rule

Any boundary violation = immediate STOP condition.
