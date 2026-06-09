#!/bin/bash
echo "==================================================="
echo "    INICIANDO QUANT TRADER SYSTEM (BOT + DASH)     "
echo "==================================================="
echo ""

# Nos aseguramos de estar en el directorio correcto
cd "$(dirname "$0")"

# Ejecutamos el launcher de python
python3 launcher.py
