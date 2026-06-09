import MetaTrader5 as mt5
import time
import logging
import pytz
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
        logging.error(f"Símbolo {config.SYMBOL} no encontrado")
        return False

    logging.info(f"Conectado a MT5. Símbolo: {config.SYMBOL}")
    return True


def get_orb_box():
    rates = mt5.copy_rates_from_pos(
        config.SYMBOL, mt5.TIMEFRAME_M1, 1, config.ORB_MINUTES
    )
    if rates is None or len(rates) < config.ORB_MINUTES:
        logging.error("No se pudieron obtener suficientes datos de velas para la caja.")
        return None, None

    df = pd.DataFrame(rates)
    return df["high"].max(), df["low"].min()


def place_stop_order(order_type, price, sl_price, volume):
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": config.SYMBOL,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "tp": 0.0,  # Sin TP, dejamos correr con Trailing Stop
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": "ORB Breakout V1",
        "type_time": mt5.ORDER_TIME_DAY,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(
            f"Fallo al enviar orden Stop: {result.retcode} - {result.comment}"
        )
        return None

    logging.info(
        f"Orden pendiente colocada: {'BUY_STOP' if order_type == mt5.ORDER_TYPE_BUY_STOP else 'SELL_STOP'} de {volume} lotes en {price:.2f} (SL: {sl_price:.2f})"
    )
    return result.order


def cancel_order(ticket):
    request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(f"Orden pendiente {ticket} cancelada exitosamente (Regla OCO).")


def close_position(position):
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        return False

    order_type = (
        mt5.ORDER_TYPE_SELL
        if position.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": config.SYMBOL,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,
        "price": price,
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": "Cierre Fin de Dia",
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logging.info(
            f"Posición {position.ticket} cerrada exitosamente por Fin de Día a {price}"
        )
        return True
    return False


def manage_trailing_stop(position):
    tick = mt5.symbol_info_tick(config.SYMBOL)
    if tick is None:
        return

    if position.type == mt5.ORDER_TYPE_BUY:
        profit_points = tick.bid - position.price_open
        if profit_points >= config.TS_ACTIVATION_POINTS:
            new_sl = tick.bid - config.TS_DISTANCE_POINTS
            if position.sl == 0.0 or new_sl > position.sl:
                symbol_info = mt5.symbol_info(config.SYMBOL)
                if new_sl < tick.bid - (
                    symbol_info.trade_stops_level * symbol_info.point
                ):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": position.ticket,
                        "symbol": config.SYMBOL,
                        "sl": new_sl,
                        "tp": position.tp,
                        "magic": config.MAGIC_NUMBER,
                    }
                    if mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(
                            f"[Trailing Stop] SL actualizado a {new_sl:.2f} (Profit: +{profit_points:.2f} pts)"
                        )

    elif position.type == mt5.ORDER_TYPE_SELL:
        profit_points = position.price_open - tick.ask
        if profit_points >= config.TS_ACTIVATION_POINTS:
            new_sl = tick.ask + config.TS_DISTANCE_POINTS
            if position.sl == 0.0 or new_sl < position.sl:
                symbol_info = mt5.symbol_info(config.SYMBOL)
                if new_sl > tick.ask + (
                    symbol_info.trade_stops_level * symbol_info.point
                ):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": position.ticket,
                        "symbol": config.SYMBOL,
                        "sl": new_sl,
                        "tp": position.tp,
                        "magic": config.MAGIC_NUMBER,
                    }
                    if mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(
                            f"[Trailing Stop] SL actualizado a {new_sl:.2f} (Profit: +{profit_points:.2f} pts)"
                        )


def main():
    if not init_mt5():
        return

    ny_tz = pytz.timezone("America/New_York")
    logging.info("Bot ORB Definitivo iniciado. Esperando la apertura de NY...")

    trade_taken_today = False
    current_date = None
    buy_ticket, sell_ticket, active_position_ticket = None, None, None

    while True:
        try:
            now_ny = datetime.now(ny_tz)

            # Reset diario
            if current_date != now_ny.date():
                current_date, trade_taken_today = now_ny.date(), False
                buy_ticket, sell_ticket, active_position_ticket = None, None, None
                logging.info(f"Nuevo día de trading: {current_date}")

            # FASE 1: Disparo de Órdenes a las 09:45 NY
            if (
                not trade_taken_today
                and now_ny.hour == config.NY_OPEN_HOUR
                and now_ny.minute == (config.NY_OPEN_MINUTE + config.ORB_MINUTES)
            ):
                logging.info(
                    "Hora alcanzada. Esperando 2 segundos para consolidación de la vela M1..."
                )
                time.sleep(2)

                high_box, low_box = get_orb_box()
                if high_box and low_box:
                    box_percent = ((high_box - low_box) / low_box) * 100
                    logging.info(
                        f"Caja ORB: High={high_box}, Low={low_box} (Tamaño: {high_box-low_box:.2f} pts, {box_percent:.2f}%)"
                    )

                    if box_percent > config.MAX_BOX_SIZE_PERCENT:
                        logging.info(f"Día ignorado (Volatilidad Extrema).")
                        trade_taken_today = True
                        continue

                    buy_price = high_box + config.BUFFER_POINTS
                    sell_price = low_box - config.BUFFER_POINTS

                    # Cálculo Dinámico de Lotes ($100 USD de Riesgo)
                    risk_buy = buy_price - low_box
                    lot_buy = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE / (risk_buy * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )

                    risk_sell = high_box - sell_price
                    lot_sell = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE
                                / (risk_sell * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )

                    buy_ticket = place_stop_order(
                        mt5.ORDER_TYPE_BUY_STOP, buy_price, low_box, lot_buy
                    )
                    sell_ticket = place_stop_order(
                        mt5.ORDER_TYPE_SELL_STOP, sell_price, high_box, lot_sell
                    )
                    trade_taken_today = True

            # FASE 2: OCO (One Cancels Other)
            if trade_taken_today and active_position_ticket is None:
                positions = mt5.positions_get(
                    symbol=config.SYMBOL, magic=config.MAGIC_NUMBER
                )
                if positions:
                    active_position_ticket = positions[0].ticket
                    logging.info(
                        f"¡Posición activada! Tipo: {'BUY' if positions[0].type == mt5.ORDER_TYPE_BUY else 'SELL'}"
                    )

                    orders = mt5.orders_get(
                        symbol=config.SYMBOL, magic=config.MAGIC_NUMBER
                    )
                    if orders:
                        for order in orders:
                            if order.ticket in (buy_ticket, sell_ticket):
                                cancel_order(order.ticket)

            # FASE 3: Trailing Stop y Cierre EOD
            if active_position_ticket is not None:
                positions = mt5.positions_get(ticket=active_position_ticket)
                if not positions:
                    logging.info("Posición cerrada (SL/TS tocado). Fin del trade.")
                    active_position_ticket = None
                else:
                    if now_ny.hour == 15 and now_ny.minute >= 55:
                        logging.warning(
                            "¡Alerta! 15:55 NY. Forzando cierre para evitar Rollover/Swaps..."
                        )
                        if close_position(positions[0]):
                            active_position_ticket = None
                    else:
                        manage_trailing_stop(positions[0])

            time.sleep(0.5)

        except Exception as e:
            logging.error(f"Error en el ciclo principal: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
