#!/usr/bin/env bash
# Throw-away lab for the template workflows: PostgreSQL 16 with integrations_db
# created by db/liquibase/master.xml, and hop-run from the official apache/hop
# images on a copy of the working tree (tests/hop/work/copy), never on the
# repository itself.
#
# Usage: tests/hop/lab.sh up | down | copy | sql "<query>"
#        tests/hop/lab.sh run <hop version> <file> [<params> [<variables>]]
#   run prints RC=<hop-run exit code>; the Hop log is tests/hop/work/hoprun.log.
set -euo pipefail
unset CDPATH
HERE="$(cd "$(dirname "$0")" && pwd -P)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
WORK="$HERE/work"
NET=hoptpl-net
PG=hoptpl-pg
PG_IMAGE=postgres:16-alpine
LB_IMAGE=liquibase/liquibase:4.33.0

usage() { echo "usage: tests/hop/lab.sh up | down | copy | sql <query> | run <hop version> <file> [<params> [<variables>]]" >&2; exit 64; }
sql() { docker exec -i "$PG" psql -U postgres -d integrations_db -At -v ON_ERROR_STOP=1 -c "$1"; }

case "${1:-}" in
  up)
    docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker run -d --name "$PG" --network "$NET" -e POSTGRES_PASSWORD=password \
      -e POSTGRES_DB=integrations_db "$PG_IMAGE" >/dev/null
    # The init server listens on the socket only: wait for TCP, i.e. the final server.
    for _ in $(seq 1 60); do
      docker exec "$PG" pg_isready -h 127.0.0.1 -U postgres -d integrations_db >/dev/null 2>&1 && break
      sleep 1
    done
    docker exec "$PG" pg_isready -h 127.0.0.1 -U postgres -d integrations_db >/dev/null \
      || { echo "ERROR: PostgreSQL not ready" >&2; exit 1; }
    docker run --rm --network "$NET" -v "$REPO/db/liquibase:/liquibase/changelog:ro" "$LB_IMAGE" \
      --url="jdbc:postgresql://$PG:5432/integrations_db" --username=postgres --password=password \
      --search-path=/liquibase/changelog --changelog-file=master.xml update >/dev/null
    docker exec -i "$PG" psql -U postgres -d integrations_db -q -v ON_ERROR_STOP=1 \
      < "$HERE/fixtures/processes.sql"
    echo "OK lab up"
    ;;
  down)
    docker rm -f "$PG" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    rm -rf "$WORK"
    echo "OK lab down"
    ;;
  copy)
    rm -rf "$WORK/copy"
    mkdir -p "$WORK/copy"
    # Tracked and untracked (not ignored) files of the working tree, as they are now.
    (cd "$REPO" && git ls-files -z --cached --others --exclude-standard \
      | tar --null --ignore-failed-read -T - -cf -) | tar -x -C "$WORK/copy"
    for p in vartest uuidtest; do
      mkdir -p "$WORK/copy/src/project/main/$p"
      cp "$HERE/fixtures/start.hwf" "$WORK/copy/src/project/main/$p/start.hwf"
    done
    mkdir -p "$WORK/copy/logs" "$WORK/copy/temp"
    echo "OK copy $WORK/copy"
    ;;
  sql)
    [[ $# -eq 2 ]] || usage
    sql "$2"
    ;;
  run)
    [[ $# -ge 3 && $# -le 5 ]] || usage
    ver="$2" file="$3" params="${4:-}" vars="${5:-}"
    mkdir -p "$WORK"
    set +e
    docker run --rm --network "$NET" --user "$(id -u):$(id -g)" \
      -e HOME=/tmp -e HOP_CONFIG_FOLDER=/tmp/hop-config -e HOP_AUDIT_FOLDER=/tmp/hop-audit \
      -v "$WORK/copy:/project" -v "$HERE:/tests:ro" \
      --entrypoint /bin/bash "apache/hop:$ver" /tests/entry.sh "$file" "$params" "$vars" \
      > "$WORK/hoprun.log" 2>&1
    rc=$?
    set -e
    echo "RC=$rc"
    ;;
  *) usage ;;
esac
