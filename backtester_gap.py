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
    logging.info(f"[GAP & GO] Descargando historial de {config.SYMBOL}...")
    df = get_historical_data()
    if df is None:
        return

    broker_hour, broker_minute = (
        config.NY_OPEN_HOUR + config.BROKER_NY_OFFSET_HOURS,
        config.NY_OPEN_MINUTE,
    )
    trades = []
    last_close = None

    for date, df_day in df.groupby("date"):
        if last_close is None:
            last_close = df_day.iloc[-1]["close"]
            continue

        open_candle = df_day[
            (df_day["hour"] == broker_hour) & (df_day["minute"] == broker_minute)
        ]
        if open_candle.empty:
            last_close = df_day.iloc[-1]["close"]
            continue

        today_open = open_candle.iloc[0]["open"]
        gap = today_open - last_close

        active_pos, entry_price, sl, tp = None, 0.0, 0.0, 0.0
        lot_size = round(
            max(
                config.MIN_LOT,
                min(
                    config.MAX_LOT,
                    config.RISK_PER_TRADE / (config.GAP_SL_PTS * config.POINT_VALUE),
                ),
            ),
            2,
        )

        if gap > config.MIN_GAP_PTS:
            active_pos, entry_price, sl, tp = (
                "SELL",
                today_open,
                today_open + config.GAP_SL_PTS,
                last_close,
            )
        elif gap < -config.MIN_GAP_PTS:
            active_pos, entry_price, sl, tp = (
                "BUY",
                today_open,
                today_open - config.GAP_SL_PTS,
                last_close,
            )

        if active_pos:
            session = df_day[
                ((df_day["hour"] == broker_hour) & (df_day["minute"] >= broker_minute))
                | (df_day["hour"] > broker_hour)
            ]
            for _, row in session.iterrows():
                if active_pos == "BUY":
                    if row["high"] >= tp:
                        trades.append(
                            {"pnl": (tp - entry_price) * lot_size * config.POINT_VALUE}
                        )
                        break
                    elif row["low"] <= sl:
                        trades.append(
                            {"pnl": (sl - entry_price) * lot_size * config.POINT_VALUE}
                        )
                        break
                else:
                    if row["low"] <= tp:
                        trades.append(
                            {"pnl": (entry_price - tp) * lot_size * config.POINT_VALUE}
                        )
                        break
                    elif row["high"] >= sl:
                        trades.append(
                            {"pnl": (entry_price - sl) * lot_size * config.POINT_VALUE}
                        )
                        break

        last_close = df_day.iloc[-1]["close"]

    imprimir_estadisticas(trades, "GAP & GO (Relleno)")


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
