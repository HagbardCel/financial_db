#!/bin/bash

# Create hooks directory if it doesn't exist
mkdir -p .git/hooks

# Create the pre-commit hook
cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash

# Run the notebook cleaner
python scripts/clean_notebooks.py

# Get the exit status
status=$?

if [ $status -eq 1 ]; then
    echo "Notebooks were cleaned. Please review and stage the changes."
    exit 1
elif [ $status -eq 0 ]; then
    exit 0
else
    echo "Error cleaning notebooks"
    exit 1
fi
EOF

# Make the hook executable
chmod +x .git/hooks/pre-commit

echo "Git hooks installed successfully!" 