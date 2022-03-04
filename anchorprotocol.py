import time
from terra_sdk.client.lcd import LCDClient
from terra_sdk.key.mnemonic import MnemonicKey
from terra_sdk.core.coins import Coins
from terra_sdk.core.coins import Coin
from terra_sdk.core.fee import Fee
from terra_sdk.client.lcd.api.tx import CreateTxOptions
from terra_sdk.core.bank import MsgSend
from terra_sdk.core.wasm import MsgExecuteContract
from terra_sdk.exceptions import LCDResponseError
from time import sleep
import logging_config
from contact_addresses import contact_addresses
import config
from datetime import datetime
from send_notification import slack_webhook, telegram_notification
import os
import logging.config

# Logging INIT
if not os.path.exists('./logs'):
    os.makedirs('logs')

logging.config.dictConfig(logging_config.LOGGING)
logger = logging.getLogger(__name__)
logger_repay = logging.getLogger('repaying')


def keep_loan_safe(anchor_hodl, current_ltv):
    try:
        # check if account have more than $1 out loan
        if current_ltv and current_ltv['loan_amount'] < 1:
            logger.error(f"Account: {current_ltv['account_address']} does not have a current loan. "
                         f"Total loan amount: ${current_ltv['loan_amount']:.4f}")
            return True

        # check if we need to repay by checking "left_to_trigger" value
        if current_ltv['left_to_trigger'] < 0:
            output = format_action_current_ltv(current_ltv)
            logger.info(f"REPAYING -> {output}")

            # get total uusd amount minus repay amount + $5 (for the sake of not running out in fees!)
            repay_amount_required = calculate_repay_amount(
                current_ltv) + 10  # always increase + 10 to cover feeds and others
            # check user balance and if has enough for repay
            balance = anchor_hodl.get_account_native_balance()

            min_amount_in_wallet = balance[0].get('uusd').sub(repay_amount_required * 1000000).amount / 1000000
            if min_amount_in_wallet > 10:  # Always keep at least $10 sitting in the wallet
                execute_repay = anchor_execute_loan_repay(anchor_hodl, repay_amount_required)
                broadcast_result = anchor_hodl.terra.tx.broadcast(execute_repay)
                # check TX and log it
                time.sleep(3)
                if broadcast_result.txhash:
                    repay_log = f"Loan Repaid!!! Repay Amount: ${repay_amount_required:,.2f}, " \
                                f"triggered at: {current_ltv['left_to_trigger']} " \
                                f"({config.trigger_at_percent}% trigger limit). " \
                                f"TX: {anchor_hodl.tx_look_up}{broadcast_result.txhash}"
                    logger_repay.info(repay_log)
                    # send notifications
                    send_notifications(anchor_hodl, current_ltv, repay_amount_required, broadcast_result)
                    return True

            # withdraw from anchor earns and repay
            else:
                # check aUST Balance
                aust_balance = get_aust_amount(anchor_hodl) / 1000000
                # if aSUT in earn is less than $10
                if aust_balance < 10:
                    logger.error(f"Not much deposited in Anchor. Can't use it for repay.")
                    return False

                aust_rate = get_aUST_rate(anchor_hodl)
                aust_repay_amount = int(repay_amount_required / aust_rate) + 3  # append an extra aUST

                # check if account has enough in earn (aust) so we can use to repay it
                if not aust_balance >= aust_repay_amount:
                    logger.warning(f"aUST is not enough. Required: {aust_repay_amount}, Available: {aust_balance}. "
                                   f"Will withdraw all {aust_balance} balance")
                    aust_repay_amount = aust_balance

                # withdraw
                execute_withdraw = anchor_execute_withdraw_from_earn(anchor_hodl, aust_repay_amount)
                broadcast_result = anchor_hodl.terra.tx.broadcast(execute_withdraw)
                time.sleep(2)
                # Repay
                execute_repay = anchor_execute_loan_repay(anchor_hodl, repay_amount_required)
                broadcast_result = anchor_hodl.terra.tx.broadcast(execute_repay)
                time.sleep(2)
                if broadcast_result.txhash:
                    repay_log = f"Loan Repaid!!! Repay Amount: ${repay_amount_required:,.2f}, " \
                                f"triggered at: {current_ltv['left_to_trigger']} " \
                                f"({config.trigger_at_percent}% trigger limit). " \
                                f"TX: {anchor_hodl.tx_look_up}{broadcast_result.txhash}"
                    logger_repay.info(repay_log)
                    logger.info(repay_log)
                    send_notifications(anchor_hodl, current_ltv, repay_amount_required, broadcast_result)
                    return True

        # No need repay !
        else:
            output = format_action_current_ltv(current_ltv)
            logger.info(output)

            # check if bot needs to borrow more based on "auto borrow" flag in config
            if config.enabled_auto_borrow and current_ltv['current_percent'] < config.auto_borrow_at_percent / 100:
                borrow_amount = int(
                    ((config.target_percent / 100) - current_ltv['current_percent']) / current_ltv['current_percent'] *
                    current_ltv['loan_amount'])
                execute_borrow = anchor_execute_borrow_ust(anchor_hodl, borrow_amount)
                broadcast_result = anchor_hodl.terra.tx.broadcast(execute_borrow)
                time.sleep(2)
                if broadcast_result.txhash:
                    borrow_log = f"Borrowed! Total Amount: ${borrow_amount:,.2f}, " \
                                f"triggered at: {current_ltv['left_to_trigger']} " \
                                f"({config.trigger_at_percent}% trigger limit). " \
                                f"TX: {anchor_hodl.tx_look_up}{broadcast_result.txhash}"
                    logger.info(borrow_log)

                # Depsoit ust into anchor earn after borrowing
                deposit_amount = borrow_amount - 10 # always increase + 10 to cover fees
                if deposit_amount > 0:
                    execute_deposit = anchor_execute_deposit_earn(anchor_hodl, deposit_amount)
                    broadcast_result = anchor_hodl.terra.tx.broadcast(execute_deposit)
                    time.sleep(2)
                    if broadcast_result.txhash:
                       deposit_log = f"Deposited! Total Amount: ${deposit_amount:,.2f}, "\
                                     f"TX: {anchor_hodl.tx_look_up}{broadcast_result.txhash}"
                else:
                    deposit_log = "Deposit Skipped! Not enough borrowed to deposit."

                logger.info(deposit_log)
            return True

    except Exception as err:
        logger.exception(f"keep_loan_safe() had an exception. Please, check logs and investigate!")
        pass


