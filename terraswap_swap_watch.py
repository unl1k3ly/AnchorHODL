import requests
import urllib
import json

terra_swap_endpoint = 'https://fcd.terra.dev'


# Check % diff of luna to blunas
def run_terra_swap_price_watcher():
    lazy_render_list = []
    prices_list = []

    # Luna to Bluna
    contract_address = 'terra1jxazgm67et0ce260kvrpfv50acuushpjsz2y0p'
    query_msg = '{"simulation":{"offer_asset":{"amount":"1000000","info":{"native_token":{"denom":"uluna"}}}}}'
    response = requests.get(terra_swap_endpoint + '/wasm/contracts/' + contract_address + '/store', params={'query_msg': query_msg})

    if response.status_code == 200:
        return_amount = int(response.json().get('result').get('return_amount'))
        commission_amount = int(response.json().get('result').get('commission_amount'))
        spread_amount = int(response.json().get('result').get('spread_amount'))
        prices_list.append({'return_amount':return_amount, 'commission_amount':commission_amount, 'price_for': 'Luna to Bluna', 'spread_amount': spread_amount})

    # Bluna to Luna
    query_msg = '{"simulation":{"offer_asset":{"amount":"1000000","info":{"token":{"contract_addr":"terra1kc87mu460fwkqte29rquh4hc20m54fxwtsx7gp"}}}}}'
    response = requests.get(terra_swap_endpoint + '/wasm/contracts/' + contract_address + '/store', params={'query_msg': query_msg})

    if response.status_code == 200:
        return_amount = int(response.json().get('result').get('return_amount'))
        commission_amount = int(response.json().get('result').get('commission_amount'))
        spread_amount = int(response.json().get('result').get('spread_amount'))
        prices_list.append({'return_amount':return_amount, 'commission_amount':commission_amount, 'price_for': 'Bluna to Luna', 'spread_amount': spread_amount})

    for item in prices_list:
        # Assuming luna:bluna are 1:1
        luna_amount = 1000000
        return_amount = item.get('return_amount')
        commission_amount = item.get('commission_amount')
        commission_amount = item.get('commission_amount')
        spread_amount = item.get('spread_amount')
        percent_diff = (return_amount - luna_amount) / luna_amount * 100
        lunas_to_blunas_diff = return_amount - luna_amount
        # TerraSwap fee
        percent_diff -= 0.3

        # Results
        price_diff = round(percent_diff, 4)
        price_ratio = (lunas_to_blunas_diff + luna_amount) / 1000000
        lazy_render = f"{item['price_for']} => Diff: {price_diff}%, Ratio (1-1): {price_ratio}, Spreed: {spread_amount}"

        lazy_render_list.append(lazy_render)

    luna_prices = get_luna_price_prices()
    lazy_render = f"SELL: ${luna_prices['sell']} (Luna to UST) - BUY: ${luna_prices['buy']} (UST to Luna)."
    lazy_render_list.append(lazy_render)

    return lazy_render_list


def get_luna_price_prices():
    luna_prices = {'sell': '', 'buy': ''}
    contract_address = 'terra1tndcaqxkpc5ce9qee5ggqf430mr2z3pefe5wj6'

    # Get the price for LUNA ---> UST (Sell)
    query_msg = '{"simulation":{"offer_asset":{"amount":"1000000","info":{"native_token":{"denom":"uluna"}}}}}'
    response = requests.get(terra_swap_endpoint + '/wasm/contracts/' + contract_address + '/store', params={'query_msg': query_msg})

    if response.status_code == 200:
        return_amount = int(response.json().get('result').get('return_amount'))
        sell_luna_price = round(1.000000 * (return_amount / 1000000), 4)
        luna_prices['sell'] = sell_luna_price

    # Get the price for UST ---> Luna (Buy)
    query_msg = '{"simulation":{"offer_asset":{"amount":"1000000","info":{"native_token":{"denom":"uusd"}}}}}'
    response = requests.get(terra_swap_endpoint + '/wasm/contracts/' + contract_address + '/store',
                            params={'query_msg': query_msg})

    if response.status_code == 200:
        return_amount = int(response.json().get('result').get('return_amount'))
        sell_luna_price = round(1.000000 / (return_amount / 1000000), 4)

        luna_prices['buy'] = sell_luna_price

    return luna_prices


if __name__ == "__main__":
    print(run_terra_swap_price_watcher())
    print(get_luna_price_prices())

