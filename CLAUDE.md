# Montana-Dakota Utilities: notes for Claude and other coding agents

Montana-Dakota Utilities (`custom_components/mdu`, domain `mdu`) is a HACS
custom integration that signs in to the Montana-Dakota Utilities customer
portal and adds the account's balance, bills and natural gas usage to Home
Assistant, including external statistics for the Energy dashboard.

Oldest supported Home Assistant: `hacs.json` → `homeassistant` (2026.8.0).

## Layout

| Path | What it is |
| --- | --- |
| `api.py` | The portal client. MDU has no public API; the module docstring documents the sign-in (CSRF, form login, MFA by email or text) and every endpoint, read from the portal's public JavaScript bundles. |
| `config_flow.py` | Sign in, MFA contact and code, account choice; reauth. |
| `coordinator.py` | Signs in, reads the account and its usage, and records external statistics (`async_add_external_statistics`) for usage and cost. |
| `sensor.py`, `binary_sensor.py`, `entity.py` | Entities. Unique IDs start with the account ID. |
| `exceptions.py` | Errors the client raises (auth, MFA, connection). |
| `diagnostics.py` | Config entry diagnostics with personal data removed. |
| `strings.json` + `translations/en.json` | Must stay identical. `icons.json` holds entity icons. |
| `brand/`, `assets/` | Icons for HACS and Home Assistant; `assets/` holds the README logo sources. |

## Conventions

- **No personal details in the repo**: no account, premise or service
  agreement numbers, names, addresses, emails or phone numbers in code,
  tests, fixtures, README or CHANGELOG. Use obviously fake values.
- The portal can change without notice. Parse responses leniently, as the
  existing helpers do, and update the `api.py` docstring when an endpoint or
  payload changes.
- Statistic IDs (`statistic_id`, `cost_statistic_id`) and entity unique IDs
  must not change: the Energy dashboard and long-term history depend on them.
- The integration depends on `recorder`; tests that touch statistics use the
  recorder fixtures.

## Checks

Run the shared checks at the end of this file, on the newest Home Assistant
(`requirements_test.txt`, Python 3.14) and the oldest supported one
(`requirements_test_min.txt`, Python 3.14, Home Assistant 2026.8). CI runs both.

`tests/portal.py` is a fake portal on a local aiohttp test server, so the
client runs over real HTTP (cookies, redirects, headers) without mocking.
Extend it rather than mocking the client. Add a test for every behavior
change.

## Docs

- Update `README.md` when sensors, statistics or setup change.

<!-- BEGIN bisman-automations shared rules -->
<!-- This block is the same in every bisman-automations repo. Edit it in
     bisman-automations/.github (templates/CLAUDE.shared.md) and copy it to
     every repo; the Validate workflow's "standards" job checks it matches. -->

## Shared rules (every bisman-automations repo)

### Releases

- The version lives in `custom_components/<domain>/manifest.json`. Anything
  else that repeats it is called out in the repo-specific notes below and is
  bumped in the same commit.
