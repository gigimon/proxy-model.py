import logging
import random
import base64
from datetime import datetime
from solana.publickey import PublicKey
from solana.rpc.commitment import Confirmed
from solana.rpc.api import Client as SolanaClient
from solana.account import Account as SolanaAccount
from proxy.common_neon.neon_instruction import NeonInstruction


from proxy.environment import read_elf_params, TIMEOUT_TO_RELOAD_NEON_CONFIG, NEW_USER_AIRDROP_AMOUNT
from proxy.common_neon.transaction_sender import TransactionSender
from proxy.common_neon.solana_interactor import SolanaInteractor
from proxy.common_neon.address import ether2program, getTokenAddr, ACCOUNT_INFO_LAYOUT, AccountInfo
from proxy.common_neon.address import EthereumAddress
from proxy.common_neon.errors import SolanaAccountNotFoundError, SolanaErrors
from proxy.common_neon.utils import get_from_dict


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def neon_config_load(ethereum_model):
    try:
        ethereum_model.neon_config_dict
    except AttributeError:
        logger.debug("loading the neon config dict for the first time!")
        ethereum_model.neon_config_dict = dict()
    else:
        elapsed_time = datetime.now().timestamp() - ethereum_model.neon_config_dict['load_time']
        logger.debug('elapsed_time={} proxy_id={}'.format(elapsed_time, ethereum_model.proxy_id))
        if elapsed_time < TIMEOUT_TO_RELOAD_NEON_CONFIG:
            return

    read_elf_params(ethereum_model.neon_config_dict)
    ethereum_model.neon_config_dict['load_time'] = datetime.now().timestamp()
    # 'Neon/v0.3.0-rc0-d1e4ff618457ea9cbc82b38d2d927e8a62168bec
    ethereum_model.neon_config_dict['web3_clientVersion'] = 'Neon/v' + \
                                                            ethereum_model.neon_config_dict['NEON_PKG_VERSION'] + \
                                                            '-' \
                                                            + ethereum_model.neon_config_dict['NEON_REVISION']
    logger.debug(ethereum_model.neon_config_dict)


def call_signed(signer, client, eth_trx, steps):
    solana_interactor = SolanaInteractor(signer, client)
    trx_sender = TransactionSender(solana_interactor, eth_trx, steps)
    return trx_sender.execute()



def _getAccountData(client, account, expected_length, owner=None):
    info = client.get_account_info(account, commitment=Confirmed)['result']['value']
    if info is None:
        raise Exception("Can't get information about {}".format(account))

    data = base64.b64decode(info['data'][0])
    if len(data) < expected_length:
        raise Exception("Wrong data length for account data {}".format(account))
    return data


def getAccountInfo(client, eth_account: EthereumAddress):
    account_sol, nonce = ether2program(eth_account)
    info = _getAccountData(client, account_sol, ACCOUNT_INFO_LAYOUT.sizeof())
    return AccountInfo.frombytes(info)


def create_eth_account_and_airdrop(client: SolanaClient, signer: SolanaAccount, eth_account: EthereumAddress):
    trx = NeonInstruction(signer.public_key()).trx_with_create_and_airdrop(eth_account)
    result = SolanaInteractor(signer, client).send_transaction(trx, reason='create_eth_account_and_airdrop')
    error = result.get("error")
    if error is not None:
        logger.error(f"Failed to create eth_account and airdrop: {eth_account}, error occurred: {error}")
        raise Exception("Create eth_account error")


def get_token_balance_gwei(client: SolanaClient, pda_account: str) -> int:
    associated_token_account = getTokenAddr(PublicKey(pda_account))
    rpc_response = client.get_token_account_balance(associated_token_account, commitment=Confirmed)
    error = rpc_response.get('error')
    if error is not None:
        message = error.get("message")
        if message == SolanaErrors.AccountNotFound.value:
            raise SolanaAccountNotFoundError()
        logger.error(f"Failed to get_token_balance_gwei by associated_token_account: {associated_token_account}, "
                     f"got get_token_account_balance error: \"{message}\"")
        raise Exception("Getting balance error")

    balance = get_from_dict(rpc_response, "result", "value", "amount")
    if balance is None:
        logger.error(f"Failed to get_token_balance_gwei by associated_token_account: {associated_token_account}, response: {rpc_response}")
        raise Exception("Unexpected get_balance response")
    return int(balance)


def get_token_balance_or_airdrop(client: SolanaClient, signer: SolanaAccount, eth_account: EthereumAddress) -> int:
    solana_account, nonce = ether2program(eth_account)
    logger.debug(f"Get balance for eth account: {eth_account} aka: {solana_account}")

    try:
        return get_token_balance_gwei(client, solana_account)
    except SolanaAccountNotFoundError:
        if NEW_USER_AIRDROP_AMOUNT:
            logger.debug(f"Account not found:  {eth_account} aka: {solana_account} - create")
            create_eth_account_and_airdrop(client, signer, eth_account)
            return get_token_balance_gwei(client, solana_account)
        return 0
