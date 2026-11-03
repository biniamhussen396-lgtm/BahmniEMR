#!/bin/bash
# ==============================================================================
#  Bahmni Facility Manager Script
#  Easily pull, start, stop, or configure Bahmni based on facility type:
#    - Health Center (hc)   : EMR, Lab, Odoo, eAPTs, Reports, Backup (No PACS, No Ollama)
#    - Hospital (hospital) : Full Stack including PACS (Orthanc/OHIF/DCM4CHEE) & Ollama AI
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ACTION="${1:-help}"
FACILITY="${2:-}"

usage() {
    echo "Usage: ./facility.sh [command] [facility_type]"
    echo ""
    echo "Commands:"
    echo "  up [hc|hospital]    - Start services for specified facility (default: from .env)"
    echo "  pull [hc|hospital]  - Pull images for specified facility (skips unused images)"
    echo "  stop                - Stop all running containers"
    echo "  status              - Show status of running containers"
    echo "  set [hc|hospital]   - Set default facility profile in .env"
    echo ""
    echo "Examples:"
    echo "  ./facility.sh up hc          # Start only Health Center services (no PACS, no Ollama)"
    echo "  ./facility.sh pull hc        # Pull only Health Center images"
    echo "  ./facility.sh up hospital    # Start full Hospital services (with PACS and Ollama)"
    echo "  ./facility.sh set hc         # Set .env to permanently use HC profile"
    exit 1
}

set_profile() {
    local target="$1"
    if [ "$target" != "hc" ] && [ "$target" != "hospital" ]; then
        echo "Error: Facility must be either 'hc' or 'hospital'"
        exit 1
    fi
    sed -i -E "s/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=$target/" .env
    echo "✓ Default profile in .env set to: $target"
}

case "$ACTION" in
    up)
        if [ -n "$FACILITY" ]; then
            echo "Starting Bahmni for facility type: $FACILITY..."
            docker compose --env-file .env --profile "$FACILITY" up -d
        else
            echo "Starting Bahmni with current .env profile..."
            docker compose --env-file .env up -d
        fi
        ;;
    pull)
        if [ -n "$FACILITY" ]; then
            echo "Pulling images for facility type: $FACILITY..."
            docker compose --env-file .env --profile "$FACILITY" pull
        else
            echo "Pulling images with current .env profile..."
            docker compose --env-file .env pull
        fi
        ;;
    stop|down)
        echo "Stopping Bahmni containers..."
        docker compose --env-file .env down
        ;;
    status|ps)
        docker compose --env-file .env ps
        ;;
    set)
        if [ -z "$FACILITY" ]; then
            usage
        fi
        set_profile "$FACILITY"
        ;;
    *)
        usage
        ;;
esac
