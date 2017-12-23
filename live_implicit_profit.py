from TriangularArbitrageModel import *

model = TriangularArbitrageModel('USDT', 'BTC', 'ETH')

print(model.pair_a_valid_name)
print(model.pair_b_valid_name)
print(model.pair_c_valid_name)

# initialize the time series
live_implicit_profit = []

trade_amount = 200.00
window = 60

while True:
    model.update_order_books()
    print(str(model.get_implicit_profit(trade_amount)))
    if len(live_implicit_profit) >= window:
        live_implicit_profit.pop(0)
    live_implicit_profit.append(model.implicit_profit)
