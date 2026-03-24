#!/usr/bin/env bash
# gpu_batch_extract.sh — Upload PDFs to Vast GPU, run marker-pdf, download results, destroy instance.
# Usage: bash gpu_batch_extract.sh /tmp/paper-research/
#
# Lifecycle: search offer (≥99% reliability) → create → SSH wait (3 min, retry) → upload → extract → download → destroy
set -euo pipefail

PDF_DIR="${1:?Usage: gpu_batch_extract.sh <pdf-directory>}"
OUTPUT_DIR="${PDF_DIR}/output"
mkdir -p "$OUTPUT_DIR"

PDF_COUNT=$(find "$PDF_DIR" -maxdepth 1 -name '*.pdf' | wc -l)
if [ "$PDF_COUNT" -eq 0 ]; then
    echo "ERROR: No PDFs found in $PDF_DIR"
    exit 1
fi
echo "Found $PDF_COUNT PDFs to process."

MAX_SSH_WAIT=180
MAX_RETRIES=3
INSTANCE_ID=""

cleanup() {
    if [ -n "$INSTANCE_ID" ]; then
        echo "Destroying instance $INSTANCE_ID..."
        vastai destroy instance "$INSTANCE_ID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

search_and_create() {
    echo "Searching for GPU (≥99% reliability, good bandwidth)..."
    local OFFER_ID
    OFFER_ID=$(vastai search offers \
        'gpu_name=RTX_3090 num_gpus=1 reliability>0.99 dph<0.25 inet_down>100 inet_up>50' \
        -o 'dph' --raw 2>/dev/null | python3 -c "
import sys, json
offers = json.load(sys.stdin)
# Prefer US/EU regions
for o in offers:
    geo = o.get('geolocation', '') or ''
    if any(r in geo.lower() for r in ['us', 'united states', 'canada', 'europe', 'germany', 'france', 'netherlands', 'uk', 'sweden']):
        print(o['id']); exit()
if offers:
    print(offers[0]['id'])
" 2>/dev/null)

    if [ -z "$OFFER_ID" ]; then
        # Broaden: any ≥20GB VRAM GPU, still ≥99% reliability
        OFFER_ID=$(vastai search offers \
            'gpu_ram>=20 num_gpus=1 reliability>0.99 dph<0.35 inet_down>100 inet_up>50' \
            -o 'dph' --raw 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data: print(data[0]['id'])
" 2>/dev/null)
    fi

    if [ -z "$OFFER_ID" ]; then
        # Last resort: drop to 95% reliability
        OFFER_ID=$(vastai search offers \
            'gpu_ram>=20 num_gpus=1 reliability>0.95 dph<0.35 inet_down>50' \
            -o 'dph' --raw 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data: print(data[0]['id'])
" 2>/dev/null)
    fi

    if [ -z "$OFFER_ID" ]; then
        echo "ERROR: No suitable GPU offers found."
        return 1
    fi

    echo "Creating instance from offer $OFFER_ID..."
    local CREATE_OUT
    CREATE_OUT=$(vastai create instance "$OFFER_ID" \
        --image pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel \
        --disk 50 --ssh --direct 2>&1)
    echo "$CREATE_OUT"

    INSTANCE_ID=$(echo "$CREATE_OUT" | grep -oP 'new contract is \K[0-9]+' || echo "")
    if [ -z "$INSTANCE_ID" ]; then
        INSTANCE_ID=$(echo "$CREATE_OUT" | grep -oP '[0-9]+' | tail -1)
    fi
    [ -n "$INSTANCE_ID" ] || { echo "ERROR: Could not get instance ID"; return 1; }
    echo "Instance: $INSTANCE_ID"
}

wait_for_ssh() {
    local elapsed=0
    while [ $elapsed -lt $MAX_SSH_WAIT ]; do
        local info
        info=$(vastai show instances --raw 2>/dev/null | python3 -c "
import sys, json
for i in json.load(sys.stdin):
    if str(i['id']) == '$INSTANCE_ID' and i.get('actual_status') == 'running':
        host = i.get('ssh_host', '')
        port = i.get('ssh_port', '')
        if host and port:
            print(f'{host} {port}')
            break
" 2>/dev/null)
        if [ -n "$info" ]; then
            SSH_HOST=$(echo "$info" | awk '{print $1}')
            SSH_PORT=$(echo "$info" | awk '{print $2}')
            if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -p "$SSH_PORT" "root@$SSH_HOST" 'echo ok' &>/dev/null; then
                echo "SSH ready: $SSH_HOST:$SSH_PORT"
                return 0
            fi
        fi
        sleep 5
        elapsed=$((elapsed + 5))
        echo "Waiting for SSH... (${elapsed}s/${MAX_SSH_WAIT}s)"
    done
    return 1
}

SSH_HOST=""
SSH_PORT=""

for attempt in $(seq 1 $MAX_RETRIES); do
    echo "=== Attempt $attempt/$MAX_RETRIES ==="
    search_and_create || continue

    if wait_for_ssh; then
        break
    fi

    echo "SSH failed after ${MAX_SSH_WAIT}s. Destroying instance $INSTANCE_ID..."
    vastai destroy instance "$INSTANCE_ID" 2>/dev/null || true
    INSTANCE_ID=""

    if [ "$attempt" -eq "$MAX_RETRIES" ]; then
        echo "ERROR: All $MAX_RETRIES attempts failed."
        exit 1
    fi
    sleep 5
done

SSH_CMD="ssh -o StrictHostKeyChecking=no -p $SSH_PORT root@$SSH_HOST"
SCP_CMD="scp -o StrictHostKeyChecking=no -P $SSH_PORT"

# Install marker-pdf
echo "Installing marker-pdf..."
$SSH_CMD 'pip install marker-pdf 2>&1 | tail -3 && pip install --upgrade torchvision 2>&1 | tail -1 && echo "INSTALL_DONE"'

# Upload PDFs
echo "Uploading PDFs..."
$SSH_CMD 'mkdir -p /tmp/pdfs /tmp/output'
$SCP_CMD "$PDF_DIR"/*.pdf "root@$SSH_HOST:/tmp/pdfs/"

# Run marker-pdf batch
echo "Running marker-pdf..."
$SSH_CMD 'cd /tmp && marker /tmp/pdfs --output_dir /tmp/output 2>&1'

# Download results
echo "Downloading results..."
$SCP_CMD -r "root@$SSH_HOST:/tmp/output/*" "$OUTPUT_DIR/"

echo "Extraction complete. Results in: $OUTPUT_DIR"
echo "Destroying instance..."
# trap handles cleanup
