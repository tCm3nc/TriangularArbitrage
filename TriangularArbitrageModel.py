import api_lib
import grequests
import os
from datetime import datetime, timedelta

from binance.client import Client
from binance.enums import *

valid_pair_name = {
        # lookup dictionary to provide valid currency pairs on the Binance exchange

        ('USDT', 'BTC'): 'BTCUSDT',
        ('BTC', 'USDT'): 'BTCUSDT',

        ('USDT', 'ETH'): 'ETHUSDT',
        ('ETH', 'USDT'): 'ETHUSDT',

        ('BTC', 'ETH'): 'ETHBTC',
        ('ETH', 'BTC'): 'ETHBTC',

        ('IOTA', 'ETH'): 'IOTAETH',
        ('ETH', 'IOTA'): 'IOTAETH',

        ('IOTA', 'BTC'): 'IOTABTC',
        ('BTC', 'IOTA'): 'IOTABTC',

        ('XMR', 'BTC'): 'XMRBTC',
        ('BTC', 'XMR'): 'XMRBTC',

        ('XMR', 'ETH'): 'XMRETH',
        ('ETH', 'XMR'): 'XMRETH',

        ('BCC', 'ETH'): 'BCCETH',
        ('ETH', 'BCC'): 'BCCETH',

        ('BCC', 'BTC'): 'BCCBTC',
        ('BTC', 'BCC'): 'BCCBTC',

        ('BCC', 'USDT'): 'BCCUSDT',
        ('USDT', 'BCC'): 'BCCUSDT',
    }


def truncate(f, n):
    '''Truncates/pads a float f to n decimal places without rounding'''
    s = '{}'.format(f)
    if 'e' in s or 'E' in s:
        return '{0:.{1}f}'.format(f, n)
    i, p, d = s.partition('.')
    return '.'.join([i, (d+'0'*n)[:n]])


