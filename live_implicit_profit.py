from TriangularArbitrageModel import *

# model = TriangularArbitrageModel('USDT', 'BTC', 'ETH')
model = TriangularArbitrageModel('USDT', 'ETH', 'BTC')

print(model.pair_a_valid_name)
print(model.pair_b_valid_name)
print(model.pair_c_valid_name)

# initialize the time series
live_implicit_profit = []

trade_amount = 50.00
window = 60

# while True:
#     model.update_order_books()
#     print(str(model.get_implicit_profit(trade_amount)))
#     if len(live_implicit_profit) >= window:
#         live_implicit_profit.pop(0)
#     live_implicit_profit.append(model.implicit_profit)

# fees = (1.0005 ** 3)
profit_threshold = 0.04

model.print_account_info()
while True:
    model.async_update(total_base_asset=trade_amount, profit_conditional=(trade_amount + profit_threshold))

# TODO: actually get responses from the trade requests so we can confirm our fill amounts
