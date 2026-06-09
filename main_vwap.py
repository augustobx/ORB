import MetaTrader5 as mt5
import time
import logging
import pytz
import json
import os
import csv
from datetime import datetime
import pandas as pd
import config_orb as config

# Configuración de Logging
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Logger raíz
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Evitar duplicar handlers
if not root_logger.handlers:
    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # Handler para archivo de errores (guarda WARNING, ERROR y CRITICAL)
    file_handler = logging.FileHandler("errors.log", encoding="utf-8")
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.WARNING)
    root_logger.addHandler(file_handler)


def init_mt5():
    if not mt5.initialize():
        logging.error("Fallo al inicializar MT5")
        mt5.shutdown()
        return False

    if not mt5.symbol_select(config.SYMBOL, True):
        logging.error(f"Símbolo {config.SYMBOL} no encontrado. Verifica Market Watch.")
        return False

    logging.info(
        f"Conectado a MT5. Símbolo: {config.SYMBOL} | Modo: VWAP BOUNCE INSTITUCIONAL"
    )
    return True


def get_live_vwap():
    """
    Descarga las velas del día de hoy y calcula el VWAP exacto desde la apertura de NY.
    """
    # Descargamos las últimas 600 velas (10 horas en M1, sobra para el día)
    rates = mt5.copy_rates_from_pos(config.SYMBOL, mt5.TIMEFRAME_M1, 0, 600)
    if rates is None or len(rates) == 0:
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df["hour"] = df["time"].dt.hour
    df["minute"] = df["time"].dt.minute

    # Horario del Broker para la apertura de NY
    broker_hour = config.NY_OPEN_HOUR + config.BROKER_NY_OFFSET_HOURS
    broker_minute = config.NY_OPEN_MINUTE

    # Filtramos solo la sesión desde la apertura
    hoy = pd.to_datetime('today').date()
    df['date'] = df['time'].dt.date
    session = df[
        (df['date'] == hoy) & 
        (
            ((df["hour"] == broker_hour) & (df["minute"] >= broker_minute))
            | (df["hour"] > broker_hour)
        )
    ]

    if session.empty:
        return None

    # Cálculo algorítmico del VWAP
    cum_vol = 0.0
    cum_vol_price = 0.0

    for _, row in session.iterrows():
        tp = (row["high"] + row["low"] + row["close"]) / 3
        cum_vol += row["tick_volume"]
        cum_vol_price += tp * row["tick_volume"]

    vwap = cum_vol_price / cum_vol if cum_vol > 0 else tp
    return vwap


def execute_with_fallback(request):
    """
    Intenta enviar la orden probando los 3 modos de llenado.
    Si MT5 devuelve None, captura el error profundo de la plataforma.
    """
    fill_modes = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_RETURN,
    ]

    for fill in fill_modes:
        request["type_filling"] = fill
        result = mt5.order_send(request)

        # Si result es None, el error es crítico (ej. AutoTrading apagado, desconexión)
        if result is None:
            error = mt5.last_error()
            logging.error(
                f"Rechazo crítico de la API de MT5. Código de error interno: {error}"
            )
            return None

        # Si el error NO es 10030 (Invalid filling mode), cortamos el bucle y devolvemos el resultado
        if result.retcode != 10030:
            return result

    return result


def open_market_order(order_type, sl_points, current_vwap):
    """
    Calcula el lotaje dinámico para arriesgar exactamente $100 y lanza orden a mercado.
    """
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        return None

    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    sl_price = (
        price - sl_points if order_type == mt5.ORDER_TYPE_BUY else price + sl_points
    )

    # Cálculo Dinámico de Lotes
    lot_size = config.RISK_PER_TRADE / (sl_points * config.POINT_VALUE)
    lot_size = round(max(config.MIN_LOT, min(config.MAX_LOT, lot_size)), 2)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.SYMBOL,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "tp": round(current_vwap, 2),
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": "VWAP 2.0",
    }

    result = execute_with_fallback(request)

    # Validación segura: comprobamos que result no sea None antes de usar .retcode
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        error_msg = (
            f"{result.retcode} - {result.comment}"
            if result
            else "Ejecución devuelta como None"
        )
        logging.error(f"Fallo al entrar a mercado: {error_msg}")
        return None

    logging.info(
        f"¡ENTRY EJECUTADA! {'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'} "
        f"Lotes: {lot_size:.2f} | Precio: {price:.2f} | SL: {sl_price:.2f}"
    )
    return result.order


