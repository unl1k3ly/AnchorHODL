from terra_sdk.client.lcd import LCDClient
from terra_sdk.key.mnemonic import MnemonicKey
import requests
from time import sleep, time
from contact_addresses import contact_addresses
import config
import anchorprotocol
import logging_config
import logging.config

logging.config.dictConfig(logging_config.LOGGING)
logger = logging.getLogger(__name__)
logger_repay = logging.getLogger('repaying')


def get_terra_gas_prices():
    try:
        r = requests.get("https://fcd.terra.dev/v1/txs/gas_prices")
        r.raise_for_status()
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.HTTPError as err:
        print(f"Could not fetch get_terra_gas_prices from Terra's FCD. Error message: {err}")


class Terra:
    def __init__(self):
        if config.NETWORK == 'MAINNET':
            self.chain_id = 'columbus-5'
            self.public_node_url = 'https://lcd.terra.dev'
            # self.public_node_url = 'http://192.168.130.2:1317'
            self.tx_look_up = f'https://finder.terra.money/{self.chain_id}/tx/'
            self.get_contract_addresses = contact_addresses(network='MAINNET')

        else:
            self.chain_id = 'bombay-12'
            # self.chain_id = 'tequila-0004'
            # self.public_node_url = 'https://tequila-lcd.terra.dev'
            self.public_node_url = 'https://bombay-lcd.terra.dev'
            # self.public_node_url = 'http://127.0.0.1:1317'
            self.tx_look_up = f'https://finder.terra.money/{self.chain_id}/tx/'
            self.get_contract_addresses = contact_addresses(network='bombay-12')

        # Contract required
        self.aTerra = self.get_contract_addresses['aTerra']
        self.mmMarket = self.get_contract_addresses['mmMarket']
        self.mmOverseer = self.get_contract_addresses['mmOverseer']

        # Load Terra LCD client
        self.terra = LCDClient(
            chain_id=self.chain_id,
            url=self.public_node_url,
            gas_prices=get_terra_gas_prices(),
            gas_adjustment=1.6)

        # Load wallet
        self.mk = MnemonicKey(mnemonic=config.mnemonic)
        self.wallet = self.terra.wallet(self.mk)

    def get_block_height(self):
        return self.terra.tendermint.block_info()['block']['header']['height']

    def get_account_native_balance(self):
        return self.terra.bank.balance(self.wallet.key.acc_address)

    def is_loan_safe(self):
        try:
            current_ltv = anchorprotocol.get_ltv(self)
            is_loan_safe = anchorprotocol.keep_loan_safe(self, current_ltv)
            if not is_loan_safe:
                logger.error(f'keep_loan_safe() function has failed for some reason. Please, investigate and check logs.')

        except Exception as err:
            logger.error(err)
            pass


if __name__ == '__main__':
    while True:
        try:
            anchor_hodl = Terra()
            anchor_hodl.is_loan_safe()
            sleep(30)
        except Exception as err:
            logger.error(err)
            pass

