# In-App DEB Library

DebToIPA's library is a generated snapshot of public iOS APT repositories. It is designed to make thousands of package records searchable inside the app without turning the production deployment into a multi-gigabyte binary dump.

## Included source classes

- Public/open repositories such as Sileo, palera1n, Procursus, ElleKit, Zebra, opa334, PoomSmart, and developer repos.
- Mixed repositories and marketplaces such as CyPwn, BigBoss, Chariz, Havoc, Twickd, Packix, and Dynastic as catalog-only sources.
- Archived sources are retained when their package indexes are still reachable.

The source registry lives in `library/sources.json`. The scheduled workflow runs `scripts/sync_deb_library.py`, parses Debian control indexes, deduplicates package versions, calculates a metadata-only conversion preflight score, and writes `public/library/index.json`.

## User flow

1. Search or filter the library.
2. Select a package and inspect its architecture, source, dependencies, and preflight score.
3. For a directly loadable package, DebToIPA fetches the DEB from its original repository through `/api/library/package`.
4. The library creates a browser `File`, injects it into the existing converter's real file input, and switches to the Builder tab.
5. The user selects the desired direct, shim, source, extension, background, or companion conversion profile.

No informational compatibility-host app is substituted for a failed conversion.

## Access and redistribution rules

`direct` means the original repository exposes a free unauthenticated package URL and the package metadata does not indicate a crack, purchase bypass, or commercial authentication requirement. It does not mean DebToIPA owns the package.

`catalog-only` means metadata is shown, but DebToIPA does not proxy or mirror package bytes. CyPwn is intentionally catalog-only because the source advertises cracks and modded packages alongside legitimate free packages.

`purchase-required` packages must be obtained legitimately from their marketplace. DebToIPA does not bypass payments, tokens, or repository authentication.

`blocked` packages are not loaded when metadata indicates piracy, DRM bypassing, or similar distribution concerns.

`bundleEligible` is only set when a direct source and the package metadata both provide an identifiable open license. That field can later drive release-pack generation without treating “free download” as permission to redistribute.

## Security boundaries

- Package IDs must exist in the generated snapshot; the proxy does not accept arbitrary URLs.
- Only HTTPS package URLs are accepted.
- Local, loopback, link-local, and private literal hosts are rejected after redirects.
- Downloads are streamed through a 250 MB limiter.
- Mixed or commercial sources do not expose download URLs in the public snapshot.
- The full converter still performs DEB extraction, Mach-O, entitlement, hook, path, and capability validation.
