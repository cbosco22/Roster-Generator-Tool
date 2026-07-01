#!/usr/bin/env bash
# One-time setup + render-all for the Navy Baseball recruiting graphics.
# Run from inside the /source folder:  bash setup.sh
set -e

# 1) Install the three display fonts (open-source, from Google Fonts)
mkdir -p ~/.fonts
curl -sL -o ~/.fonts/Anton-Regular.ttf        "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
curl -sL -o ~/.fonts/Oswald.ttf               "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf"
curl -sL -o ~/.fonts/BarlowCondensed-Bold.ttf "https://raw.githubusercontent.com/google/fonts/main/ofl/barlowcondensed/BarlowCondensed-Bold.ttf"
fc-cache -f

# 2) Rendering engine
npm i playwright
npx playwright install chromium

# 3) Render every graphic
for f in Navy_Baseball_*.html; do node render.js "$f"; done
echo "Done. PNGs written next to their .html sources."
