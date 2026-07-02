#!/bin/bash
# Restoration script for dashboard layout refactoring
cp templates/dashboard.html.bak templates/dashboard.html
cp static/css/style.css.bak static/css/style.css
echo "Restoration complete! Reverted templates/dashboard.html and static/css/style.css to their backups."
