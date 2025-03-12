#!/usr/bin/env sh

####################################################################################################
# This script uses pyreverse (from the pylint package) to automatically generate architecture
# diagrams for each package in the project.
####################################################################################################

if ! command -v pyreverse &> /dev/null
then
    echo "pyreverse could not be found. Please install pylint."
    exit 1
fi

OUTPUT_FORMAT="mmd"
PYREVERSE_OPTIONS="--colorized -o $OUTPUT_FORMAT"

SEARCH_DEPTH=2  # Search for Python packages up to this depth

for PACKAGE_INIT in $(find . -d $SEARCH_DEPTH -name __init__.py)
do
    PACKAGE_NAME=$(echo $PACKAGE_INIT | cut -f 2 -d /)
    echo "Generating class diagram for package '$PACKAGE_NAME'..."
    pyreverse $PYREVERSE_OPTIONS -p $PACKAGE_NAME $PACKAGE_NAME

    OUTPUT_FILE="$PACKAGE_NAME/architecture.md"
    echo "Writing to file '$OUTPUT_FILE'..."
    echo "# Architecture for '$PACKAGE_NAME'" > $OUTPUT_FILE
    echo "" >> $OUTPUT_FILE
    
    echo "## Classes" >> $OUTPUT_FILE    
    echo "" >> $OUTPUT_FILE
    echo ":::mermaid" >> $OUTPUT_FILE
    cat classes_$PACKAGE_NAME.$OUTPUT_FORMAT >> $OUTPUT_FILE
    rm classes_$PACKAGE_NAME.$OUTPUT_FORMAT
    echo ":::" >> $OUTPUT_FILE
    echo "" >> $OUTPUT_FILE

    echo "## Packages" >> $OUTPUT_FILE
    echo "" >> $OUTPUT_FILE
    echo ":::mermaid" >> $OUTPUT_FILE
    cat packages_$PACKAGE_NAME.$OUTPUT_FORMAT >> $OUTPUT_FILE
    rm packages_$PACKAGE_NAME.$OUTPUT_FORMAT
    echo ":::" >> $OUTPUT_FILE
done
