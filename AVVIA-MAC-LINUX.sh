#!/bin/sh
cd "$(dirname "$0")" || exit 1
printf '\nGoldBet Piedimonte — Avvio gestionale\nApri http://127.0.0.1:8787 nel browser\n\n'
exec python3 server.py