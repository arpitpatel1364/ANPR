#!/usr/bin/env bash
source "$(dirname "$0")/utils.sh"

info "Running validation..."

[[ $EUID -ne 0 ]] && die "Run with sudo"

command -v /usr/bin/python3 || die "Python missing"
command -v /usr/bin/pip || die "pip missing"

[[ -f "$ROOT_DIR/run.sh" ]] || die "run.sh missing"

# Check model files
for f in best.pt yolov8n.pt newmodel/best_lprnet.pth; do
    [[ -f "$ROOT_DIR/$f" ]] || warn "Missing model: $f"
done