from terra_sdk.client.lcd import LCDClient
from terra_sdk.key.mnemonic import MnemonicKey
from terra_sdk.core.coins import Coins
from terra_sdk.core.coins import Coin
from terra_sdk.core.auth import StdFee
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
default_logger = logging.getLogger(__name__)
base_logger = logging.getLogger('info_logger')
repay_logger = logging.getLogger('repay_logger')


if config.NETWORK == 'MAINNET':
    chain_id = 'columbus-4'
    public_node_url = 'https://lcd.terra.dev'
    contact_addresses = contact_addresses(network='MAINNET')
    tx_look_up = f'https://finder.terra.money/{chain_id}/tx/'

else:
    chain_id = 'tequila-0004'
    public_node_url = 'https://tequila-fcd.terra.dev'
    contact_addresses = contact_addresses(network='TESTNET')
    tx_look_up = f'https://finder.terra.money/{chain_id}/tx/'

# Contract required
aTerra = contact_addresses['aTerra']
mmMarket = contact_addresses['mmMarket']
mmOverseer = contact_addresses['mmOverseer']

# Connect to Testnet
terra = LCDClient(chain_id=chain_id, url=public_node_url)
# Desire wallet via passphrase
mk = MnemonicKey(mnemonic=config.mnemonic)
# Define what wallet to use
wallet = terra.wallet(mk)
# Account Add
account_address = wallet.key.acc_address
# print(f"Terra Address: {account_address}")
# Check balance
balance = terra.bank.balance(address=account_address)
# print(f"Balance: {balance.to_dec_coins().div(1000000)}")


def getting_current_loan_percent():
    """Getting loan percent by querying borrow_limit and loan_amount and return its percentage"""
    query_msg_borrow_limit = {
        "borrow_limit": {
            "borrower": account_address,
        },
    }
    borrow_limit_result = terra.wasm.contract_query(mmOverseer, query_msg_borrow_limit)

    query_msg_loan = {
        "borrower_info": {
            "borrower": account_address,
        },
    }
    loan_amount_result = terra.wasm.contract_query(mmMarket, query_msg_loan)

    query_msg_anchor_deposited = {
        "balance": {
            "address": account_address,
        },
    }
    total_deposited_amount = terra.wasm.contract_query(aTerra, query_msg_anchor_deposited)

    loan_amount = int(loan_amount_result['loan_amount']) / 1000000
    borrow_limit = int(borrow_limit_result['borrow_limit']) / 1000000
    total_deposited_amount = int(total_deposited_amount['balance']) / 1000000
    current_percent = loan_amount / borrow_limit
    left_to_trigger = round(config.trigger_at_percent - round(current_percent * 100, 2), 2)

    loan_details = {'loan_amount': loan_amount, 'borrow_limit': borrow_limit, 'current_percent': current_percent,
                    'total_deposited_amount': total_deposited_amount, 'left_to_trigger': left_to_trigger}

    return loan_details


def execute_withdraw_ust_from_anchor(amount):
    fee_estimation = get_fee_estimation()
    base_logger.debug(f"Withdrawing ${amount:,.2f} + ${int(fee_estimation) / 1000000:,.2f} fees from Anchor ...")
    amount = (amount * 1000000) + int(fee_estimation)

    send = MsgExecuteContract(
        sender=wallet.key.acc_address,
        contract=aTerra,
        execute_msg={
            "send": {
                "contract": mmMarket,
                "amount": str(amount),
                "msg": "eyJyZWRlZW1fc3RhYmxlIjp7fX0="}
        },
        coins=Coins()
    ),

    fee = str(int(fee_estimation) + 250000) + 'uusd'
    sendtx = wallet.create_and_sign_tx(send, fee=StdFee(1000000, fee))
    result = terra.tx.broadcast(sendtx)

    return result.txhash


def borrow_ust_from_anchor(amount):
    fee_estimation = get_fee_estimation()
    base_logger.debug(f"Borrowing ${amount:,.2f} + ${int(fee_estimation) / 1000000:,.2f} fees from Anchor ...")
    amount = int((amount * 1000000) + int(fee_estimation))
    test = '150000000'

    send = MsgExecuteContract(
        sender=wallet.key.acc_address,
        contract=mmMarket,
        execute_msg={
            "borrow_stable": {
                "borrow_amount": f'{amount}'
            }
        },
        coins=Coins()
    ),

    fee = str(int(fee_estimation) + 250000) + 'uusd'
    sendtx = wallet.create_and_sign_tx(send, fee=StdFee(1000000, fee))
    result = terra.tx.broadcast(sendtx)

    return result.txhash


