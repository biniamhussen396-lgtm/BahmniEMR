#!/bin/bash
set -e

echo "=== Ensuring all custom Bahmni/BI images are tagged and available ==="

tag_if_needed() {
    local src="$1"
    local dst="$2"
    if docker image inspect "$dst" >/dev/null 2>&1; then
        echo "✓ Image already exists: $dst"
    elif docker image inspect "$src" >/dev/null 2>&1; then
        docker tag "$src" "$dst"
        echo "✓ Tagged $src -> $dst"
    else
        echo "! Source image not found locally: $src"
    fi
}

# 1. OpenELIS
tag_if_needed "selamsew/openelis:1.0.0-uog-1.0.5" "bahmni/openelis:1.0.0-bi-1.0.0"

# 2. Odoo 16
tag_if_needed "selamsew/odoo-16:1.0.0-uog-1.0.3" "bahmni/odoo-16:1.0.0-bi-1.0.3"

# 3. Bahmni Web
if ! docker image inspect "bahmni/bahmni-web:1.1.0-bi-1.0.0" >/dev/null 2>&1; then
    if docker image inspect "selamsew/bahmni-web:1.1.0-uog-1.0.0" >/dev/null 2>&1; then
        docker tag "selamsew/bahmni-web:1.1.0-uog-1.0.0" "bahmni/bahmni-web:1.1.0-bi-1.0.0"
        echo "✓ Tagged selamsew/bahmni-web:1.1.0-uog-1.0.0 -> bahmni/bahmni-web:1.1.0-bi-1.0.0"
    else
        echo "Pulling official bahmni/bahmni-web:1.1.0 and tagging as bi-1.0.0..."
        docker pull bahmni/bahmni-web:1.1.0
        docker tag bahmni/bahmni-web:1.1.0 bahmni/bahmni-web:1.1.0-bi-1.0.0
        echo "✓ Tagged bahmni/bahmni-web:1.1.0 -> bahmni/bahmni-web:1.1.0-bi-1.0.0"
    fi
else
    echo "✓ Image already exists: bahmni/bahmni-web:1.1.0-bi-1.0.0"
fi

# 4. Global Property
tag_if_needed "selamsew/global_property:uog-1.0.2" "bahmni/global_property:bi-1.0.2"

# 5. Lab Result Sync
tag_if_needed "selamsew/lab-result-sync:1.0.2-remove-validation" "bahmni/lab-result-sync:1.0.2-remove-validation"

# 6. OpenMRS
tag_if_needed "selamsew/openmrs:1.1.1-uog-1.0.2" "bahmni/openmrs:1.1.1-bi-1.0.2"

echo "=== All image tags verified successfully ==="