def log_trade_to_csv(position, close_price, pnl_usd, reason):
    """
    Registra los detalles del trade en un archivo CSV.
    """
    filename = "trades_vwap.csv"
    file_exists = os.path.isfile(filename)
    
    account_info = mt5.account_info()
    balance = account_info.balance if account_info else 1.0
    roi = (pnl_usd / balance) * 100 if balance > 0 else 0.0
    
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Ticket", "Symbol", "Type", "Lots", "Entry Time", "Entry Price", "Exit Time", "Exit Price", "PnL (USD)", "ROI (%)", "Reason", "Balance"])
            
        entry_time = datetime.fromtimestamp(position.time).strftime('%Y-%m-%d %H:%M:%S')
        exit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        trade_type = "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL"
        
        writer.writerow([
            position.ticket,
            position.symbol,
            trade_type,
            position.volume,
            entry_time,
            position.price_open,
            exit_time,
            close_price,
            round(pnl_usd, 2),
            round(roi, 4),
            reason,
            round(balance, 2)
        ])

def close_position(position, reason="VWAP Touch"):
    """
    Cierra la posición abierta a precio de mercado actual.
    """
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        return False

    order_type = (
        mt5.ORDER_TYPE_SELL
        if position.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask

    # Aseguramos que el comment sea puramente ASCII y de longitud segura
    reason_ascii = "".join(c for c in reason if ord(c) < 128)[:20]

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.SYMBOL,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": f"Close: {reason_ascii}",
    }

    result = execute_with_fallback(request)

    # Validación segura al cerrar
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        error_msg = (
            f"{result.retcode} - {result.comment}"
            if result
            else "Ejecución devuelta como None"
        )
        logging.error(f"Fallo al cerrar posición: {error_msg}")
        return False

    # En caso de cierre exitoso, usar result.price si existe
    close_price = result.price if result and getattr(result, "price", 0) > 0 else price
    
    pnl = (
        (close_price - position.price_open)
        if position.type == mt5.ORDER_TYPE_BUY
        else (position.price_open - close_price)
    )
    pnl_usd = pnl * position.volume * config.POINT_VALUE
    logging.info(f"Posición Cerrada ({reason}). PnL Aprox: ${pnl_usd:.2f} USD")
    
    # Registro en CSV
    log_trade_to_csv(position, close_price, pnl_usd, reason)
    
    return True


