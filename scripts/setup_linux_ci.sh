#!/usr/bin/env bash
# Prepare only a disposable GitHub-hosted Ubuntu runner; never alter a local host.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted ]]; then
  echo 'This setup script is only for disposable GitHub-hosted runners.' >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y bubblewrap apparmor python3.12-venv
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /usr/local/share/mori27-venv

if ! /usr/bin/bwrap --unshare-all --ro-bind / / -- /bin/true; then
  # Grant userns only to this root-owned CI copy. Keep global AppArmor settings.
  sudo install -D -m 0755 /usr/bin/bwrap /usr/local/libexec/mori27-ci/bwrap
  cat > "${RUNNER_TEMP}/mori27-ci-bwrap.apparmor" <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>
profile mori27-ci-bwrap /usr/local/libexec/mori27-ci/bwrap flags=(unconfined) {
  userns,
}
PROFILE
  sudo apparmor_parser -r "${RUNNER_TEMP}/mori27-ci-bwrap.apparmor"
  /usr/local/libexec/mori27-ci/bwrap --unshare-all --ro-bind / / -- /bin/true
  echo /usr/local/libexec/mori27-ci >> "$GITHUB_PATH"
fi
