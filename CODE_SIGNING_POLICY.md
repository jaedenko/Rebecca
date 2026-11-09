# Code signing policy

Rebecca's Windows installer and executable are built from this repository by the public GitHub Actions
workflow (`.github/workflows/build.yml`). Release builds are signed only when they come from that workflow.

- **Free code signing provided by [SignPath.io](https://signpath.io), certificate by the
  [SignPath Foundation](https://signpath.org).** (Applies once signing is enabled for this project.)

## Roles
- **Committer and reviewer:** project owner, [@jaedenko](https://github.com/jaedenko)
- **Approver:** project owner, [@jaedenko](https://github.com/jaedenko)

Only the approver can release a signed build. Contributions from others are reviewed before they are merged.

## Privacy
This program will not transfer any information to other networked systems unless specifically requested by
the user or the person installing or operating it. In Rebecca's case the only such request is the
"Check for updates" menu item, which asks GitHub for the newest release number. Camera video is processed
on the computer and is never saved or sent anywhere. See the Privacy section of the README.

## What is signed
`RebeccaSetup.exe` and `Rebecca.exe` (inside the portable zip). The macOS build is not signed with a
SignPath certificate.