def execute_loan_repay(amount):
    fee_estimation = get_fee_estimation()
    amount = (amount * 1000000)

    # Include fee also ...
    coin = Coin('uusd', amount + int(fee_estimation)).to_data()
    coins = Coins.from_data([coin])

    # print(f"[~] Repaying ${amount / 1000000:,.2f} off the loan ...")
    send = MsgExecuteContract(
        sender=wallet.key.acc_address,
        contract=mmMarket,
        execute_msg={
            "repay_stable": {}
        },
        coins=coins
    ),

    fee = str(int(fee_estimation) + 250000) + 'uusd'
    sendtx = wallet.create_and_sign_tx(send, fee=StdFee(1000000, fee))
    result = terra.tx.broadcast(sendtx)

    return result.txhash


def get_fee_estimation():
    estimation = terra.treasury.tax_cap('uusd')
    return estimation.to_data().get('amount')


def check_tx_info(tx_hash):
    try:
        tx_look_up_on_chain = terra.tx.tx_info(tx_hash)
        sleep(1)
        return tx_look_up_on_chain

    except LCDResponseError as err:
        base_logger.error(err)
        # return str(err)


def keep_loan_safe():
    loan_details = getting_current_loan_percent()
    current_percent = loan_details['current_percent']
    loan_amount = loan_details['loan_amount']
    anchor_deposited_amount = loan_details['total_deposited_amount']
    left_to_trigger = loan_details['left_to_trigger']
    target_percent = config.target_percent / 100
    trigger_at_percent = config.trigger_at_percent / 100

    # Check of there is anything to pay before run it
    if int(loan_amount) < 10:
        line = "Hummm ... It seems there is nothing to repay!"
        base_logger.warning(line)
        return True

    # Check if we need to repay!
    if left_to_trigger < 0:
        run_stats = (f'REPAYING ... Left until trigger: {left_to_trigger}%, Current at: {current_percent:.2%},'
                     f' Triggering at: {config.trigger_at_percent}%, Borrow Limit target: {config.target_percent}%.')
        #  f' loan_amount: ${loan_amount:,.2f}, deposited_amount: ${anchor_deposited_amount:,.2f}, '
        # print(line)
        base_logger.info(run_stats)

    # Check if we can borrow some more, if enabled ...
    elif config.enabled_auto_borrow and current_percent < config.auto_borrow_at_percent / 100:
        borrow_amount = int(((config.target_percent / 100) - current_percent) / current_percent * loan_amount)
        run_stats = (f'BORROWING - Left until trigger: {left_to_trigger}%, Current at: {current_percent:.2%},'
                     # f' loan_amount: ${loan_amount:,.2f}, deposited_amount: ${anchor_deposited_amount:,.2f}, '
                     f' Triggering at: {config.trigger_at_percent}%, Borrow Limit target {config.target_percent}%.')
        borrow_tx = borrow_ust_from_anchor(borrow_amount)
        if borrow_tx:
            if config.NOTIFY_SLACK:
                slack_msg = f"*Borrowed More!*\n\n_Borrowed amount:_ `${borrow_amount}`\n" \
                            f"_Triggered at:_ `{current_percent:.2%}`\n" \
                            f"TX: [{borrow_tx}]({tx_look_up}{borrow_tx})"
                slack_webhook(slack_msg)
            if config.NOTIFY_TELEGRAM:
                telegram_msg = f"*Borrowed More!*\n\n_Borrowed amount:_ `${borrow_amount}`\n" \
                            f"_Triggered at:_ `{current_percent:.2%}`\n" \
                            f"TX: [{borrow_tx}]({tx_look_up}{borrow_tx})"
                telegram_notification(telegram_msg)

    else:
        run_stats = (f'Left until trigger: {left_to_trigger}%, Current at: {current_percent:.2%},'
                     # f' loan_amount: ${loan_amount:,.2f}, deposited_amount: ${anchor_deposited_amount:,.2f}, '
                     f' Triggering at: {config.trigger_at_percent}%, Borrow Limit target {config.target_percent}%.')
        # print(line)
        base_logger.info(run_stats)

    # If current_percent is bigger than trigger_at_percent, it means we need to repay!
    if current_percent > trigger_at_percent:
        repay_amount = int((current_percent - target_percent) / current_percent * loan_amount)

        # Check if we can pay from the wallet directly rather than get it from aUST (why would someone leave UST sitting in there ?)
        get_balance_wallet_ust = balance.get('uusd')
        should_get_from_anchor = True
        if get_balance_wallet_ust:
            get_balance_wallet_ust = int(get_balance_wallet_ust.amount / 1000000)
            # leave 10 UST for fees and so on ...
            if (get_balance_wallet_ust - 10) > repay_amount:
                should_get_from_anchor = False
                base_logger.info(f"Paying loan from {repay_amount} UST leftover in the wallet")

        if should_get_from_anchor:
            # Check if Anchor has funds to be withdrawn from
            # This will query aUST which is not always matching the right amount UST deposited in Anchor for some reason...
            if int(anchor_deposited_amount) >= int(repay_amount):
                repay_amount = repay_amount
            elif int(anchor_deposited_amount) > 10:
                # If not enough deposited in Anchor withdraw whatever sitting there if bigger than $10
                line = f"Not enough on Anchor ... Withdrawing ${anchor_deposited_amount:,.2f}"
                # print(line)
                base_logger.warning(line)
                repay_amount = int(anchor_deposited_amount)
            else:
                # If less than $10 in Anchor, do nothing!
                return False
            # Finally withdraw form anchor ...
            withdraw_from_anchor_tx = execute_withdraw_ust_from_anchor(repay_amount)
            sleep(0.5)

        loan_repay_tx = execute_loan_repay(repay_amount)
        sleep(0.5)

        if not check_tx_info(loan_repay_tx):
            line = f"check_tx_info({loan_repay_tx}) was not found ... Maybe something went wrong ?"
            # print(line)
            base_logger.error(line)
            line = f"Loan Repaid!!! Repay Amount: ${repay_amount:,.2f}, triggered at: {current_percent:.2%} ({config.trigger_at_percent}% trigger limit). TX: {tx_look_up}{loan_repay_tx}"
            repay_logger.warning('TX 404 ... ' + line)
        else:
            line = f"Loan Repaid!!! Repay Amount: ${repay_amount:,.2f}, triggered at: {current_percent:.2%} ({config.trigger_at_percent}% trigger limit). TX: {tx_look_up}{loan_repay_tx}"
            # print(line)
            repay_logger.info(line)
            if config.NOTIFY_SLACK:
                slack_msg = f":money_with_wings: *Loan Repaid* :money_with_wings:\n\n_Repaid amount:_ `${repay_amount}`\n" \
                            f"_Triggered at:_ `{current_percent:.2%}`\n" \
                            f"_Borrow Limit trigger:_ `{config.trigger_at_percent}%`\n" \
                            f"_Borrow Limit target:_ `{config.target_percent}%`\n" \
                            f"TX: [{loan_repay_tx}]({tx_look_up}{loan_repay_tx})"
                slack_webhook(slack_msg)
            if config.NOTIFY_TELEGRAM:
                telegram_msg = f"*Loan Repaid*\n\n_Repaid amount:_ `${repay_amount}`\n" \
                            f"_Triggered at:_ `{current_percent:.2%}`\n" \
                            f"_Borrow Limit trigger:_ `{config.trigger_at_percent}%`\n" \
                            f"_Borrow Limit target:_ `{config.target_percent}%`\n" \
                            f"TX: [{loan_repay_tx}]({tx_look_up}{loan_repay_tx})"
                telegram_notification(telegram_msg)
            return line
    else:
        # Does not need to act! We good!
        return run_stats


if __name__ == '__main__':
    keep_loan_safe = keep_loan_safe()
    if not keep_loan_safe:
        print("Oh no!!! Something went wrong!")
        base_logger.error("Oh no!!! Something went wrong! - keep_loan_safe() returned empty.")
    else:
        print(f"[+] {datetime.now():%d-%m-%Y %H:%M:%S} -> {keep_loan_safe}")
