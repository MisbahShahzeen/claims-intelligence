#!/usr/bin/env bash
# Submit three internally consistent claims and attach their documents.
#
# Each is built to exercise a different reasoning path:
#   1. clean       - all policy conditions met, expect covered
#   2. excluded    - learner permit driver, expect an exclusion to bite
#   3. suspicious  - delayed FIR, both keys, listed for sale, expect high risk
#
# Idempotent on documents by content hash, but each run creates new claims.
set -euo pipefail

API="${API:-http://localhost:8000}"
EMAIL="${EMAIL:-adjuster@example.com}"
PASSWORD="${PASSWORD:-AdjusterPass123!}"
DOCS="$(dirname "$0")/documents"

json_field() { python -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }

echo "authenticating against $API"
TOKEN=$(curl -sS -X POST "$API/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | json_field access_token)

submit() {
  local label=$1 payload=$2 fir=$3 estimate=$4
  echo ""
  echo "--- $label ---"

  local response id number
  response=$(curl -sS -X POST "$API/claims" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$payload")

  id=$(echo "$response" | json_field id)
  number=$(echo "$response" | json_field claim_number)
  echo "submitted $number"

  for doc in "$fir" "$estimate"; do
    [ -z "$doc" ] && continue
    curl -sS -o /dev/null -X POST "$API/claims/$id/documents" \
      -H "Authorization: Bearer $TOKEN" \
      -F "file=@$DOCS/$doc;type=text/plain"
    echo "  uploaded $doc"
  done

  echo "$number $id" >> /tmp/demo-claims.txt
}

: > /tmp/demo-claims.txt

submit "1. Clean collision, all conditions met" '{
  "policy_number": "MOT-2026-0001",
  "loss_date": "2026-07-28",
  "loss_type": "collision",
  "description": "Rear-ended while stationary at the Silk Board signal on Hosur Road at approximately 09:15. Damage to rear bumper, boot lid and left tail lamp. Third party admitted liability at the scene and FIR was filed the same morning. Vehicle in private use, driver licensed and sober.",
  "claimed_amount": "127971.00"
}' clean-fir.txt clean-estimate.txt

submit "2. Learner permit driver, exclusion expected" '{
  "policy_number": "MOT-2026-0001",
  "loss_date": "2026-07-27",
  "loss_type": "collision",
  "description": "Single vehicle collision with a concrete median barrier on the Hosur Road service lane at approximately 02:40. Vehicle was being driven by a family member holding a learner permit with no qualified licence holder present. Extensive front end and suspension damage.",
  "claimed_amount": "328512.00"
}' excluded-fir.txt excluded-estimate.txt

submit "3. Delayed theft report, high risk expected" '{
  "policy_number": "MOT-2026-0001",
  "loss_date": "2026-07-24",
  "loss_type": "theft",
  "description": "Vehicle reported taken from unattended roadside parking on Varthur Road overnight. FIR lodged approximately 68 hours after the stated incident time. Both original keys remain with the owner and no evidence of forced entry was found at the scene.",
  "claimed_amount": "680000.00"
}' suspicious-fir.txt ""

echo ""
echo "submitted:"
cat /tmp/demo-claims.txt
echo ""
echo "The pipeline now runs: extraction, then retrieval and assessment."
echo "Allow roughly 60 to 90 seconds for all five documents."
