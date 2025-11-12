# === imports (放在文件最开头) ===
import os, sys
from dataclasses import dataclass
from typing import Dict, List

# 允许同目录模块被 import（容器/某些运行环境下很有用）
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 主策略优先使用新的四周期中线策略；若文件未就位，则回退到旧策略以不中断运行
try:
    from multi_tf_midterm_strategy import MultiTFMidtermStrategy
except ModuleNotFoundError:
    from macd_rsi_strategy import MACDRSIStrategy as MultiTFMidtermStrategy

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
main_strategy = MultiTFMidtermStrategy()  # 新四周期中线策略
simple_strategy = SimpleMACDStrategy()  # 新简单 MACD 策略

# 当前持仓 & 累计盈亏（简单内存版）
POSITIONS: Dict[str, Position | None] = {}
TOTAL_REALIZED_PNL: float = 0.0

# 策略实例：主策略(四周期中线) + 简单策略(执行层)
main_strategy = MultiTFMidtermStrategy()
simple_strategy = SimpleMACDStrategy()


def run_strategy_and_update_positions() -> tuple[str, List[str]]:
    """
    对 TRADE_SYMBOLS 跑一轮：
      - 用 MACDRSIStrategy 计算主策略信号（只展示，不控制开平）
      - 用 SimpleMACDStrategy 计算简单策略信号（用来模拟开平仓）
    返回:
      summary_text: 本次完整的多策略 + 仓位总结（可选是否推送）
      trade_events: 本次新发生的开仓/平仓事件列表（每条是一段文字）
    """
    global TOTAL_REALIZED_PNL

    lines: List[str] = []
    trade_events: List[str] = []

    lines.append("[多策略信号 + 仓位模拟]")
    lines.append(f"总资金假设: {TOTAL_CAPITAL:.2f} USDT, 每个品种开仓: {PER_TRADE_NOTIONAL:.2f} USDT\n")

    for symbol in TRADE_SYMBOLS:
        try:
            df_15m = fetch_15m_klines(symbol, limit=300)

            # 1) 主策略（不参与交易，只做观察）
            df_main = main_strategy.generate_signals(df_15m)
            main_last_signal = int(df_main["signal"].iloc[-1])
            main_total_signals = int((df_main["signal"] != 0).sum())

            # 2) 简单策略（控制开平仓）
            df_simple = simple_strategy.generate_signals(df_15m)
            simple_last_signal = int(df_simple["simple_signal"].iloc[-1])
            simple_total_signals = int((df_simple["simple_signal"] != 0).sum())

            last_price = float(df_simple["close"].iloc[-1])

            symbol_lines: List[str] = []
            symbol_lines.append(f"{symbol} 当前价: {last_price:.4f}")
            symbol_lines.append(
                f"主策略: 当前 signal={main_last_signal}, 历史触发次数={main_total_signals}"
            )
            symbol_lines.append(
                f"简单策略: 当前 signal={simple_last_signal}, 历史触发次数={simple_total_signals}"
            )

            # 3) 用简单策略信号做交易
            # 与主趋势同向才交易：若 simple 与 main 不一致，或 simple 为 0，则不开仓
            trade_signal = (
                simple_last_signal
                if (simple_last_signal != 0 and simple_last_signal == main_last_signal)
                else 0
            )

                if (simple_last_signal != 0 and simple_last_signal == main_last_signal) 
                else 0
            )

            pos = POSITIONS.get(symbol)

            # 先算已有持仓的浮盈亏
            unreal_pnl = 0.0
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

            # ---- 平仓逻辑：已有仓位 & 出现反向信号 或 0 ----
            if pos is not None and (
                trade_signal == 0
                or (trade_signal == 1 and pos.side == "short")
                or (trade_signal == -1 and pos.side == "long")
            ):
                if pos.side == "long":
                    realized = (last_price - pos.entry_price) * pos.qty
                else:
                    realized = (pos.entry_price - last_price) * pos.qty

                pos.realized_pnl += realized
                TOTAL_REALIZED_PNL += realized

                msg = (
                    f"【平仓】{symbol} {pos.side.upper()} @ {last_price:.4f}，"
                    f"本次盈亏: {realized:.2f} USDT，"
                    f"该仓累计: {pos.realized_pnl:.2f} USDT，"
                    f"组合累计已实现: {TOTAL_REALIZED_PNL:.2f} USDT"
                )
                symbol_lines.append(msg)
                trade_events.append(msg)

                POSITIONS[symbol] = None
                pos = None
                unreal_pnl = 0.0

            # ---- 开仓逻辑：当前无仓 & 有信号 ----
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

                msg = (
                    f"【开仓】{symbol} {side.upper()} @ {last_price:.4f}，"
                    f"名义资金: {notional:.2f} USDT，数量: {qty:.6f}"
                )
                symbol_lines.append(msg)
                trade_events.append(msg)

            # ---- 展示当前持仓状态 ----
            pos = POSITIONS.get(symbol)
            if pos is not None:
                if pos.side == "long":
                    unreal_pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    unreal_pnl = (pos.entry_price - last_price) * pos.qty

                symbol_lines.append(
                    f"持仓: {pos.side.upper()} @ {pos.entry_price:.4f}，"
                    f"浮动盈亏: {unreal_pnl:.2f} USDT，"
                    f"该仓累计已实现: {pos.realized_pnl:.2f} USDT"
                )
            else:
                symbol_lines.append("当前无持仓")

            lines.append("\n".join(symbol_lines))
            lines.append("")  # 空行分隔
        except Exception as e:
            lines.append(f"{symbol}: 运行多策略失败：{e}")

    lines.append(f"\n简单策略组合累计已实现盈亏: {TOTAL_REALIZED_PNL:.2f} USDT")
    summary_text = "\n".join(lines)
    return summary_text, trade_events

