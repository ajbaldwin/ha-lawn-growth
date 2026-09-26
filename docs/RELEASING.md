# Releasing

This repository is distributed via a HACS **custom repository**, with
`hacs.json`'s `hide_default_branch: true`. That setting means HACS only ever
offers users **tagged releases** — never the tip of `main` — so a change
isn't available to installs until it's tagged and released. There is no
separate "publish to HACS store" step: publishing a GitHub release *is* the
publish step.

## Beta and stable

Releases go out on two channels, both as GitHub releases:

- **Beta — `X.Y.Z-beta.N`**, published as a GitHub *pre-release*. HACS offers
  it only to users who turned on this integration's **Pre-release** switch —
  since HACS 2.0 a per-repository switch entity, disabled by default (see the
  README's *Beta versions*). You run it on your own box first.
- **Stable — `X.Y.Z`**, the release every HACS user is offered.

**By default, merged changes ship as a beta.** Fixes found while a beta is out
go into the next beta (`-beta.2`, `-beta.3`, ...), not into a string of stable
patches. Promote to stable when you judge the beta ready. Nothing enforces the
wait, so the discipline is yours. A direct stable (no beta) is still allowed
for an urgent fix to a bug in the current stable.

Version numbers: betas carry the version the stable will get — the first beta
after 0.1.0 is `0.2.0-beta.1` (or `0.1.1-beta.1` for fixes only), and
promoting it is `0.2.0`. Never publish a beta of a version that is already
stable; it would sort below it (`tools/release.sh` refuses).

CHANGELOG sections:

- **Each beta** gets its own section, `## 0.2.0-beta.2 — Title`, covering what
  changed since the previous beta. Beta users read it as that release's notes.
- **The stable** gets `## 0.2.0 — Title` summarizing *everything* since the
  previous stable, written for users who skipped every beta. Don't just point
  at the beta sections. The beta sections stay in the file.

## Steps

1. **Open a release PR** (`release: vX.Y.Z`) with two changes:

   - **Bump the version** in `custom_components/lawn_growth/manifest.json`: the
     next beta (`0.2.0-beta.1`, ...) or the stable (`0.2.0`), no leading `v`.
     The tag will be `v` + this version.
   - **Write the release notes** as a new top section in `CHANGELOG.md`,
     headed `## X.Y.Z — Title`. `tools/release.sh` publishes that section
     verbatim as the GitHub release body, and HACS renders the body as the
     changelog shown to users before they update. Write a short,
     human-readable summary of what changed and why it matters to someone
     deciding whether to update — never a raw commit log.

2. **Merge it**, then publish from an up-to-date `main`:

   ```bash
   git checkout main && git pull
   bash tools/release.sh publish --dry-run
   bash tools/release.sh publish
   ```

   The script refuses unless you are on a clean `main` that matches
   `origin/main`, CI passed on that commit, the tag is new, and `CHANGELOG.md`
   has the version's section. It then tags `vX.Y.Z` and creates the GitHub
   release — a pre-release for `-beta.N`, the latest release for a stable —
   titled from the CHANGELOG heading. `--dry-run` runs every check and shows
   the notes without publishing.

   **Or publish from GitHub** (no local `gh` needed): Actions → **Publish
   release** → Run workflow on `main`. It runs the same `tools/release.sh`;
   `dry_run` is on by default, so run it once as a dry run, check the log, then
   run it again with `dry_run` off. A release created this way doesn't trigger
   the release guard below (GitHub doesn't start workflows from a workflow's
   own token), so the job runs `tools/check_release.sh` itself and fails if the
   release is inconsistent.

3. **Verify in HACS.** After the release publishes, HACS should offer the new
   version as an update (a beta only with the Pre-release switch on) within
   its normal refresh window.

**Release guard.** `.github/workflows/release-guard.yml` re-checks every
published or edited release — including ones made by hand in the GitHub UI —
with `tools/check_release.sh`: the tag must equal `v` + the manifest version at
that tag, and the pre-release flag must match the version. On a mismatch it
turns the release back into a draft (HACS stops offering it) and the run
fails. Fix the cause, then publish the draft again.

## Notes

- Version numbers are semver (`MAJOR.MINOR.PATCH`). Bump `PATCH` for
  fixes, `MINOR` for backwards-compatible features (e.g. a new sensor),
  `MAJOR` for anything that breaks existing config entries or entity IDs.
- The manifest `version` and the git tag must agree, or HACS will show a
  confusing version mismatch to users comparing the release notes to what
  they see installed. `tools/release.sh` and the release guard both enforce
  this.
