# Historical benchmark material store

This directory is intentionally empty in the source distribution. V1.12 does
not fabricate or redistribute the 120 official historical materials. After
licence review, place each approved source at:

```text
sha256/{first-two-hex-digits}/{full-sha256}
```

Then import a manifest with `python -m app.manage benchmark ingest-manifest`.
The importer checks the six-domain `90 development + 30 blind` matrix,
publisher/license metadata, cutoff discipline, and every Blob SHA-256 before
the suite can become active. Full blind labels are encrypted outside the
repository and imported only as a sealed label pack.