- Versions follow [Semantic Versioning](https://semver.org): patch for fixes,
  translations, docs and CI; minor for new features, options or entities;
  major when something users rely on is removed or renamed (entities,
  services, events, options) or setup has to be redone.
- Check what is released before choosing a version:
  `git ls-remote --tags origin | awk -F/ '{print $3}' | sort -V | tail -1`
  (`sort -V`: plain sorting puts `v1.10.0` before `v1.9.0`). Never add
  changes to a released version. If the manifest version has no tag yet,
  add to its CHANGELOG section instead of bumping again.
- Every push to `main` ships as a release. In that same commit, named
  `Release X.Y.Z`, bump the manifest version and write the notes directly
  under a new `## [X.Y.Z] - YYYY-MM-DD` heading in `CHANGELOG.md` (Keep a
  Changelog: Added, Changed, Deprecated, Removed, Fixed, Security), with
  that version's compare link at the bottom. There is no `## [Unreleased]`
  section and no `[Unreleased]:` compare link. New work is not collected
  under a holding heading and moved later; the release commit is where the
  heading and the entries are written. The standards check fails if a
  `## [Unreleased]` heading is present.
- Ask Donavan before every push. Push fast-forward only: never force-push,
  rebase or amend anything already pushed, or rewrite history in any other
  way. Rewriting history orphans the release tags (it broke drafting in
  ha-button-actions).
- Pushing to `main` runs **Draft release**, which creates or refreshes a
  draft `vX.Y.Z` with that version's CHANGELOG section as the notes, the
  commits since the last release and `<domain>.zip`. **Donavan publishes
  the draft himself**, and publishing creates the tag. Never create or push
  tags, publish releases, or edit published releases.
- Publishing runs **Release check**: the tag must match the manifest version
  and the CHANGELOG, and be on `main`. If it fails, fix it with a new patch
  release, not by moving the tag.

### Commits

- Author commits as `Donavan Becker <donavan.becker@icloud.com>` (set
  `git config user.name` / `user.email` in the clone). HACS's
  default-repository check needs the submitter to have a fair share of the
  commits. Credit an AI assistant with a `Co-Authored-By:` trailer if you
  like, never as the author.
- Subject lines are plain, imperative and say what changed for the user
  ("Show Pico remotes as unavailable when Lutron isn't running"). No
  `fix:`/`feat:` prefixes. Release commits are "Release X.Y.Z".
- Commit and push only when asked.

### CI (shared workflows)

- `.github/workflows/` holds four thin callers of the reusable workflows in
  [bisman-automations/.github](https://github.com/bisman-automations/.github):
  `test.yml` (lint, frontend, pytest on the oldest supported and the newest
  Home Assistant, plus the upcoming one as information only), `validate.yml`
  (hassfest, HACS, standards), `draft-release.yml` and `release-check.yml`.
  Don't add jobs to the callers. Use the shared workflow's inputs, or change
  the shared workflow so every repo gets the improvement.
- `requirements_test.txt` leaves `pytest-homeassistant-custom-component`
  unpinned (newest Home Assistant) and pins ruff (and mypy where used).
  `requirements_test_min.txt` pins the harness release for the minimum in
  `hacs.json`: the newest harness release of that month. CI fails if they
  drift apart.
- Raising the minimum Home Assistant means changing, together: `hacs.json`,
  `requirements_test_min.txt`, `python-min` in `test.yml` (3.13 up to
  2026.2, 3.14 from 2026.3), the README's Home Assistant badge, and a
  CHANGELOG entry.
- Home Assistant 2026.3 and newer need Python 3.14 (3.14.2+).
- The published hassfest rejects `categories` in `manifest.json` and Pillow
  in `requirements`. Leave both out.
- Dependabot (`.github/dependabot.yml`) proposes action and pinned-tool
  updates weekly. It ignores the test harness on purpose.
- Test and Validate also run every Thursday, the day after Home Assistant's
  betas come out. The **next** test job (newest pre-release harness) is
  information only: when it fails, fix the cause before that release ships.

### Before saying work is done

Run from the repo root, in a Python 3.14 venv with `requirements_test.txt`
installed:

```
ruff check .
ruff format --check .
pytest
```

Also run `node --test tests/*.mjs` when the repo has Node tests, mypy when
the repo-specific notes list it, and the tests in a second venv with
`requirements_test_min.txt` when a change could behave differently on the
oldest supported Home Assistant. The standards check (also in CI) is
`python <path to bisman-automations/.github>/scripts/check_repo.py .`.

### Code and docs

- Support every Home Assistant from the `hacs.json` minimum to the newest
  release. Check for deprecations in the newest release and the beta.
- Keep entity IDs, unique IDs, service names and event names stable. When
  one has to change, migrate it and say so under Changed in the CHANGELOG.
- `strings.json` and `translations/en.json` hold the same keys. Home
  Assistant reads only `translations/`, so change both in the same commit.
- Never put personal details in the repo (README, CHANGELOG, code, tests,
  screenshots): no names, addresses, account or device identifiers, or real
  entity IDs. Use placeholders such as `light.living_room`.
- `README.md` is user documentation with the standard header (badges, HACS
  and "add integration" My buttons) and sections Installation, Setup, ...,
  Troubleshooting, Development, License. Use plain language and show names,
  not entity IDs, wherever the UI does.
<!-- END bisman-automations shared rules -->
