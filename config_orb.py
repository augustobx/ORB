import MetaTrader5 as mt5

# ==========================================
# CONFIGURACIÓN: VWAP BOUNCE INSTITUCIONAL
# ==========================================

SYMBOL = "NAS100"

# DNI Único para el bot VWAP (Evita conflictos con el bot ORB o SMC)
MAGIC_NUMBER = 100200

# ------------------------------------------
# GESTIÓN DE RIESGO DINÁMICA
# ------------------------------------------
RISK_PER_TRADE = 100.0  # Pérdida máxima exacta en dólares por trade
POINT_VALUE = (
    1.0  # Valor monetario de 1.0 punto por lote (NAS100: 1 lote = 1 USD por punto)
)
MIN_LOT = 0.01  # Lote mínimo permitido por el bróker
MAX_LOT = 100.0  # Lote máximo permitido por el bróker

# ------------------------------------------
# PARÁMETROS DE TIEMPO (Hora de Nueva York)
# ------------------------------------------
NY_OPEN_HOUR = 9
NY_OPEN_MINUTE = 30

# El VWAP necesita unos minutos para estabilizarse antes de operar
VWAP_WARMUP_MINUTES = 30

# ------------------------------------------
# PARÁMETROS DE LA ESTRATEGIA ORB
# ------------------------------------------
ORB_MINUTES = 15  # Tamaño de la caja en minutos
MAX_BOX_SIZE_PERCENT = 0.6  # Máximo tamaño de la caja permitido (%)
BUFFER_POINTS = 10.0  # Distancia para las órdenes stop
TS_ACTIVATION_POINTS = 45.0  # Puntos de ganancia para activar Trailing Stop
TS_DISTANCE_POINTS = 25.0  # Distancia del Trailing Stop


# ------------------------------------------
# PARÁMETROS DE LA ESTRATEGIA VWAP
# ------------------------------------------
# Distancia en puntos al VWAP para considerar que el precio está "sobre-extendido"
VWAP_EXTENSION = 80.0

# Stop Loss fijo de protección matemática (Si el precio no rebota, cortamos en seco)
VWAP_SL_PTS = 40.0

# ------------------------------------------
# CONFIGURACIÓN DEL BROKER
# ------------------------------------------
BROKER_NY_OFFSET_HOURS = 7
