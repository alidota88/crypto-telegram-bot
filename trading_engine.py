from dataclasses import dataclass
from typing import Dict, List

from macd_rsi_strategy import MACDRSIStrategy
from market_service import fetch_15m_klines

TOTAL_CAPITAL = 10_000.0          # 总资金（展示用）
PER_TRADE_NOTIONAL = 2_000.0      # 每个品种固定 2000 USDT
TRADE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


@dataclass
class Position:
    symbol: str
    side: str           # "long" or "short"
    entry_price: float
    qty: float
    notional: float
    realized_pnl: float = 0.0


# 当前持仓 & 累计盈亏（简单内存版）
POSITIONS: Dict[str, Position | None] = {}
TOTAL_REALIZED_PNL: float = 0.0

strategy = MACDRSIStrategy()


def run_strategy_and_update_positions() -> str:
    """
    对 TRADE_SYMBOLS 跑一轮策略，更新模拟持仓 & 计算盈亏，
    返回一段适合发到 Telegram 的文本。
    """
    global TOTAL_REALIZED_PNL

    lines: List[str] = []
    lines.append("[策略信号 + 仓位模拟（每小时）]")
    lines.append(f"总资金假设: {TOTAL_CAPITAL:.2f} USDT, 每个品种开仓: {PER_TRADE_NOTIONAL:.2f} USDT\n")

    for symbol in TRADE_SYMBOLS:
        try:
            df_15m = fetch_15m_klines(symbol, limit=300)
            df_sig = strategy.generate_signals(df_15m)
            last = df_sig.iloc[-1]
            last_price = float(last["close"])
            signal = int(last["signal"])  # 1=多, -1=空, 0=无操作

            pos = POSITIONS.get(symbol)
            symbol_lines: List[str] = [f"{symbol} 当前价: {last_price:.4f}"]

            # 1) 已有持仓，先算浮盈亏
            unreal_pnl = 0.0
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

            # 2) 平仓逻辑：已有仓位 & 信号反向 或 signal == 0
            if pos is not None and (signal == 0 or (signal == 1 and pos.side == "short") or (signal == -1 and pos.side == "long")):
                if pos.side == "long":
                    realized = (last_price - pos.entry_price) * pos.qty
                else:
                    realized = (pos.entry_price - last_price) * pos.qty

                pos.realized_pnl += realized
                TOTAL_REALIZED_PNL += realized

                symbol_lines.append(
                    f"平仓: {pos.side.upper()} @ {last_price:.4f}, "
                    f"本次盈亏: {realized:.2f} USDT, 累计: {pos.realized_pnl:.2f} USDT"
                )

                POSITIONS[symbol] = None
                pos = None
                unreal_pnl = 0.0

            # 3) 开仓逻辑：当前无仓 & 有新信号
            if pos is None and signal != 0:
                side = "long" if signal == 1 else "short"
                notional = PER_TRADE_NOTIONAL
                qty = notional / last_price

                pos = Position(
                    symbol=symbol,
                    side=side,
                    entry_price=last_price,
                    qty=qty,
                    notional=notional,
                )
                POSITIONS[symbol] = pos

                symbol_lines.append(
                    f"开仓: {side.upper()} @ {last_price:.4f}, "
                    f"名义资金: {notional:.2f} USDT, 数量: {qty:.6f}"
                )

            # 4) 持仓状态展示
            pos = POSITIONS.get(symbol)
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

                symbol_lines.append(
                    f"持仓: {pos.side.upper()} @ {pos.entry_price:.4f}, "
                    f"浮动盈亏: {unreal_pnl:.2f} USDT, 累计已实现: {pos.realized_pnl:.2f} USDT"
                )
            else:
                symbol_lines.append("当前无持仓")

            lines.append("\n".join(symbol_lines))
            lines.append("")  # 空行分隔
        except Exception as e:
            lines.append(f"{symbol}: 运行策略失败：{e}")

    lines.append(f"\n组合累计已实现盈亏: {TOTAL_REALIZED_PNL:.2f} USDT")
    return "\n".join(lines)
