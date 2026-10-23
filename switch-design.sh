#!/bin/bash
REPO="/home/ubuntu/web/Traderwatch-repo"
cd "$REPO"

if [ "$1" = "apple" ]; then
    cp apple-style/index.html index.html
    echo "Switched to Apple Bento style index.html"
elif [ "$1" = "original" ]; then
    cp backup-original/index.html index.html
    echo "Switched back to Original index.html"
else
    echo "Usage: ./switch-design.sh [apple|original]"
    exit 1
fi
git add index.html
git commit -m "design: switch to $1 style index.html"
git push origin main
echo "Pushed to GitHub Pages."
