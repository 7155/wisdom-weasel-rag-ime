# Release Metadata

This directory contains public-safe source and distribution metadata:

- `feature-registry.json`: feature-level source/foreground status and
  acceptance commands;
- `product-status.json`: the latest declared verification scope and unresolved
  release gates;
- `release-manifest.example.json`: the required shape for a signed,
  notarized, hash-bound macOS distribution.

Two readiness decisions are intentionally separate:

```bash
# Is this source tree safe to make public?
python3 scripts/check_public_release.py --repository-only

# Is a distributable macOS package accepted, signed, notarized, stapled, and
# bound to exact corresponding source?
python3 scripts/check_public_release.py
```

The first command may pass while the second remains blocked. Do not change
`product-status.json` or manufacture a release manifest merely to make the
distribution audit green.
