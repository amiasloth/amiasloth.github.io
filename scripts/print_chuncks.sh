#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 FILE [START] [END]"
    exit 1
fi

FILE="$1"
START="${2:-0}"
END="${3:-30}"

jq -r \
    --argjson start "$START" \
    --argjson end "$END" '
    .sections[0].chunks[$start:$end][]
    | .t
' "$FILE"
# #!/usr/bin/env bash
# 
# set -euo pipefail
# 
# if [[ $# -lt 1 ]]; then
#     echo "Usage: $0 FILE [START] [END]"
#     exit 1
# fi
# 
# FILE="$1"
# START="${2:-0}"
# END="${3:-30}"
# 
# jq -r \
#     --argjson start "$START" \
#     --argjson end "$END" '
#     .sections[0].chunks[$start:$end]
#     | reduce .[] as $c (
#         "";
#         if . == "" then
#             $c.t
#         elif ($c.cont // 0) == 1 then
#             . + " " + $c.t
#         else
#             . + "\n" + $c.t
#         end
#     )
# ' "$FILE"
