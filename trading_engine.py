from dataclasses import dataclass
from typing import Dict, List

from macd_rsi_strategy import MACDRSIStrategy
from simple_strategy import SimpleMACDStrategy
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

# 使用简单策略做模拟交易的持仓
POSITIONS: Dict[str, Position | None] = {}
TOTAL_REALIZED_PNL: float = 0.0

# 策略实例：保留你原来的 + 新增一个简单策略
main_strategy = MACDRSIStrategy()       # 原 MACD+RSI 多周期策略
simple_strategy = SimpleMACDStrategy()  # 新简单 MACD 策略

# 当前持仓 & 累计盈亏（简单内存版）
POSITIONS: Dict[str, Position | None] = {}
TOTAL_REALIZED_PNL: float = 0.0

strategy = MACDRSIStrategy()


def run_strategy_and_update_positions() -> str:
    """
    对 TRADE_SYMBOLS 跑一轮：
      - 用 MACDRSIStrategy 计算主策略信号（只展示，不开仓）
      - 用 SimpleMACDStrategy 计算简单策略信号（用来模拟开平仓）
    返回一段适合发到 Telegram 的文本。
    """
    global TOTAL_REALIZED_PNL

    lines: List[str] = []
    lines.append("[多策略信号 + 仓位模拟（每小时）]")
    lines.append(f"总资金假设: {TOTAL_CAPITAL:.2f} USDT, 每个品种开仓: {PER_TRADE_NOTIONAL:.2f} USDT\n")

    for symbol in TRADE_SYMBOLS:
        try:
            df_15m = fetch_15m_klines(symbol, limit=300)

            # 1️⃣ 主策略（你的 MACD+RSI 多周期策略）——只用来观察信号情况
            df_main = main_strategy.generate_signals(df_15m)
            main_last_signal = int(df_main["signal"].iloc[-1])
            main_total_signals = int((df_main["signal"] != 0).sum())

            # 2️⃣ 简单策略（15m MACD 金叉/死叉）——用来开仓/平仓
            df_simple = simple_strategy.generate_signals(df_15m)
            simple_last_signal = int(df_simple["simple_signal"].iloc[-1])
            simple_total_signals = int((df_simple["simple_signal"] != 0).sum())

            last_price = float(df_simple["close"].iloc[-1])

            symbol_lines: List[str] = []
            symbol_lines.append(f"{symbol} 当前价: {last_price:.4f}")

            # 展示两套策略的信号情况（方便你判断是不是策略太严）
            symbol_lines.append(
                f"主策略: 当前 signal={main_last_signal}, 历史触发次数={main_total_signals}"
            )
            symbol_lines.append(
                f"简单策略: 当前 signal={simple_last_signal}, 历史触发次数={simple_total_signals}"
            )

            # 3️⃣ 用简单策略的信号 simple_last_signal 来驱动模拟交易
            trade_signal = simple_last_signal  # 1=多, -1=空, 0=不动

            pos = POSITIONS.get(symbol)

            # 先算已有持仓的浮盈亏
            unreal_pnl = 0.0
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

            # 3.1 平仓逻辑：已有仓位 & 简单策略给出反向信号 或 0
            if pos is not None and (trade_signal == 0 or (trade_signal == 1 and pos.side == "short") or (trade_signal == -1 and pos.side == "long")):
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

            # 3.2 开仓逻辑：当前无仓 & 简单策略有新信号
            if pos is None and trade_signal != 0:
                side = "long" if trade_signal == 1 else "short"
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

            # 3.3 展示当前持仓状态
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
            lines.append(f"{symbol}: 运行多策略失败：{e}")

    lines.append(f"\n简单策略组合累计已实现盈亏: {TOTAL_REALIZED_PNL:.2f} USDT")
    return "\n".join(lines)