def get_aust_amount(anchor_hodl):
    query_msg = {'balance': {
        'address': anchor_hodl.wallet.key.acc_address
    }
    }
    aust_amount = anchor_hodl.terra.wasm.contract_query(anchor_hodl.aTerra, query_msg)

    return int(aust_amount['balance'])


def send_notifications(anchor_hodl, current_ltv, repay_amount, broadcast_result):
    if config.NOTIFY_SLACK:
        slack_msg = f":money_with_wings: *Loan Repaid* :money_with_wings:\n\n_Repaid amount:_ `${repay_amount}`\n" \
                    f"_Triggered at:_ `{current_ltv['left_to_trigger']}`\n" \
                    f"_Borrow Limit trigger:_ `{config.trigger_at_percent}%`\n" \
                    f"_Borrow Limit target:_ `{config.target_percent}%`\n" \
                    f"TX: [{broadcast_result.txhash}]({anchor_hodl.tx_look_up}{broadcast_result.txhash})"
        slack_webhook(slack_msg)
    if config.NOTIFY_TELEGRAM:
        telegram_msg = f"*Loan Repaid*\n\n_Repaid amount:_ `${repay_amount}`\n" \
                       f"_Triggered at:_ `{current_ltv['left_to_trigger']}`\n" \
                       f"_Borrow Limit trigger:_ `{config.trigger_at_percent}%`\n" \
                       f"_Borrow Limit target:_ `{config.target_percent}%`\n" \
                       f"TX: [{broadcast_result.txhash}]({anchor_hodl.tx_look_up}{broadcast_result.txhash})"
        telegram_notification(telegram_msg)


def get_ltv(anchor_hodl):
    """Getting loan percent by querying borrow_limit and loan_amount and return its percentage"""
    query_msg_borrow_limit = {
        "borrow_limit": {
            "borrower": anchor_hodl.wallet.key.acc_address,
        },
    }
    borrow_limit_result = anchor_hodl.terra.wasm.contract_query(anchor_hodl.mmOverseer, query_msg_borrow_limit)

    # https://github.com/Anchor-Protocol/money-market-contracts/blob/main/contracts/market/src/borrow.rs#L376
    query_msg_loan = {
        "borrower_info": {
            "borrower": anchor_hodl.wallet.key.acc_address,
            "block_height": 1
        },
    }

    loan_amount_result = anchor_hodl.terra.wasm.contract_query(anchor_hodl.mmMarket, query_msg_loan)

    query_msg_anchor_deposited = {
        "balance": {
            "address": anchor_hodl.wallet.key.acc_address,
        },
    }
    total_deposited_amount = anchor_hodl.terra.wasm.contract_query(anchor_hodl.aTerra, query_msg_anchor_deposited)

    loan_amount = int(loan_amount_result['loan_amount']) / 1000000
    borrow_limit = int(borrow_limit_result['borrow_limit']) / 1000000
    total_deposited_amount = int(total_deposited_amount['balance']) / 1000000
    current_percent = loan_amount / borrow_limit
    left_to_trigger = round(config.trigger_at_percent - round(current_percent * 100, 2), 2)

    loan_details = {
        'loan_amount': loan_amount,
        'borrow_limit': borrow_limit,
        'current_percent': current_percent,
        'total_deposited_amount': total_deposited_amount,
        'left_to_trigger': left_to_trigger,
        'account_address': anchor_hodl.wallet.key.acc_address
    }

    return loan_details


