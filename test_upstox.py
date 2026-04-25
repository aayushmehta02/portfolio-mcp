import asyncio
import sys
from portfolio_mcp.brokers.upstox import UpstoxAdapter

async def main():
    adapter = UpstoxAdapter()
    try:
        print("Fetching holdings from Upstox...")
        portfolio = await adapter.get_holdings()
        print("Portfolio fetched successfully!")
        print(f"Total Invested: {portfolio.total_invested}")
        print(f"Total Current Value: {portfolio.total_current_value}")
        print(f"Total PNL: {portfolio.total_pnl_absolute} ({portfolio.total_pnl_percent}%)")
        print("-" * 40)
        for h in portfolio.holdings:
            print(f"{h.ticker} ({h.exchange.value}): {h.quantity} shares @ {h.avg_cost}")
    except Exception as e:
        print(f"Error fetching portfolio: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
