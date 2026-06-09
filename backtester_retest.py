import MetaTrader5 as mt5
import pandas as pd
import logging
import config_orb as config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


def init_mt5():
    if not mt5.initialize():
        return False
    if not mt5.symbol_select(config.SYMBOL, True):
        return False
    return True


def get_historical_data():
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
        rates_df_list.append(pd.DataFrame(rates))
        if len(rates) < chunk_size:
            break
        pos += len(rates)

    if not rates_df_list:
        return None
    df = pd.concat(rates_df_list, ignore_index=True)
    df.drop_duplicates(subset=["time"], inplace=True)
    df.sort_values(by="time", ascending=True, inplace=True)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour
    df["minute"] = df["time"].dt.minute
    return df


def run_backtest():
    if not init_mt5():
        return
    logging.info(f"[RETEST] Descargando historial de {config.SYMBOL}...")
    df = get_historical_data()
    if df is None:
        logging.error("Fallo al descargar datos.")
        return

    broker_hour, broker_minute = (
        config.NY_OPEN_HOUR + config.BROKER_NY_OFFSET_HOURS,
        config.NY_OPEN_MINUTE,
    )
    trades = []

    for date, df_day in df.groupby("date"):
        box = df_day[
            (df_day["hour"] == broker_hour)
            & (df_day["minute"] >= broker_minute)
            & (df_day["minute"] < broker_minute + config.ORB_MINUTES)
        ]
        if len(box) < config.ORB_MINUTES:
            continue

        high_box, low_box = box["high"].max(), box["low"].min()
        if ((high_box - low_box) / low_box) * 100 > config.MAX_BOX_SIZE_PERCENT:
            continue

        after_box = df_day[
            (
                (df_day["hour"] == broker_hour)
                & (df_day["minute"] >= broker_minute + config.ORB_MINUTES)
            )
            | (df_day["hour"] > broker_hour)
        ]

        active_pos, state, sl, breakout_sl = None, "WAIT", 0.0, 0.0
        entry_price, lot_size, entry_time = 0.0, 0.0, None

        for _, row in after_box.iterrows():
            if not active_pos:
                if state == "WAIT":
                    if row["close"] > high_box + config.RETEST_BUFFER:
                        state, breakout_sl = (
                            "RETEST_BUY",
                            row["low"] - config.RETEST_SL_OFFSET,
                        )
                    elif row["close"] < low_box - config.RETEST_BUFFER:
                        state, breakout_sl = (
                            "RETEST_SELL",
                            row["high"] + config.RETEST_SL_OFFSET,
                        )
                elif state == "RETEST_BUY" and row["low"] <= high_box:
                    active_pos, entry_price, sl, entry_time = (
                        "BUY",
                        high_box,
                        breakout_sl,
                        row["time"],
                    )
                    risk = max(1.0, entry_price - sl)
                    lot_size = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE / (risk * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )
                elif state == "RETEST_SELL" and row["high"] >= low_box:
                    active_pos, entry_price, sl, entry_time = (
                        "SELL",
                        low_box,
                        breakout_sl,
                        row["time"],
                    )
                    risk = max(1.0, sl - entry_price)
                    lot_size = round(
                        max(
                            config.MIN_LOT,
                            min(
                                config.MAX_LOT,
                                config.RISK_PER_TRADE / (risk * config.POINT_VALUE),
                            ),
                        ),
                        2,
                    )
            else:
                if active_pos == "BUY":
                    if row["low"] <= sl:
                        trades.append(
                            {"pnl": (sl - entry_price) * lot_size * config.POINT_VALUE}
                        )
                        break
                    if row["high"] - entry_price >= config.TS_ACTIVATION_POINTS:
                        sl = max(sl, row["high"] - config.TS_DISTANCE_POINTS)
                else:
                    if row["high"] >= sl:
                        trades.append(
                            {"pnl": (entry_price - sl) * lot_size * config.POINT_VALUE}
                        )
                        break
                    if entry_price - row["low"] >= config.TS_ACTIVATION_POINTS:
                        sl = min(sl, row["low"] + config.TS_DISTANCE_POINTS)

    imprimir_estadisticas(trades, "ORB RETEST (Confirmación)")


def imprimir_estadisticas(trades, nombre):
    if not trades:
        return logging.info(f"Sin trades para {nombre}")
    win = [t["pnl"] for t in trades if t["pnl"] > 0]
    loss = [t["pnl"] for t in trades if t["pnl"] <= 0]
    logging.info(f"==== RESULTADOS {nombre} ====")
    logging.info(
        f"Total Trades: {len(trades)} | Win Rate: {(len(win)/len(trades))*100:.2f}%"
    )
    logging.info(f"PnL Neto Total: {sum(win)+sum(loss):.2f} USD")
    logging.info(
        f"Promedio Ganancia: {sum(win)/len(win) if win else 0:.2f} | Promedio Perdida: {sum(loss)/len(loss) if loss else 0:.2f}"
    )


if __name__ == "__main__":
    run_backtest()