def format_action_current_ltv(current_ltv):
    format = f"Left until trigger: {current_ltv['left_to_trigger']}%, " \
             f"Current at: {current_ltv['current_percent']:.2%}, " \
             f"Triggering at: {config.trigger_at_percent}%, " \
             f"Borrow Limit target: {config.target_percent}%"

    return format


def calculate_borrow_amount(current_ltv):
    target_percent = config.target_percent / 100
    borrow_amount = int(
        (target_percent - current_ltv['current_percent']) / current_ltv['current_percent'] * current_ltv['loan_amount'])
    return borrow_amount


def calculate_repay_amount(current_ltv):
    # Calculate the repay amount required based on the desired "target_percent" value from user config.
    # target_percent is where ltv will be at once repay is complete.
    # return will be in UST amount rather than uusd
    target_percent = config.target_percent / 100
    repay_amount = int(
        (current_ltv['current_percent'] - target_percent) / current_ltv['current_percent'] * current_ltv['loan_amount'])
    return repay_amount


def get_aUST_rate(anchor_hodl):
    query_msg_aUST_rate = {
        "epoch_state": {},
    }
    aUST_rate_result = anchor_hodl.terra.wasm.contract_query(anchor_hodl.mmMarket, query_msg_aUST_rate)
    aUST_rate = float(aUST_rate_result['exchange_rate'])

    return aUST_rate


def anchor_execute_loan_repay(anchor_hodl, amount):
    amount = (amount * 1000000)
    coins = Coins.from_str(f'{amount}uusd')
    contract_address = anchor_hodl.mmMarket
    msg = {
        "repay_stable": {}
    }

    anchor_execute_loan_repay_tx = contract_executor(anchor_hodl, contract_address, msg, coins)

    return anchor_execute_loan_repay_tx


def anchor_execute_withdraw_from_earn(anchor_hodl, amount):
    amount = (amount * 1000000)
    coins = Coins()
    contract_address = anchor_hodl.aTerra
    msg = {
        "send": {
            "msg": "eyJyZWRlZW1fc3RhYmxlIjp7fX0=",
            "amount": f"{amount}",
            "contract": f"{anchor_hodl.mmMarket}"
        }
    }
    anchor_execute_withdraw_from_earn_tx = contract_executor(anchor_hodl, contract_address, msg, coins)

    return anchor_execute_withdraw_from_earn_tx


# BORROW
def anchor_execute_borrow_ust(anchor_hodl, amount):
    amount = (amount * 1000000)
    coins = Coins()
    contract_address = anchor_hodl.mmMarket
    msg = {
        "borrow_stable": {
            "borrow_amount": f"{amount}"
        }
    }
    anchor_execute_loan_repay_tx = contract_executor(anchor_hodl, contract_address, msg, coins)

    return anchor_execute_loan_repay_tx

def anchor_execute_deposit_earn(anchor_hodl, amount):
    # Deposit UST into anchor earn
    amount = int(amount * 1000000)
    coin = Coin("uusd", amount).to_data()
    coins = Coins.from_data([coin])

    contract_address = anchor_hodl.mmMarket
    msg = {"deposit_stable": {}}

    tx_return = contract_executor(anchor_hodl, contract_address, msg, coins)

    return tx_return

def contract_executor(anchor_hodl, contract_addr, execute_msg, send_coins):
    # sequence = anchor_hodl.wallet.sequence()

    execute = MsgExecuteContract(
        sender=anchor_hodl.wallet.key.acc_address,
        contract=contract_addr,
        execute_msg=execute_msg,
        coins=send_coins,
    )
    try:
        tx = anchor_hodl.wallet.create_and_sign_tx(
            CreateTxOptions(msgs=[execute], fee=Fee(600000, "2500000uusd"), memo="AnchorHODL!")
        )
        return tx

    except Exception as err:
        logger.error(f"Error: {err}")
        pass
