#!/bin/sh
# Applies Atlas' authentik blueprints (stacks/authentik/blueprints) in order,
# checks the result, and restarts the server so its embedded outpost serves
# every forward-auth provider (README "Blueprints"). The authentik stack's
# post_deploy runs it from stacks/authentik. The blueprints are labelled
# blueprints.goauthentik.io/instantiate: "false", so the worker's task queue
# never applies them: with two worker threads, slow or concurrent applies there
# stalled the queue and left new blueprints unapplied.

set -eu

# Dependency order: groups first, then what binds to them; the outpost last,
# because it lists every forward-auth provider. The validator keeps this list
# equal to the blueprint files.
BLUEPRINTS="groups admins-mfa reputation grafana oidc-autobrr oidc-qui
forward-auth-adguard forward-auth-autobrr forward-auth-bazarr
forward-auth-houndarr forward-auth-lidarr forward-auth-prowlarr
forward-auth-qbittorrent forward-auth-qui forward-auth-radarr
forward-auth-rclone forward-auth-sabnzbd forward-auth-slskd
forward-auth-sonarr forward-auth-speedtest forward-auth-spottarr
forward-auth-ugos outpost"

ak_shell() {
  docker compose exec -T worker ak shell 2>/dev/null
}

wait_healthy() {
  service=$1
  attempts=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q "$service")")" = healthy ]; do
    attempts=$((attempts + 1))
    if [ "$attempts" -gt 120 ]; then
      echo "authentik-apply-blueprints: $service is not healthy after 10 minutes" >&2
      exit 1
    fi
    sleep 5
  done
}

wait_healthy worker

# Blueprint instances the worker created for these files before they were
# labelled: disabled, the worker skips any task it still has queued for them.
# This script keeps them, disabled, as its record of what it applied.
ak_shell <<'EOF' | grep '^DISABLED' || true
from authentik.blueprints.models import BlueprintInstance
print("DISABLED", BlueprintInstance.objects.filter(path__startswith="custom/", enabled=True).update(enabled=False))
EOF

# The worker applies authentik's own blueprints after it starts. Wait until
# that work is done, so the applies below do not contend for the same rows.
attempts=0
while :; do
  pending=$(ak_shell <<'EOF' | sed -n 's/^PENDING //p'
from authentik.tasks.models import Task
print("PENDING", Task.objects.filter(
    actor_name="authentik.blueprints.v1.tasks.apply_blueprint",
    state__in=["queued", "consumed", "running"],
).count())
EOF
)
  [ "$pending" = 0 ] && break
  attempts=$((attempts + 1))
  if [ "$attempts" -gt 60 ]; then
    echo "authentik-apply-blueprints: the worker still has $pending blueprint tasks after 10 minutes" >&2
    exit 1
  fi
  sleep 10
done

# Only blueprints whose content changed since this script last applied them:
# re-saving an unchanged provider still makes authentik rebuild the outpost's
# permissions, about 20 seconds each. The order stays that of BLUEPRINTS.
paths=$(ak_shell <<EOF | sed -n 's/^CHANGED //p'
from hashlib import sha512

from authentik.blueprints.models import BlueprintInstance

for name in """$BLUEPRINTS""".split():
    path = f"custom/{name}.yaml"
    content = BlueprintInstance(path=path).retrieve()
    instance = BlueprintInstance.objects.filter(path=path).first()
    if not instance or instance.last_applied_hash != sha512(content.encode()).hexdigest():
        print("CHANGED", path)
EOF
)

if [ -n "$paths" ]; then
  echo "authentik-apply-blueprints: applying" $paths
  # One command applies them in order and stops at the first invalid one. A
  # database deadlock with the worker is retried.
  log=$(mktemp)
  trap 'rm -f "$log"' EXIT
  attempt=1
  # shellcheck disable=SC2086 # $paths is a list of words.
  until docker compose exec -T worker ak apply_blueprint $paths >"$log" 2>&1; do
    grep -v -e '"level": "info"' -e '"level": "debug"' "$log" >&2 || true
    if [ "$attempt" -ge 3 ]; then
      echo "authentik-apply-blueprints: applying the blueprints failed three times" >&2
      exit 1
    fi
    attempt=$((attempt + 1))
    sleep 10
  done
else
  echo "authentik-apply-blueprints: every blueprint is applied already"
fi

# ak apply_blueprint does not fail when applying (rather than validating) goes
# wrong, so check the result: the outpost serves exactly the forward-auth
# providers, and each has an application.
result=$(ak_shell <<'EOF' | grep '^VERIFY'
import glob
import re

from authentik.outposts.models import Outpost

expected = set()
for path in glob.glob("/blueprints/custom/forward-auth-*.yaml"):
    match = re.search(r"proxyprovider\n    id: provider\n    identifiers:\n      name: (\S+)\n", open(path).read())
    expected.add(match.group(1) if match else path)
outpost = Outpost.objects.get(managed="goauthentik.io/outposts/embedded")
served = {provider.name for provider in outpost.providers.all()}
orphans = sorted(p.name for p in outpost.providers.all() if getattr(p, "application", None) is None)
if served == expected and not orphans:
    print("VERIFY ok", len(served), "forward-auth providers")
else:
    print("VERIFY failed: missing", sorted(expected - served), "unexpected", sorted(served - expected), "without application", orphans)
EOF
)
echo "authentik-apply-blueprints: $result"
case "$result" in
  "VERIFY ok"*) ;;
  *) exit 1 ;;
esac

# Record what is applied, so the next deploy applies only changes.
ak_shell <<EOF | grep '^RECORDED' || true
from hashlib import sha512

from django.utils.timezone import now

from authentik.blueprints.models import BlueprintInstance, BlueprintInstanceStatus

names = """$BLUEPRINTS""".split()
for name in names:
    path = f"custom/{name}.yaml"
    content = BlueprintInstance(path=path).retrieve()
    instance = BlueprintInstance.objects.filter(path=path).first() or BlueprintInstance(
        path=path, name=path, context={}, managed_models=[], metadata={}
    )
    instance.enabled = False
    instance.status = BlueprintInstanceStatus.SUCCESSFUL
    instance.last_applied_hash = sha512(content.encode()).hexdigest()
    instance.last_applied = now()
    instance.save()
print("RECORDED", len(names))
EOF

# The embedded outpost loads its providers when the server starts.
docker compose restart server
wait_healthy server
echo "authentik-apply-blueprints: server restarted with every forward-auth provider"
