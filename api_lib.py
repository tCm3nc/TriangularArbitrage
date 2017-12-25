import requests
import pandas as pd
import os


stella_api_key = os.environ.get('STELLA_API_KEY')
stella_secret_key = os.environ.get('STELLA_SECRET_KEY')

_base_endpoint = 'https://api.binance.com'

# GENERAL ENDPOINTS ################################


def get_general(request_type='ping'):
    # TODO: split this into a different function for each endpoint
    endpoint_dict = {
                     # return empty json for testing connectivity
                     'ping': '/api/v1/ping',
                     # return server timestamp
                     'time': '/api/v1/time', # return server timestamp
                     # Exchange information - Current exchange trading rules and symbol information
                     'exchangeInfo': '/api/v1/exchangeInfo',
                     }
    response = requests.get(_base_endpoint + endpoint_dict[request_type])
    return response

# MARKET DATA ENDPOINTS ################################


def get_depth(symbol, limit=100):
    # Order book
    # Weight: 1 if limit in [5, 10, 20, 50, 100]
    # Weight: 25 if limit=500
    # Weight: 50 if limit=1000
    ep = '/api/v1/depth'
    parameters = {'symbol': symbol,
                  # Valid limits:[5, 10, 20, 50, 100, 500, 1000]
                  'limit': limit}
    headers = {'X-MBX-APIKEY': stella_api_key}
    response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_trades(symbol, limit=500):
    # Get list of recent trades (up to last 500)
    # Weight: 1
    ep = '/api/v1/trades'
    parameters = {'symbol': symbol,
                  # limit: max 500
                  'limit': limit}
    headers = {'X-MBX-APIKEY': stella_api_key}
    response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_historical_trades(symbol, limit=500):
    # Old trade lookup (MARKET_DATA)
    # Weight: 100
    # TODO: implement optional parameter "fromID"
    ep = '/api/v1/historicalTrades'
    parameters = {'symbol': symbol,
                  # limit: max 500
                  'limit': limit}
    headers = {'X-MBX-APIKEY': stella_api_key}
    response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_aggregate_trades(symbol, limit=500):
    # Get compressed, aggregate trades. Trades that fill at the time, from the same order,
    # with the same price will have the quantity aggregated.
    # Weight: 1
    # TODO: implement optional parameters "fromID", "startTime", "endTime"
    ep = '/api/v1/aggTrades'
    parameters = {'symbol': symbol,
                  # limit: max 500
                  'limit': limit}
    headers = {'X-MBX-APIKEY': stella_api_key}
    response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_klines(symbol, interval, limit=500):
    # Kline/candlestick bars for a symbol. Klines are uniquely identified by their open time.
    # Weight: 1
    # TODO: implement optional parameters "startTime", "endTime"
    ep = '/api/v1/klines'
    parameters = {'symbol': symbol, 'interval': interval, 'limit': limit}
    headers = {'X-MBX-APIKEY': stella_api_key}
    response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_24hr_ticker(symbol='BTCUSDT'):
    # 24 hour ticker price change statistics. Careful when accessing this with no symbol.
    # If the symbol is not sent, tickers for all symbols will be returned in an array
    # Weight: 1 for each symbol
    ep = '/api/v1/ticker/24hr'
    parameters = {'symbol': symbol}
    headers = {'X-MBX-APIKEY': stella_api_key}
    if symbol in ['all', '']:
        response = requests.get(_base_endpoint + ep, headers=headers)
    else:
        response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_price_ticker(symbol='BTCUSDT'):
    # Latest price for a symbol
    # If the symbol is not sent, tickers for all symbols will be returned in an array
    # Weight: 1
    ep = '/api/v3/ticker/price'
    parameters = {'symbol': symbol}
    headers = {'X-MBX-APIKEY': stella_api_key}
    if symbol in ['all', '']:
        response = requests.get(_base_endpoint + ep, headers=headers)
    else:
        response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response


def get_book_ticker(symbol='BTCUSDT'):
    # Best price/qty on the order book for a symbols.
    # If the symbol is not sent, tickers for all symbols will be returned in an array
    ep = '/api/v3/ticker/bookTicker'
    parameters = {'symbol': symbol}
    headers = {'X-MBX-APIKEY': stella_api_key}
    if symbol in ['all', '']:
        response = requests.get(_base_endpoint + ep, headers=headers)
    else:
        response = requests.get(_base_endpoint + ep, params=parameters, headers=headers)
    return response

def post_test_order():
    ep = 'POST /api/v3/order/test'