def main():
    if not init_mt5():
        return

    ny_tz = pytz.timezone("America/New_York")
    logging.info(
        "Francotirador VWAP Iniciado. Esperando apertura de NY y estabilización..."
    )

    trade_taken_today = False
    current_date = None
    last_active_ticket = None
    last_position = None

    # Bucle principal de ejecución
    while True:
        try:
            now_ny = datetime.now(ny_tz)

            # Reset de ciclo diario
            if current_date != now_ny.date():
                current_date = now_ny.date()
                trade_taken_today = False
                logging.info(f"=== Nueva sesión VWAP: {current_date} ===")

            # Estamos dentro de la sesión operativa (NY Open + 30 mins) hasta las 15:55
            is_trading_window = (
                now_ny.hour > config.NY_OPEN_HOUR
                or (
                    now_ny.hour == config.NY_OPEN_HOUR
                    and now_ny.minute >= config.NY_OPEN_MINUTE + 30
                )
            ) and (now_ny.hour < 15 or (now_ny.hour == 15 and now_ny.minute < 55))

            # Validar si hay operaciones abiertas de nuestro bot
            positions = mt5.positions_get(
                symbol=config.SYMBOL, magic=config.MAGIC_NUMBER
            )
            has_active_position = positions and len(positions) > 0

            # DETECCIÓN DE CIERRE EXTERNO (SL/TP alcanzado por el bróker)
            if not has_active_position and last_active_ticket is not None:
                time.sleep(1)  # Dar 1 seg a MT5 para consolidar historial
                deals = mt5.history_deals_get(position=last_active_ticket)
                if deals:
                    out_deal = next((d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None)
                    if out_deal:
                        logging.warning(f"¡ALERTA! Posición {last_active_ticket} cerrada por el Bróker (SL/TP). PnL Realizado: ${out_deal.profit:.2f} USD")
                        if last_position:
                            log_trade_to_csv(last_position, out_deal.price, out_deal.profit, "Broker SL/TP")
                    else:
                        logging.warning(f"¡ALERTA! Posición {last_active_ticket} cerrada por el Bróker.")
                        if last_position:
                            log_trade_to_csv(last_position, 0.0, 0.0, "Broker Closed (Unknown)")
                last_active_ticket = None
                last_position = None
                
            if has_active_position:
                last_active_ticket = positions[0].ticket
                last_position = positions[0]

            if is_trading_window:
                vwap = get_live_vwap()
                tick = mt5.symbol_info_tick(config.SYMBOL)

                if vwap and tick:
                    current_price = (tick.bid + tick.ask) / 2
                    distancia = current_price - vwap

                    # LOGS (Imprime cada 1 minuto para no saturar la consola)
                    if now_ny.second == 0:
                        logging.info(
                            f"Monitor VWAP -> Precio: {current_price:.2f} | VWAP: {vwap:.2f} | Distancia: {distancia:.2f} pts"
                        )

                    # 1. BUSCAR ENTRADA (Si no operamos hoy y no hay pos abierta)
                    if not trade_taken_today and not has_active_position:
                        if distancia > config.VWAP_EXTENSION:
                            logging.warning(
                                f"¡SOBRECOMPRA EXTREMA DETECTADA! Distancia: {distancia:.2f} pts. Entrando en CORTO (SELL)..."
                            )
                            result_ticket = open_market_order(
                                mt5.ORDER_TYPE_SELL, config.VWAP_SL_PTS, vwap
                            )
                            if result_ticket:
                                trade_taken_today = True
                            else:
                                logging.warning("Cooldown 60s activado tras rechazo de orden (Anti-Spam)...")
                                time.sleep(60)

                        elif distancia < -config.VWAP_EXTENSION:
                            logging.warning(
                                f"¡SOBREVENTA EXTREMA DETECTADA! Distancia: {distancia:.2f} pts. Entrando en LARGO (BUY)..."
                            )
                            result_ticket = open_market_order(
                                mt5.ORDER_TYPE_BUY, config.VWAP_SL_PTS, vwap
                            )
                            if result_ticket:
                                trade_taken_today = True
                            else:
                                logging.warning("Cooldown 60s activado tras rechazo de orden (Anti-Spam)...")
                                time.sleep(60)

                    # 2. GESTIÓN DE SALIDA DINÁMICA (Si estamos en un trade)
                    elif has_active_position:
                        pos = positions[0]
                        buffer_salida = 3.0  
                        # Si estamos COMPRADOS y el precio cruza por encima del VWAP (Llegamos al objetivo)
                        if pos.type == mt5.ORDER_TYPE_BUY and tick.bid >= (vwap - buffer_salida):
                            close_position(pos, "VWAP Target")

                        # Si estamos VENDIDOS y el precio cruza por debajo del VWAP (Llegamos al objetivo)
                        elif pos.type == mt5.ORDER_TYPE_SELL and tick.ask <= (vwap + buffer_salida):
                            close_position(pos, "VWAP Target")

            # 3. CIERRE FORZADO DE FIN DE DÍA (15:55 NY)
            if now_ny.hour == 15 and now_ny.minute >= 55 and has_active_position:
                logging.warning(
                    "¡Cierre forzado 15:55 NY! Liquidando posición para evitar Swaps/Gaps."
                )
                close_position(positions[0], "EOD Close")

            # 4. EXPORTAR HEARTBEAT AL DASHBOARD
            status_dir = os.path.join(os.path.dirname(__file__), "dashboard", "data")
            os.makedirs(status_dir, exist_ok=True)
            status_path = os.path.join(status_dir, "live_status.json")
            try:
                pos_str = "None"
                pnl_usd = 0.0
                dist_val = distancia if 'distancia' in locals() else 0.0
                
                if has_active_position:
                    pos_str = "BUY" if positions[0].type == mt5.ORDER_TYPE_BUY else "SELL"
                    tick = mt5.symbol_info_tick(config.SYMBOL)
                    if tick:
                        curr_price = (tick.bid + tick.ask) / 2
                        pnl_pts = (curr_price - positions[0].price_open) if pos_str == "BUY" else (positions[0].price_open - curr_price)
                        pnl_usd = pnl_pts * positions[0].volume * config.POINT_VALUE
                        
                with open(status_path, "w") as f:
                    json.dump({
                        "vwap_dist": round(dist_val, 2),
                        "position": pos_str,
                        "pnl_usd": round(pnl_usd, 2),
                        "timestamp": time.time(),
                        "status": "ONLINE"
                    }, f)
            except Exception as e:
                pass

            # Pausa breve del bucle (1 segundo para monitorear ticks rápido pero sin quemar CPU)
            time.sleep(1)

        except Exception as e:
            logging.error(f"Error crítico en el bucle principal VWAP: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
