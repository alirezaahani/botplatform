#!/usr/bin/env bash
# Starts the stack, launches one headless/direct run per bot and checks how each run ends.
# Run from the project root: .github/scripts/smoke.sh   (needs Docker and a .env, like `compose up`)
#
# Pass criteria:
#   example   must end `success`.
#   arcaptcha runs against the live site, so `success`, `blocked` and `failed` are all accepted
#             (the outcome depends on ARCaptcha). `error` and `timeout` fail the check, and so does
#             a `success` or `blocked` run that has no challenge_id.
set -euo pipefail

cd "$(dirname "$0")/../.."
[ -f .env ] || { echo "No .env found. Copy .env.example to .env first." >&2; exit 1; }

port="$(grep -E '^WEB_PORT=' .env | tail -n1 | cut -d= -f2 || true)"
base="http://127.0.0.1:${port:-8000}"
startup_timeout="${STARTUP_TIMEOUT:-300}"
run_timeout="${RUN_WAIT_TIMEOUT:-300}"

psql() { docker compose exec -T db psql -U botplatform -d botplatform -tA -F '|' -c "$1"; }

echo "Starting the stack"
docker compose up -d --build

echo "Waiting for $base/healthz and both bots on /bots"
deadline=$((SECONDS + startup_timeout))
until curl -fsS "$base/healthz" >/dev/null 2>&1 \
  && bots="$(curl -fsS "$base/bots" 2>/dev/null)" \
  && grep -q '/bots/example/runs' <<<"$bots" \
  && grep -q '/bots/arcaptcha/runs' <<<"$bots"; do
  if ((SECONDS >= deadline)); then
    echo "The stack was not ready after ${startup_timeout}s" >&2
    exit 1
  fi
  sleep 3
done

launch_and_wait() {
  local bot="$1" mode="$2" location run_id row end
  location="$(curl -sS -o /dev/null -D - -X POST -d "mode=$mode" "$base/bots/$bot/runs" \
    | tr -d '\r' | awk 'tolower($1) == "location:" {print $2}')"
  run_id="${location##*/}"
  if [[ ! "$run_id" =~ ^[0-9a-f-]{36}$ ]]; then
    echo "Could not launch $bot ($mode): got location '$location'" >&2
    return 1
  fi
  echo "Launched $bot ($mode): run $run_id" >&2
  end=$((SECONDS + run_timeout))
  while :; do
    row="$(psql "select status, coalesce(reason,''), coalesce(challenge_id,'') from runs where id='$run_id'")"
    case "${row%%|*}" in
      queued | running) ;;
      "") echo "Run $run_id not found" >&2; return 1 ;;
      *) break ;;
    esac
    if ((SECONDS >= end)); then
      echo "Run $run_id still active after ${run_timeout}s" >&2
      row="timeout_waiting||"
      break
    fi
    sleep 3
  done
  echo "$bot|$mode|$run_id|$row"
}

results=()
results+=("$(launch_and_wait example direct)")
results+=("$(launch_and_wait arcaptcha headless)")

echo
printf '%-10s %-9s %-36s %-10s %-22s %s\n' BOT MODE RUN STATUS REASON CHALLENGE_ID
failed=0
for line in "${results[@]}"; do
  IFS='|' read -r bot mode run_id status reason challenge_id <<<"$line"
  printf '%-10s %-9s %-36s %-10s %-22s %s\n' "$bot" "$mode" "$run_id" "$status" "${reason:--}" "${challenge_id:--}"
  case "$bot:$status" in
    example:success) ;;
    arcaptcha:success | arcaptcha:blocked)
      if [ -z "$challenge_id" ]; then
        echo "FAIL: $bot run $run_id ended $status without a challenge_id" >&2
        failed=1
      fi
      ;;
    arcaptcha:failed) ;;
    *)
      echo "FAIL: $bot run $run_id ended '$status' (reason: ${reason:--})" >&2
      failed=1
      ;;
  esac
done
echo
if ((failed)); then echo "Smoke check FAILED"; else echo "Smoke check passed"; fi
exit "$failed"
