#!/usr/bin/env bash
# הפעלה מהירה: יצירת נתוני דמו (אם צריך) והרמת השרת
set -e
cd "$(dirname "$0")"
if [ ! -f pronear.db ]; then
  echo "יוצר נתוני דמו…"
  python3 seed.py
fi
exec python3 -m pronear.server "$@"
