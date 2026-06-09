import MetaTrader5 as mt5
import pandas as pd
import logging
import json
import os
from datetime import datetime
import config_orb as config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


def init_mt5():
    if not mt5.initialize():
        logging.error("Fallo al inicializar MT5")
        mt5.shutdown()
        return False

    if not mt5.symbol_select(config.SYMBOL, True):
        logging.error(
            f"Símbolo {config.SYMBOL} no encontrado en Market Watch. Verifica tu config_orb.py"
        )
        return False

    return True


def run_backtest():
    if not init_mt5():
        return

    logging.info(
        f"Descargando el máximo historial posible en M1 para {config.SYMBOL}..."
    )

    rates_df_list = []
    pos = 0
    chunk_size = 10000

    while True:
        rates = mt5.copy_rates_from_pos(
            config.SYMBOL, mt5.TIMEFRAME_M1, pos, chunk_size
        )

        if rates is None or len(rates) == 0:
            if chunk_size > 1000:
                chunk_size = int(chunk_size / 2)
                continue
            else:
                break

        df_chunk = pd.DataFrame(rates)
        rates_df_list.append(df_chunk)

        if len(rates) < chunk_size:
            break

        pos += len(rates)

    if len(rates_df_list) == 0:
        error = mt5.last_error()
        logging.error(f"No se pudieron descargar los datos. Error MT5: {error}")
        return

    df = pd.concat(rates_df_list, ignore_index=True)
    df.drop_duplicates(subset=["time"], inplace=True)
    df.sort_values(by="time", ascending=True, inplace=True)

    logging.info(f"¡Descarga exitosa! Se obtuvieron {len(df)} velas históricas.")
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour
    df["minute"] = df["time"].dt.minute

    broker_hour = config.NY_OPEN_HOUR + config.BROKER_NY_OFFSET_HOURS
    broker_minute = config.NY_OPEN_MINUTE

    logging.info(
        f"Buscando la apertura a las {broker_hour:02d}:{broker_minute:02d} (Hora Broker)"
    )

    trades = []
    total_pnl_usd = 0.0

    grouped = df.groupby("date")

    for date, df_day in grouped:
        box = df_day[
            (df_day["hour"] == broker_hour)
            & (df_day["minute"] >= broker_minute)
            & (df_day["minute"] < broker_minute + config.ORB_MINUTES)
        ]

        if len(box) < config.ORB_MINUTES:
            continue

        high_box = box["high"].max()
        low_box = box["low"].min()

        box_size = high_box - low_box
        box_percent = (box_size / low_box) * 100

        if box_percent > config.MAX_BOX_SIZE_PERCENT:
            logging.info(f"Día ignorado ({date}): Caja muy grande ({box_percent:.2f}%)")
            continue

        buy_price = high_box + config.BUFFER_POINTS
        sell_price = low_box - config.BUFFER_POINTS

        after_box = df_day[
            (
                (df_day["hour"] == broker_hour)
                & (df_day["minute"] >= broker_minute + config.ORB_MINUTES)
            )
            | (df_day["hour"] > broker_hour)
        ]

        active_pos = None
        entry_price = 0.0
        sl = 0.0
        initial_sl = 0.0
        entry_time = None
        exit_time = None
        exit_price = 0.0
        lot_size = 0.0
        pnl_usd = 0.0
        exit_reason = ""

        for _, row in after_box.iterrows():
            if not active_pos:
                if row["high"] >= buy_price and row["low"] <= sell_price:
                    break
                elif row["high"] >= buy_price:
                    active_pos = "BUY"
                    entry_price = buy_price
                    sl = low_box
                    initial_sl = low_box
                    entry_time = row["time"]
                    # Cálculo de lotaje (Riesgo Fijo $100)
                    risk_pts = entry_price - initial_sl
                    lot_size = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE / (risk_pts * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )

                elif row["low"] <= sell_price:
                    active_pos = "SELL"
                    entry_price = sell_price
                    sl = high_box
                    initial_sl = high_box
                    entry_time = row["time"]
                    # Cálculo de lotaje (Riesgo Fijo $100)
                    risk_pts = initial_sl - entry_price
                    lot_size = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE / (risk_pts * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )

            if active_pos:
                if active_pos == "BUY":
                    if sl > 0 and row["low"] <= sl:
                        exit_price = sl
                        exit_time = row["time"]
                        pnl_usd = (
                            (exit_price - entry_price) * lot_size * config.POINT_VALUE
                        )
                        exit_reason = "SL" if sl == initial_sl else "TS"
                        break

                    profit_points = row["high"] - entry_price
                    if profit_points >= config.TS_ACTIVATION_POINTS:
                        new_sl = row["high"] - config.TS_DISTANCE_POINTS
                        if sl == 0 or new_sl > sl:
                            sl = new_sl

                elif active_pos == "SELL":
                    if sl > 0 and row["high"] >= sl:
                        exit_price = sl
                        exit_time = row["time"]
                        pnl_usd = (
                            (entry_price - exit_price) * lot_size * config.POINT_VALUE
                        )
                        exit_reason = "SL" if sl == initial_sl else "TS"
                        break

                    profit_points = entry_price - row["low"]
                    if profit_points >= config.TS_ACTIVATION_POINTS:
                        new_sl = row["low"] + config.TS_DISTANCE_POINTS
                        if sl == 0 or new_sl < sl:
                            sl = new_sl

        if active_pos and exit_time is None:
            last_price = after_box.iloc[-1]["close"]
            exit_price = last_price
            exit_time = after_box.iloc[-1]["time"]
            if active_pos == "BUY":
                pnl_usd = (exit_price - entry_price) * lot_size * config.POINT_VALUE
            else:
                pnl_usd = (entry_price - exit_price) * lot_size * config.POINT_VALUE
            exit_reason = "EOD"

        if active_pos:
            trades.append(
                {
                    "entry_time": entry_time,
                    "type": active_pos,
                    "box_pts": box_size,
                    "lotes": lot_size,
                    "entry_price": entry_price,
                    "exit_time": exit_time,
                    "exit_price": exit_price,
                    "pnl_usd": pnl_usd,
                    "reason": exit_reason,
                }
            )
            total_pnl_usd += pnl_usd

    # Estadísticas
    if len(trades) > 0:
        win_trades = [t["pnl_usd"] for t in trades if t["pnl_usd"] > 0]
        loss_trades = [t["pnl_usd"] for t in trades if t["pnl_usd"] <= 0]
        win_rate = len(win_trades) / len(trades) * 100

        gross_profit = sum(win_trades)
        gross_loss = abs(sum(loss_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        logging.info(
            "=========================================================================================="
        )
        logging.info("AUDITORÍA DE TRADES (V1 Definitiva - Gestión Riesgo $100)")
        logging.info(
            "=========================================================================================="
        )
        logging.info(
            "FECHA ENTRADA    | TIPO | CAJA PTS | LOTES | PRECIO EN. | PRECIO SAL. | MOTIVO | PNL ($)  "
        )
        logging.info("-" * 90)
        for t in trades:
            logging.info(
                f"{t['entry_time'].strftime('%Y-%m-%d %H:%M')} | {t['type']:<4} | {t['box_pts']:>8.2f} | {t['lotes']:>5.2f} | {t['entry_price']:>10.2f} | {t['exit_price']:>11.2f} | {t['reason']:<6} | {t['pnl_usd']:>8.2f}"
            )

        logging.info(
            "=========================================================================================="
        )
        logging.info("RESULTADOS GLOBALES DEL BACKTEST (V1 DEFINITIVA)")
        logging.info(
            "=========================================================================================="
        )
        logging.info(f"Total Trades: {len(trades)}")
        logging.info(f"Win Rate: {win_rate:.2f}%")
        logging.info(f"PnL Neto Total ($): {total_pnl_usd:.2f} USD")
        logging.info(f"Profit Factor: {profit_factor:.2f}")
        logging.info(
            f"Promedio Ganancia ($): {sum(win_trades)/len(win_trades) if win_trades else 0:.2f} USD"
        )
        logging.info(
            f"Promedio Pérdida ($): {sum(loss_trades)/len(loss_trades) if loss_trades else 0:.2f} USD"
        )
        logging.info(
            "=========================================================================================="
        )
        
        # --- EXPORTAR AL DASHBOARD ---
        dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard", "data")
        os.makedirs(dashboard_dir, exist_ok=True)
        export_path = os.path.join(dashboard_dir, "orb_backtest.json")
        
        export_data = {
            "summary": {
                "total_trades": len(trades),
                "win_rate": round(win_rate, 2),
                "total_pnl": round(total_pnl_usd, 2),
                "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
                "avg_win": round(sum(win_trades)/len(win_trades), 2) if win_trades else 0,
                "avg_loss": round(sum(loss_trades)/len(loss_trades), 2) if loss_trades else 0,
            },
            "trades": [
                {
                    "entry_time": t["entry_time"].strftime('%Y-%m-%d %H:%M'),
                    "type": t["type"],
                    "box_pts": round(t["box_pts"], 2),
                    "lotes": t["lotes"],
                    "entry_price": round(t["entry_price"], 2),
                    "exit_price": round(t["exit_price"], 2),
                    "pnl_usd": round(t["pnl_usd"], 2),
                    "reason": t["reason"]
                }
                for t in trades
            ]
        }
        
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=4)
            logging.info(f"Datos exportados al dashboard en: {export_path}")
        except Exception as e:
            logging.error(f"Error al exportar datos al dashboard: {e}")

    else:
        logging.info("No se encontraron operaciones.")


if __name__ == "__main__":
    run_backtest()
