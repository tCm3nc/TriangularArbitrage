import api_lib
import grequests
import os

valid_pair_name = {
        # lookup dictionary to provide valid currency pairs on the Binance exchange
        ('BCC', 'ETH'): 'BCCETH',
        ('ETH', 'BCC'): 'BCCETH',

        ('IOTA', 'ETH'): 'IOTAETH',
        ('ETH', 'IOTA'): 'IOTAETH',

        ('USDT', 'ETH'): 'ETHUSDT',
        ('ETH', 'USDT'): 'ETHUSDT',

        ('BTC', 'ETH'): 'ETHBTC',
        ('ETH', 'BTC'): 'ETHBTC',

        ('IOTA', 'BTC'): 'IOTABTC',
        ('BTC', 'IOTA'): 'IOTABTC',

        ('USDT', 'BTC'): 'BTCUSDT',
        ('BTC', 'USDT'): 'BTCUSDT'
    }


class TriangularArbitrageModel:
    def __init__(self, base_asset, quote_asset, tertiary_asset):
        self.pair_a = (base_asset, quote_asset)
        self.pair_b = (quote_asset, tertiary_asset)
        self.pair_c = (tertiary_asset, base_asset)

        self.pair_a_valid_name = valid_pair_name[(base_asset, quote_asset)]
        self.pair_b_valid_name = valid_pair_name[(quote_asset, tertiary_asset)]
        self.pair_c_valid_name = valid_pair_name[(tertiary_asset, base_asset)]

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

        self.implicit_profit = 0

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
        # call this sparsely -- when arbitrage_profit is within a specified range
        ep = 'https://api.binance.com/api/v1/depth'
        symbols = [self.pair_a_valid_name, self.pair_b_valid_name, self.pair_c_valid_name]
        headers = {'X-MBX-APIKEY': os.environ.get('STELLA_API_KEY')}

        #  responses = grequests.map( grequests.get( , size=3 )
        get_request_list = []
        for symbol in symbols:
            get_request_list.append(grequests.get(ep,
                                                  params={'symbol': symbol, 'limit': self.order_book_limit},
                                                  headers=headers))

        responses = grequests.map(get_request_list, exception_handler=self._request_exception, size=3)

        pair_a_response = responses[0]
        pair_b_response = responses[1]
        pair_c_response = responses[2]

        # pair_a_response = api_lib.get_depth(self.pair_a_valid_name, limit=self.order_book_limit)
        # pair_b_response = api_lib.get_depth(self.pair_b_valid_name, limit=self.order_book_limit)
        # pair_c_response = api_lib.get_depth(self.pair_c_valid_name, limit=self.order_book_limit)

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
        if inversion:
            return self._get_base_amount_from_sell_quote(order_book, total_base_asset)
        return self._get_quote_amount_from_sell_base(order_book, total_base_asset)

    @staticmethod
    def _get_quote_amount_from_sell_base(order_book, total_base_asset):
        # amount = total_base / price

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
