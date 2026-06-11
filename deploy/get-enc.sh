#!/usr/bin/env bash
# Download the Tampa Bay ENC cells into backend/data/enc for ingestion.
set -euo pipefail
cd "$(dirname "$0")/../backend"
mkdir -p data/enc && cd data/enc
CELLS="US5TPACB US5TPACC US5TPACD US5TPACE US5TPACF US5TPACG US5TPADC US5TPADD \
US5TPADE US5TPADF US5TPADG US5TPADH US5TPAEF US5TPAEG US5TPAEH US5TPAEI \
US5TPAFG US5TPAFH US5TPAFI US5TPAGH US5TPAHI US5TPAHJ US4FL1PQ"
for c in $CELLS; do
  echo "  $c"
  curl -sf -o "$c.zip" "https://charts.noaa.gov/ENCs/$c.zip"
done
echo "done: $(ls *.zip | wc -l) cells"