class TriangularArbitrageModel:
    def __init__(self, base_asset, quote_asset, tertiary_asset):
        # Construct the Binance API client
        self.client = Client(os.environ.get('STELLA_API_KEY'), os.environ.get('STELLA_SECRET_KEY'))

        self.base_asset = base_asset
        self.quote_asset = quote_asset
        self.tertiary_asset = tertiary_asset

        self.pair_a = (base_asset, quote_asset)
        self.pair_b = (quote_asset, tertiary_asset)
        self.pair_c = (tertiary_asset, base_asset)

        # get the valid exchange names for each pair
        self.pair_a_valid_name = valid_pair_name[self.pair_a]
        self.pair_b_valid_name = valid_pair_name[self.pair_b]
        self.pair_c_valid_name = valid_pair_name[self.pair_c]

        # determine if the valid pair needs to be inverted for our model
        self.pair_a_inversion = self.pair_a_valid_name.startswith(quote_asset)
        self.pair_b_inversion = self.pair_b_valid_name.startswith(tertiary_asset)
        self.pair_c_inversion = self.pair_c_valid_name.startswith(base_asset)

        # call get_market_data to update the data
        self.market_data = {}

        # call get_order_books to update the data
        self.order_book_limit = 100
        self.pair_a_order_book = {}
        self.pair_b_order_book = {}
        self.pair_c_order_book = {}

        self.base_asset_amount = 0
        self.pair_a_quote_fill = 0
        self.pair_b_quote_fill = 0
        self.implicit_profit = 0

        self.debounce = timedelta(0, 10, 0)  # 10 seconds -- decrease this when we get more advanced
        # initialize last_trade_time so we can trade immediately
        self.last_trade_time = datetime.now() - self.debounce

        # holds the last n values for implicit profit

        self.live_pair_a_fill = []
        self.live_pair_b_fill = []
        self.live_implicit_profit = []
        self.live_implicit_profit_len = 0
        self.implicit_rolling_window = 10  # smaller window to calculate for trading strategy
        self.live_window = 60

        self.trade_fee = 0.0005

        self.base_asset_account = 0
        self.quote_asset_account = 0
        self.tertiary_asset_account = 0

        # TODO: add filters for min_notional

        self.pair_a_minQty = 0
        self.pair_a_maxQty = 0
        self.pair_a_stepSize = 0
        self.pair_b_minQty = 0
        self.pair_b_maxQty = 0
        self.pair_b_stepSize = 0
        self.pair_c_minQty = 0
        self.pair_c_maxQty = 0
        self.pair_c_stepSize = 0
        self.exchangeInfo = self.update_exchange_info()  # update filter information

    def async_update(self, total_base_asset, profit_conditional):
        # This method should be called periodically for executing live trading
        # TODO: get order book data from web socket streams instead of REST API
        self.update_order_books()
        self.base_asset_amount = total_base_asset
        self.pair_a_quote_fill = self._get_order_book_quote_value(self.pair_a_order_book,
                                                                  total_base_asset,
                                                                  self.pair_a_inversion)
        self.pair_b_quote_fill = self._get_order_book_quote_value(self.pair_b_order_book,
                                                                  self.pair_a_quote_fill,
                                                                  self.pair_b_inversion)
        self.implicit_profit = self._get_order_book_quote_value(self.pair_c_order_book,
                                                                self.pair_b_quote_fill,
                                                                self.pair_c_inversion)

        # update the time series for last n implicit profits
        self.live_implicit_profit_len = len(self.live_implicit_profit)

        if self.live_implicit_profit_len >= self.live_window:
            self.live_pair_a_fill.pop(0)
            self.live_pair_b_fill.pop(0)
            self.live_implicit_profit.pop(0)
        self.live_pair_a_fill.append(self.pair_a_quote_fill)
        self.live_pair_b_fill.append(self.pair_b_quote_fill)
        self.live_implicit_profit.append(self.implicit_profit)

        # CONDITIONAL FOR PLACING TRADES
        debounce_conditional = (datetime.now() - self.last_trade_time >= self.debounce)
        implicit_rolling_average = self.implicit_profit
        if self.live_implicit_profit_len > self.implicit_rolling_window:
            implicit_rolling_average = sum(self.live_implicit_profit[-self.implicit_rolling_window:]) / float(self.implicit_rolling_window)
        if debounce_conditional and (self.implicit_profit > implicit_rolling_average > profit_conditional):
            print()
            print('Implicit profit is: ', self.implicit_profit)
            print('implicit_rolling_average: ', implicit_rolling_average)
            pre_trade = datetime.now()
            print('Placing arbitrage trades', str(pre_trade))
            # self.place_arbitrage_trade(total_base_asset)
            # self.place_arbitrage_trade()
            post_trade = datetime.now()
            print('Arbitrage trades complete: ', str(post_trade))
            print('Time to complete trades: ', str(post_trade-pre_trade))
            print()
            self.last_trade_time = post_trade

        else:
            print('Trade conditional not met. Implicit profit: ', self.implicit_profit)

    def update_exchange_info(self):
        exchange_info = self.client.get_exchange_info()

        for symbol in exchange_info['symbols']:
            print(symbol['symbol'])
            print(symbol['filters'])
            if symbol['symbol'] == self.pair_a_valid_name:
                self.pair_a_minQty = symbol['filters'][1]['minQty']
                self.pair_a_maxQty = symbol['filters'][1]['maxQty']
                self.pair_a_stepSize = symbol['filters'][1]['stepSize']
                print(self.pair_a_minQty)
                print(self.pair_a_maxQty)
                print(self.pair_a_stepSize)

        for symbol in exchange_info['symbols']:
            print(symbol['filters'])
            if symbol['symbol'] == self.pair_b_valid_name:
                self.pair_b_minQty = symbol['filters'][1]['minQty']
                self.pair_b_maxQty = symbol['filters'][1]['maxQty']
                self.pair_b_stepSize = symbol['filters'][1]['stepSize']
                print(self.pair_b_minQty)
                print(self.pair_b_maxQty)
                print(self.pair_b_stepSize)

        for symbol in exchange_info['symbols']:
            print(symbol['filters'])
            if symbol['symbol'] == self.pair_c_valid_name:
                self.pair_c_minQty = symbol['filters'][1]['minQty']
                self.pair_c_maxQty = symbol['filters'][1]['maxQty']
                self.pair_c_stepSize = symbol['filters'][1]['stepSize']
                print(self.pair_c_minQty)
                print(self.pair_c_maxQty)
                print(self.pair_c_stepSize)

        return exchange_info

    def test_binance_client(self):
        depth = self.client.get_order_book(symbol='ETHBTC')
        print(depth)

    def place_arbitrage_trade(self):
        # place the arbitrage based on the model's most recent calculations
        # we save time by not updating the values

        # place trade a
        a_side = SIDE_BUY
        if self.pair_a_inversion:
            a_side = SIDE_SELL
        trade_qty = str(float(self.pair_a_quote_fill) - (float(self.pair_a_quote_fill) % float(self.pair_a_stepSize)))[:7]
        print('placing order for %s %s' % (trade_qty, self.pair_a_valid_name))
        order = self.client.create_order(
            symbol=self.pair_a_valid_name,
            side=a_side,
            type=ORDER_TYPE_MARKET,
            quantity=trade_qty,
            recvWindow=10000)
        print('ORDER: ', order)

        # TODO: receive trade a fill amount

        # place trade b
        b_side = SIDE_BUY
        if self.pair_b_inversion:
            b_side = SIDE_SELL
        trade_qty = str(float(self.pair_b_quote_fill) - (float(self.pair_b_quote_fill) % float(self.pair_b_stepSize)))[:7]
        print('placing order for %s %s' % (trade_qty, self.pair_b_valid_name))
        order = self.client.create_order(
            symbol=self.pair_b_valid_name,
            side=b_side,
            type=ORDER_TYPE_MARKET,
            quantity=trade_qty,
            recvWindow=10000)
        print('ORDER: ', order)

        # TODO: receive trade b fill amount

        # place trade c
        c_side = SIDE_BUY
        if self.pair_c_inversion:
            c_side = SIDE_SELL
        trade_qty = str(float(self.implicit_profit) - (float(self.implicit_profit) % float(self.pair_c_stepSize)))[:7]
        print('placing order for %s %s' % (trade_qty, self.pair_c_valid_name))
        order = self.client.create_order(
            symbol=self.pair_c_valid_name,
            side=c_side,
            type=ORDER_TYPE_MARKET,
            quantity=trade_qty,
            recvWindow=10000)
        print('ORDER: ', order)

        # TODO: calculate total trade profit from fill amount

        # print account info after trade
        self.print_account_info()
        return

    def print_account_info(self):
        self.pair_a_valid_name = valid_pair_name[self.pair_a]
        self.pair_b_valid_name = valid_pair_name[self.pair_b]
        self.pair_c_valid_name = valid_pair_name[self.pair_c]

        info = self.client.get_account(recvWindow=10000)
        for balance in info['balances']:
            if balance['asset'] == self.base_asset:
                print(balance['asset'], balance)
                print(balance['free'])
                print('Change %s: %s' % (balance['asset'], float(balance['free']) - float(self.base_asset_account)))
                self.base_asset_account = float(balance['free'])
            elif balance['asset'] == self.quote_asset:
                print(balance['asset'], balance)
                print(balance['free'])
                print('Change %s: %s' % (balance['asset'], float(balance['free']) - float(self.quote_asset_account)))
                self.quote_asset_account = float(balance['free'])
            elif balance['asset'] == self.tertiary_asset:
                print(balance['asset'], balance)
                print('Change %s: %s' % (balance['asset'], float(balance['free']) - float(self.tertiary_asset_account)))
                self.tertiary_asset_account = float(balance['free'])

    def testing_ping(self, total_base_asset):
        # place trades in parallel
        ep = 'https://api.binance.com/api/v1/ping'

        get_request_list = [grequests.get(ep)] * 3

        responses = grequests.map(get_request_list, exception_handler=self._request_exception, size=3)

        pair_a_response = responses[0]
        pair_b_response = responses[1]
        pair_c_response = responses[2]

        return

    def update_market_data(self):
        # call this once per second
        response_list = api_lib.get_book_ticker(symbol='all').json()

        # assign the prices to variables
        self.market_data['pair_a_ask'] = self._get_ask_from_json(response_list, self.pair_a_valid_name, self.pair_a_inversion)
        self.market_data['pair_b_ask'] = self._get_ask_from_json(response_list, self.pair_b_valid_name, self.pair_b_inversion)
        self.market_data['pair_c_ask'] = self._get_ask_from_json(response_list, self.pair_c_valid_name, self.pair_c_inversion)

        self.market_data['pair_a_bid'] = self._get_bid_from_json(response_list, self.pair_a_valid_name, self.pair_a_inversion)
        self.market_data['pair_b_bid'] = self._get_bid_from_json(response_list, self.pair_b_valid_name, self.pair_b_inversion)
        self.market_data['pair_c_bid'] = self._get_bid_from_json(response_list, self.pair_c_valid_name, self.pair_c_inversion)

        profit1 = float(self.market_data['pair_a_ask']) * float(self.market_data['pair_b_bid'])
        profit2 = float(self.market_data['pair_b_ask']) * float(self.market_data['pair_c_bid'])
        profit3 = float(self.market_data['pair_c_ask']) * float(self.market_data['pair_a_bid'])

        # arbitrage profit is total after making three trades
        self.market_data['market_arbitrage_profit'] = profit1 * profit2 * profit3

        return self.market_data

    def get_implicit_profit(self, total_base_asset):
        # get the implied profit from executing a triangular arbitrage trade with the specified base asset amount
        # this calculates trades against the most recent order book
        # TODO: implement implicit profit calculation for trading the other direction
        self.update_order_books()

        pair_a_quote_bought = self._get_order_book_quote_value(self.pair_a_order_book,
                                                               total_base_asset,
                                                               self.pair_a_inversion)
        pair_b_quote_bought = self._get_order_book_quote_value(self.pair_b_order_book,
                                                               pair_a_quote_bought,
                                                               self.pair_b_inversion)
        base_asset_bought = self._get_order_book_quote_value(self.pair_c_order_book,
                                                             pair_b_quote_bought,
                                                             self.pair_c_inversion)
        self.implicit_profit = base_asset_bought

        return self.implicit_profit

    def update_order_books(self):
        # update order books in parallel
        # call this sparsely -- when arbitrage_profit is within a specified range
        ep = 'https://api.binance.com/api/v1/depth'
        symbols = [self.pair_a_valid_name, self.pair_b_valid_name, self.pair_c_valid_name]
        headers = {'X-MBX-APIKEY': os.environ.get('STELLA_API_KEY')}

        get_request_list = []
        for symbol in symbols:
            get_request_list.append(grequests.get(ep,
                                                  params={'symbol': symbol, 'limit': self.order_book_limit},
                                                  headers=headers))

        responses = grequests.map(get_request_list, exception_handler=self._request_exception, size=3)

        pair_a_response = responses[0]
        pair_b_response = responses[1]
        pair_c_response = responses[2]

        if 429 in [pair_a_response.status_code, pair_b_response.status_code, pair_c_response.status_code]:
            print('Received a status code 429... exiting')
            exit(1)

        self.pair_a_order_book = pair_a_response.json()
        self.pair_b_order_book = pair_b_response.json()
        self.pair_c_order_book = pair_c_response.json()

        return [self.pair_a_order_book, self.pair_b_order_book, self.pair_c_order_book]

    @staticmethod
    def _request_exception(request, exception):
        print('Error executing HTTP GET request')
        print("Problem: {}: {}".format(request.url, exception))
        exit(1)

    def _get_order_book_quote_value(self, order_book, total_base_asset, inversion=False):
        # choose the trading direction dependent on inversion factor
        # fees are calculated here
        if inversion:
            profit = self._get_base_amount_from_sell_quote(order_book, total_base_asset)
            return profit * (1.0 - self.trade_fee)
        profit = self._get_quote_amount_from_sell_base(order_book, total_base_asset)
        return profit * (1.0-self.trade_fee)

    @staticmethod
    def _get_quote_amount_from_sell_base(order_book, total_base_asset):
        # amount = total_base * price

        base_to_sell = total_base_asset
        quote_bought = 0.0

        for ask in order_book['asks']:
            price = float(ask[0])
            qty = float(ask[1])
            ask_total = price * qty

            if ask_total >= base_to_sell:
                # we can buy all we need within this ask's total
                quote_bought += base_to_sell * price
                base_to_sell -= base_to_sell
                break
            elif base_to_sell > ask_total:
                # we are trying to buy more than this ask total, move on to next ask
                quote_bought += ask_total * price
                base_to_sell -= ask_total

        if base_to_sell > 0.0:
            print('Not enough order book info to calculate trade quantity. Consider increasing the limit parameter.')
        return quote_bought

    @staticmethod
    def _get_base_amount_from_sell_quote(order_book, total_quote_asset):
        # amount = total_base / price

        quote_to_sell = total_quote_asset
        base_bought = 0.0

        for bid in order_book['bids']:
            price = float(bid[0])
            qty = float(bid[1])
            bid_total = price * qty

            if bid_total >= quote_to_sell:
                # we can sell all we need within this bid's total
                base_bought += quote_to_sell * (1.0 / price)
                quote_to_sell -= quote_to_sell
                break
            elif quote_to_sell > bid_total:
                # we are trying to sell more than this bid total, move on to next bid
                base_bought += bid_total * (1.0 / price)
                quote_to_sell -= bid_total

        if quote_to_sell > 0.0:
            print('Not enough order book info to calculate trade quantity. Consider increasing the limit parameter.')
        return base_bought

    @staticmethod
    def _get_ask_from_json(response_list, pair_valid_name, inversion=False):
        for symbol_dict in response_list:
            if symbol_dict['symbol'] == pair_valid_name:
                if inversion:
                    return 1.0/float(symbol_dict['askPrice'])
                return symbol_dict['askPrice']

    @staticmethod
    def _get_bid_from_json(response_list, pair_valid_name, inversion=False):
        for symbol_dict in response_list:
            if symbol_dict['symbol'] == pair_valid_name:
                if inversion:
                    return 1.0/float(symbol_dict['bidPrice'])
                return symbol_dict['bidPrice']
