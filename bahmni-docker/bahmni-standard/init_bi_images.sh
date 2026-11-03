#!/bin/bash
set -e

echo "=== Ensuring all custom Bahmni/BI images are tagged and available ==="

ensure_image() {
    local src="$1"
    local dst="$2"
    if docker image inspect "$dst" >/dev/null 2>&1; then
        echo "✓ Target image already exists: $dst"
    elif docker image inspect "$src" >/dev/null 2>&1; then
        docker tag "$src" "$dst"
        echo "✓ Tagged local $src -> $dst"
    else
        echo "--> Pulling $src from Docker Hub..."
        if docker pull "$src"; then
            docker tag "$src" "$dst"
            echo "✓ Pulled and tagged $src -> $dst"
        else
            echo "⚠️ Failed to pull $src"
        fi
    fi
}

# 1. OpenELIS
ensure_image "selamsew/openelis:1.0.0-uog-1.0.5" "bahmni/openelis:1.0.0-bi-1.0.0"

# 2. Odoo 16
ensure_image "selamsew/odoo-16:1.0.0-uog-1.0.3" "bahmni/odoo-16:1.0.0-bi-1.0.3"

# 3. Bahmni Web
if ! docker image inspect "bahmni/bahmni-web:1.1.0-bi-1.0.0" >/dev/null 2>&1; then
    if docker image inspect "selamsew/bahmni-web:1.1.0-uog-1.0.0" >/dev/null 2>&1; then
        docker tag "selamsew/bahmni-web:1.1.0-uog-1.0.0" "bahmni/bahmni-web:1.1.0-bi-1.0.0"
        echo "✓ Tagged local selamsew/bahmni-web:1.1.0-uog-1.0.0 -> bahmni/bahmni-web:1.1.0-bi-1.0.0"
    else
        echo "--> Pulling official bahmni/bahmni-web:1.1.0..."
        docker pull bahmni/bahmni-web:1.1.0
        docker tag bahmni/bahmni-web:1.1.0 bahmni/bahmni-web:1.1.0-bi-1.0.0
        echo "✓ Pulled and tagged bahmni/bahmni-web:1.1.0 -> bahmni/bahmni-web:1.1.0-bi-1.0.0"
    fi
else
    echo "✓ Target image already exists: bahmni/bahmni-web:1.1.0-bi-1.0.0"
fi

# 4. Global Property
ensure_image "selamsew/global_property:uog-1.0.2" "bahmni/global_property:bi-1.0.2"

# 5. Lab Result Sync
ensure_image "selamsew/lab-result-sync:1.0.2-remove-validation" "bahmni/lab-result-sync:1.0.2-remove-validation"

# 6. OpenMRS (fallback if bi-1.0.2 is requested)
ensure_image "selamsew/openmrs:1.1.1-uog-1.0.2" "bahmni/openmrs:1.1.1-bi-1.0.2"

echo "=== All custom images are ready! ==="
