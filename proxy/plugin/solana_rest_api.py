# -*- coding: utf-8 -*-
"""
    proxy.py
    ~~~~~~~~
    ⚡⚡⚡ Fast, Lightweight, Pluggable, TLS interception capable proxy server focused on
    Network monitoring, controls & Application development, testing, debugging.

    :copyright: (c) 2013-present by Abhinav Singh and contributors.
    :license: BSD, see LICENSE for more details.
"""
from typing import List, Tuple, Optional
import copy
import json
import unittest
import eth_utils
import rlp
import solana
from solana.account import Account as sol_Account
from ..common.utils import socket_connection, text_, build_http_response
from ..http.codes import httpStatusCodes
from ..http.parser import HttpParser
from ..http.websocket import WebsocketFrame
from ..http.server import HttpWebServerBasePlugin, httpProtocolTypes
from .eth_proto import Trx as EthTrx
from solana.rpc.api import Client as SolanaClient, SendTransactionError as SolanaTrxError
from sha3 import keccak_256
import base58
import traceback
import threading

from .solana_rest_api_tools import EthereumAddress, get_token_balance_or_airdrop, getAccountInfo, call_signed, \
                                   call_emulated, EthereumError, neon_config_load, MINIMAL_GAS_PRICE, estimate_gas
from solana.rpc.commitment import Commitment, Confirmed
from web3 import Web3
import logging
from ..core.acceptor.pool import proxy_id_glob
from ..indexer.utils import get_trx_results, LogDB
from ..indexer.sql_dict import SQLDict
from ..environment import evm_loader_id, solana_cli, solana_url, neon_cli

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

modelInstanceLock = threading.Lock()
modelInstance = None

NEON_PROXY_PKG_VERSION = '0.4.1-rc0'
NEON_PROXY_REVISION = 'NEON_PROXY_REVISION_TO_BE_REPLACED'

class EthereumModel:
    def __init__(self):
        self.signer = self.get_solana_account()
        self.client = SolanaClient(solana_url)

        self.logs_db = LogDB()
        self.blocks_by_hash = SQLDict(tablename="solana_blocks_by_hash")
        self.ethereum_trx = SQLDict(tablename="ethereum_transactions")
        self.eth_sol_trx = SQLDict(tablename="ethereum_solana_transactions")
        self.sol_eth_trx = SQLDict(tablename="solana_ethereum_transactions")

        with proxy_id_glob.get_lock():
            self.proxy_id = proxy_id_glob.value
            proxy_id_glob.value += 1
        logger.debug("worker id {}".format(self.proxy_id))

        neon_config_load(self)


    @staticmethod
    def get_solana_account() -> Optional[sol_Account]:
        solana_account: Optional[sol_Account] = None
        res = solana_cli().call('config', 'get')
        substr = "Keypair Path: "
        path = ""
        for line in res.splitlines():
            if line.startswith(substr):
                path = line[len(substr):].strip()
        if path == "":
            raise Exception("cannot get keypair path")

        with open(path.strip(), mode='r') as file:
            pk = (file.read())
            nums = list(map(int, pk.strip("[] \n").split(',')))
            nums = nums[0:32]
            values = bytes(nums)
            solana_account = sol_Account(values)
        return solana_account

    def neon_proxy_version(self):
        return 'Neon-proxy/v' + NEON_PROXY_PKG_VERSION + '-' + NEON_PROXY_REVISION

    def web3_clientVersion(self):
        neon_config_load(self)
        return self.neon_config_dict['web3_clientVersion']

    def eth_chainId(self):
        neon_config_load(self)
        # NEON_CHAIN_ID is a string in decimal form
        return hex(int(self.neon_config_dict['NEON_CHAIN_ID']))

    def neon_cli_version(self):
        return neon_cli().version()

    def net_version(self):
        neon_config_load(self)
        # NEON_CHAIN_ID is a string in decimal form
        return self.neon_config_dict['NEON_CHAIN_ID']

    def eth_gasPrice(self):
        return hex(MINIMAL_GAS_PRICE)

    def eth_estimateGas(self, param):
        try:
            caller_id = param.get('from', "0x0000000000000000000000000000000000000000")
            contract_id = param.get('to', "deploy")
            data = param.get('data', "None")
            value = param.get('value', "")
            return estimate_gas(self.client, self.signer, contract_id, EthereumAddress(caller_id), data, value)
        except Exception as err:
            logger.debug("Exception on eth_estimateGas: %s", err)
            raise

    def __repr__(self):
        return str(self.__dict__)

    def process_block_tag(self, tag):
        if tag == "latest":
            slot = int(self.client.get_slot(commitment=Confirmed)["result"])
        elif tag in ('earliest', 'pending'):
            raise Exception("Invalid tag {}".format(tag))
        elif isinstance(tag, str):
            slot = int(tag, 16)
        elif isinstance(tag, int):
            slot = tag
        else:
            raise Exception(f'Failed to parse block tag: {tag}')
        return slot

    def eth_blockNumber(self):
        slot = self.client.get_slot(commitment=Confirmed)['result']
        logger.debug("eth_blockNumber %s", hex(slot))
        return hex(slot)

    def eth_getBalance(self, account, tag):
        """account - address to check for balance.
           tag - integer block number, or the string "latest", "earliest" or "pending"
        """
        eth_acc = EthereumAddress(account)
        logger.debug('eth_getBalance: %s %s', account, eth_acc)
        balance = get_token_balance_or_airdrop(self.client, self.signer, eth_acc)

        return hex(balance * eth_utils.denoms.gwei)

    def eth_getLogs(self, obj):
        fromBlock = None
        toBlock = None
        address = None
        topics = None
        blockHash = None

        if 'fromBlock' in obj:
            fromBlock = self.process_block_tag(obj['fromBlock'])
        if 'toBlock' in obj:
            toBlock = self.process_block_tag(obj['toBlock'])
        if 'address' in obj:
           address = obj['address']
        if 'topics' in obj:
           topics = obj['topics']
        if 'blockHash' in obj:
           blockHash = obj['blockHash']

        return self.logs_db.get_logs(fromBlock, toBlock, address, topics, blockHash)

    def getBlockBySlot(self, slot, full):
        response = self.client._provider.make_request("getBlock", slot, {"commitment":"confirmed", "transactionDetails":"signatures"})
        if 'error' in response:
            raise Exception(response['error']['message'])
        block_info = response['result']
        if block_info is None:
            return None

        transactions = []
        gasUsed = 0
        trx_index = 0
        for signature in block_info['signatures']:
            eth_trx = self.sol_eth_trx.get(signature, None)
            if eth_trx is not None:
                if eth_trx['idx'] == 0:
                    trx_receipt = self.eth_getTransactionReceipt(eth_trx['eth'], block_info)
                    if trx_receipt is not None:
                        gasUsed += int(trx_receipt['gasUsed'], 16)
                    if full:
                        trx = self.eth_getTransactionByHash(eth_trx['eth'], block_info)
                        if trx is not None:
                            trx['transactionIndex'] = hex(trx_index)
                            trx_index += 1
                            transactions.append(trx)
                    else:
                        transactions.append(eth_trx['eth'])

        ret = {
            "gasUsed": hex(gasUsed),
            "hash": '0x' + base58.b58decode(block_info['blockhash']).hex(),
            "number": hex(slot),
            "parentHash": '0x' + base58.b58decode(block_info['previousBlockhash']).hex(),
            "timestamp": hex(block_info['blockTime']),
            "transactions": transactions,
            "logsBloom": '0x'+'0'*512,
            "gasLimit": '0x6691b7',
        }
        return ret

    def eth_getStorageAt(self, account, position, block_identifier):
        '''Retrieves storage data by given position
        Currently supports only 'latest' block
        '''
        if block_identifier != "latest":
            logger.debug(f"Block type '{block_identifier}' is not supported yet")
            raise RuntimeError(f"Not supported block identifier: {block_identifier}")

        try:
            value = neon_cli().call('get-storage-at', account, position)
            return value
        except Exception as err:
            logger.debug(f"Neon-cli failed to execute: {err}")
            return '0x00'

    def eth_getBlockByHash(self, trx_hash, full):
        """Returns information about a block by hash.
            trx_hash - Hash of a block.
            full - If true it returns the full transaction objects, if false only the hashes of the transactions.
        """
        trx_hash = trx_hash.lower()
        slot = self.blocks_by_hash.get(trx_hash, None)
        if slot is None:
            logger.debug("Not found block by hash %s", trx_hash)
            return None
        ret = self.getBlockBySlot(slot, full)
        if ret is not None:
            logger.debug("eth_getBlockByHash: %s", json.dumps(ret, indent=3))
        else:
            logger.debug("Not found block by hash %s", trx_hash)
        return ret

    def eth_getBlockByNumber(self, tag, full):
        """Returns information about a block by block number.
            tag - integer of a block number, or the string "earliest", "latest" or "pending", as in the default block parameter.
            full - If true it returns the full transaction objects, if false only the hashes of the transactions.
        """
        slot = self.process_block_tag(tag)
        ret = self.getBlockBySlot(slot, full)
        if ret is not None:
            logger.debug("eth_getBlockByNumber: %s", json.dumps(ret, indent=3))
        else:
            logger.debug("Not found block by number %s", tag)
        return ret

    def eth_call(self, obj, tag):
        """Executes a new message call immediately without creating a transaction on the block chain.
           Parameters
            obj - The transaction call object
                from: DATA, 20 Bytes - (optional) The address the transaction is sent from.
                to: DATA, 20 Bytes - The address the transaction is directed to.
                gas: QUANTITY - (optional) Integer of the gas provided for the transaction execution. eth_call consumes zero gas, but this parameter may be needed by some executions.
                gasPrice: QUANTITY - (optional) Integer of the gasPrice used for each paid gas
                value: QUANTITY - (optional) Integer of the value sent with this transaction
                data: DATA - (optional) Hash of the method signature and encoded parameters. For details see Ethereum Contract ABI in the Solidity documentation
            tag - integer block number, or the string "latest", "earliest" or "pending", see the default block parameter
        """
        if not obj['data']: raise Exception("Missing data")
        try:
            caller_id = obj.get('from', "0x0000000000000000000000000000000000000000")
            contract_id = obj.get('to', 'deploy')
            data = obj.get('data', "None")
            value = obj.get('value', '')
            return "0x"+call_emulated(contract_id, caller_id, data, value)['result']
        except Exception as err:
            logger.debug("eth_call %s", err)
            raise

    def eth_getTransactionCount(self, account, tag):
        logger.debug('eth_getTransactionCount: %s', account)
        try:
            acc_info = getAccountInfo(self.client, EthereumAddress(account))
            return hex(int.from_bytes(acc_info.trx_count, 'little'))
        except Exception as err:
            print("Can't get account info: %s"%err)
            return hex(0)

    def eth_getTransactionReceipt(self, trxId, block_info = None):
        logger.debug('getTransactionReceipt: %s', trxId)

        trxId = trxId.lower()
        trx_info = self.ethereum_trx.get(trxId, None)
        if trx_info is None:
            logger.debug ("Not found receipt")
            return None

        eth_trx = rlp.decode(bytes.fromhex(trx_info['eth_trx']))

        addr_to = None
        contract = None
        if eth_trx[3]:
            addr_to = '0x' + eth_trx[3].hex()
        else:
            contract = '0x' + bytes(Web3.keccak(rlp.encode((bytes.fromhex(trx_info['from_address'][2:]), eth_trx[0]))))[-20:].hex()

        blockHash = '0x%064x'%trx_info['slot']
        blockNumber = hex(trx_info['slot'])
        try:
            if block_info is None:
                block_info = self.client._provider.make_request("getBlock", trx_info['slot'], {"commitment":"confirmed", "transactionDetails":"none", "rewards":False})['result']
            blockHash = '0x' + base58.b58decode(block_info['blockhash']).hex()
        except Exception as err:
            logger.debug("Can't get block info: %s"%err)

        logs = trx_info['logs']
        for log in logs:
            log['blockHash'] = blockHash

        result = {
            "transactionHash": trxId,
            "transactionIndex": hex(0),
            "blockHash": blockHash,
            "blockNumber": blockNumber,
            "from": trx_info['from_address'],
            "to": addr_to,
            "gasUsed": hex(trx_info['gas_used']),
            "cumulativeGasUsed": hex(trx_info['gas_used']),
            "contractAddress": contract,
            "logs": logs,
            "status": trx_info['status'],
            "logsBloom":"0x"+'0'*512
        }

        logger.debug('RESULT: %s', json.dumps(result, indent=3))
        return result

    def eth_getTransactionByHash(self, trxId, block_info = None):
        logger.debug('eth_getTransactionByHash: %s', trxId)

        trxId = trxId.lower()
        trx_info = self.ethereum_trx.get(trxId, None)
        if trx_info is None:
            logger.debug ("Not found receipt")
            return None

        eth_trx = rlp.decode(bytes.fromhex(trx_info['eth_trx']))
        addr_to = None
        if eth_trx[3]:
            addr_to = '0x' + eth_trx[3].hex()
        for i, eth_field in enumerate(eth_trx):
            if len(eth_field) ==0:
                eth_trx[i] = '0x0'
            else:
                eth_trx[i] = '0x'+eth_field.hex()

        blockHash = '0x%064x'%trx_info['slot']
        blockNumber = hex(trx_info['slot'])
        try:
            if block_info is None:
                block_info = self.client._provider.make_request("getBlock", trx_info['slot'], {"commitment":"confirmed", "transactionDetails":"none", "rewards":False})['result']
            blockHash = '0x' + base58.b58decode(block_info['blockhash']).hex()
        except Exception as err:
            logger.debug("Can't get block info: %s"%err)

        ret = {
            "blockHash": blockHash,
            "blockNumber": blockNumber,
            "hash": trxId,
            "transactionIndex": hex(0),
            "from": trx_info['from_address'],
            "nonce": eth_trx[0],
            "gasPrice": eth_trx[1],
            "gas": eth_trx[2],
            "to": addr_to,
            "value": eth_trx[4],
            "input": eth_trx[5],
            "v": eth_trx[6],
            "r": eth_trx[7],
            "s": eth_trx[8],
        }

        logger.debug("eth_getTransactionByHash: %s", json.dumps(ret, indent=3))
        return ret

    def eth_getCode(self, param,  param1):
        return "0x01"

    def eth_sendTransaction(self, trx):
        logger.debug("eth_sendTransaction")
        logger.debug("eth_sendTransaction: type(trx):%s", type(trx))
        logger.debug("eth_sendTransaction: str(trx):%s", str(trx))
        logger.debug("eth_sendTransaction: trx=%s", json.dumps(trx, cls=JsonEncoder, indent=3))
        raise Exception("eth_sendTransaction is not supported. please use eth_sendRawTransaction")

    def eth_sendRawTransaction(self, rawTrx):
        logger.debug('eth_sendRawTransaction rawTrx=%s', rawTrx)
        trx = EthTrx.fromString(bytearray.fromhex(rawTrx[2:]))
        logger.debug("%s", json.dumps(trx.as_dict(), cls=JsonEncoder, indent=3))
        if trx.gasPrice < MINIMAL_GAS_PRICE:
            raise Exception("The transaction gasPrice is less then the minimum allowable value ({}<{})".format(trx.gasPrice, MINIMAL_GAS_PRICE))

        eth_signature = '0x' + bytes(Web3.keccak(bytes.fromhex(rawTrx[2:]))).hex()

        sender = trx.sender()
        logger.debug('Eth Sender: %s', sender)
        logger.debug('Eth Signature: %s', trx.signature().hex())
        logger.debug('Eth Hash: %s', eth_signature)

        nonce = int(self.eth_getTransactionCount('0x' + sender, None), base=16)

        logger.debug('Eth Sender trx nonce: %s', nonce)
        logger.debug('Operator nonce: %s', trx.nonce)

        if (int(nonce) != int(trx.nonce)):
            raise EthereumError(-32002, 'Verifying nonce before send transaction: Error processing Instruction 1: invalid program argument'
                                .format(int(nonce), int(trx.nonce)),
                                {
                                    'logs': [
                                        '/src/entrypoint.rs Invalid Ethereum transaction nonce: acc {}, trx {}'.format(nonce, trx.nonce),
                                    ]
                                })
        try:
            signature = call_signed(self.signer, self.client, trx, steps=250)

            logger.debug('Transaction signature: %s %s', signature, eth_signature)

            try:
                trx = self.client.get_confirmed_transaction(signature)['result']
                slot = trx['slot']
                block = self.client._provider.make_request("getBlock", slot, {"commitment":"confirmed", "transactionDetails":"none", "rewards":False})['result']
                block_hash = '0x' + base58.b58decode(block['blockhash']).hex()
                got_result = get_trx_results(trx)
                if got_result:
                    (logs, status, gas_used, return_value, slot) = got_result
                    if logs:
                        for rec in logs:
                            rec['transactionHash'] = eth_signature
                            rec['blockHash'] = block_hash
                        self.logs_db.push_logs(logs)

                    self.ethereum_trx[eth_signature] = {
                        'eth_trx': rawTrx[2:],
                        'slot': slot,
                        'logs': logs,
                        'status': status,
                        'gas_used': gas_used,
                        'return_value': return_value,
                        'from_address': '0x'+sender,
                    }
                else:
                    self.ethereum_trx[eth_signature] = {
                        'eth_trx': rawTrx[2:],
                        'slot': slot,
                        'logs': [],
                        'status': 0,
                        'gas_used': 0,
                        'return_value': None,
                        'from_address': '0x'+sender,
                    }
                self.eth_sol_trx[eth_signature] = [signature]
                self.blocks_by_hash[block_hash] = slot
                self.sol_eth_trx[signature] = {
                    'idx': 0,
                    'eth': eth_signature,
                }
            except Exception as err:
                logger.debug(err)

            return eth_signature

        except SolanaTrxError as err:
            self._log_transaction_error(err, logger)
            raise
        except EthereumError as err:
            logger.debug("eth_sendRawTransaction EthereumError:%s", err)
            raise
        except Exception as err:
            logger.debug("eth_sendRawTransaction type(err):%s, Exception:%s", type(err), err)
            raise

    def _log_transaction_error(self, error: SolanaTrxError, logger):
        result = copy.deepcopy(error.result)
        logs = result.get("data", {}).get("logs", [])
        result.get("data", {}).update({"logs": ["\n\t" + log for log in logs]})
        log_msg = str(result).replace("\\n\\t", "\n\t")
        logger.error(f"Got SendTransactionError: {log_msg}")


class JsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytearray):
            return obj.hex()
        if isinstance(obj, bytes):
            return obj.hex()
        return json.JSONEncoder.default(self, obj)


class SolanaContractTests(unittest.TestCase):

    def setUp(self):
        self.model = EthereumModel()
        self.owner = '0xc1566af4699928fdf9be097ca3dc47ece39f8f8e'
        self.token1 = '0x49a449cd7fd8fbcf34d103d98f2c05245020e35b'

    def getBalance(self, account):
        return int(self.model.eth_getBalance(account, 'latest'), 16)

    def getBlockNumber(self):
        return int(self.model.eth_blockNumber(), 16)

    def getTokenBalance(self, token, account):
        return self.model.contracts[token].balances.get(account, 0)

    def test_transferFunds(self):
        (sender, receiver, amount) = (self.owner, '0x8d900bfa2353548a4631be870f99939575551b60', 123*10**18)
        senderBalance = self.getBalance(sender)
        receiverBalance = self.getBalance(receiver)
        blockNumber = self.getBlockNumber()

        receiptId = self.model.eth_sendRawTransaction('0xf8730a85174876e800825208948d900bfa2353548a4631be870f99939575551b608906aaf7c8516d0c0000808602e92be91e86a040a2a5d73931f66185e8526f09c4d0dc1f389c1b9fcd5e37a012839e6c5c70f0a00554615806c3fa7dc7c8096b3bfed5a29354045e56982bdf3ee11f649e53d51e')
        logger.debug('ReceiptId:', receiptId)

        self.assertEqual(self.getBalance(sender), senderBalance - amount)
        self.assertEqual(self.getBalance(receiver), receiverBalance + amount)
        self.assertEqual(self.getBlockNumber(), blockNumber+1)

        receipt = self.model.eth_getTransactionReceipt(receiptId)
        logger.debug('Receipt:', receipt)

        block = self.model.eth_getBlockByNumber(receipt['blockNumber'], False)
        logger.debug('Block:', block)

        self.assertTrue(receiptId in block['transactions'])

    def test_transferTokens(self):
        (token, sender, receiver, amount) = ('0xcf73021fde8654e64421f67372a47aa53c4341a8', '0x324726ca9954ed9bd567a62ae38a7dd7b4eaad0e', '0xb937ad32debafa742907d83cb9749443160de0c4', 32)
        senderBalance = self.getTokenBalance(token, sender)
        receiverBalance = self.getTokenBalance(token, receiver)
        blockNumber = self.getBlockNumber()


        receiptId = self.model.eth_sendRawTransaction('0xf8b018850bdfd63e00830186a094b80102fd2d3d1be86823dd36f9c783ad0ee7d89880b844a9059cbb000000000000000000000000cac68f98c1893531df666f2d58243b27dd351a8800000000000000000000000000000000000000000000000000000000000000208602e92be91e86a05ed7d0093a991563153f59c785e989a466e5e83bddebd9c710362f5ee23f7dbaa023a641d304039f349546089bc0cb2a5b35e45619fd97661bd151183cb47f1a0a')
        logger.debug('ReceiptId:', receiptId)

        self.assertEqual(self.getTokenBalance(token, sender), senderBalance - amount)
        self.assertEqual(self.getTokenBalance(token, receiver), receiverBalance + amount)

        receipt = self.model.eth_getTransactionReceipt(receiptId)
        logger.debug('Receipt:', receipt)

        block = self.model.eth_getBlockByNumber(receipt['blockNumber'], False)
        logger.debug('Block:', block)

        self.assertTrue(receiptId in block['transactions'])


class SolanaProxyPlugin(HttpWebServerBasePlugin):
    """Extend in-built Web Server to add Reverse Proxy capabilities.
    """

    SOLANA_PROXY_LOCATION: str = r'/solana$'
    SOLANA_PROXY_PASS = [
        b'http://localhost:8545/'
    ]

    def __init__(self, *args):
        HttpWebServerBasePlugin.__init__(self, *args)
        self.model = SolanaProxyPlugin.getModel()

    @classmethod
    def getModel(cls):
        global modelInstanceLock
        global modelInstance
        with modelInstanceLock:
            if modelInstance is None:
                modelInstance = EthereumModel()
            return modelInstance

    def routes(self) -> List[Tuple[int, str]]:
        return [
            (httpProtocolTypes.HTTP, SolanaProxyPlugin.SOLANA_PROXY_LOCATION),
            (httpProtocolTypes.HTTPS, SolanaProxyPlugin.SOLANA_PROXY_LOCATION)
        ]

    def process_request(self, request):
        response = {
            'jsonrpc': '2.0',
            'id': request.get('id', None),
        }
        try:
            method = getattr(self.model, request['method'])
            params = request.get('params', [])
            response['result'] = method(*params)
        except SolanaTrxError as err:
            traceback.print_exc()
            response['error'] = err.result
        except EthereumError as err:
            traceback.print_exc()
            response['error'] = err.getError()
        except Exception as err:
            traceback.print_exc()
            response['error'] = {'code': -32000, 'message': str(err)}

        return response

    def handle_request(self, request: HttpParser) -> None:
        if request.method == b'OPTIONS':
            self.client.queue(memoryview(build_http_response(
                httpStatusCodes.OK, body=None,
                headers={
                    b'Access-Control-Allow-Origin': b'*',
                    b'Access-Control-Allow-Methods': b'POST, GET, OPTIONS',
                    b'Access-Control-Allow-Headers': b'Content-Type',
                    b'Access-Control-Max-Age': b'86400'
                })))
            return

        logger.debug('<<< %s 0x%x %s', threading.get_ident(), id(self.model), request.body.decode('utf8'))
        response = None

        try:
            request = json.loads(request.body)
            print('type(request) = ', type(request), request)
            if isinstance(request, list):
                response = []
                if len(request) == 0:
                    raise Exception("Empty batch request")
                for r in request:
                    response.append(self.process_request(r))
            elif isinstance(request, object):
                response = self.process_request(request)
            else:
                raise Exception("Invalid request")
        except Exception as err:
            traceback.print_exc()
            response = {'jsonrpc': '2.0', 'error': {'code': -32000, 'message': str(err)}}

        logger.debug('>>> %s 0x%0x %s', threading.get_ident(), id(self.model), json.dumps(response))

        self.client.queue(memoryview(build_http_response(
            httpStatusCodes.OK, body=json.dumps(response).encode('utf8'),
            headers={
                b'Content-Type': b'application/json',
                b'Access-Control-Allow-Origin': b'*',
            })))

    def on_websocket_open(self) -> None:
        pass

    def on_websocket_message(self, frame: WebsocketFrame) -> None:
        pass

    def on_websocket_close(self) -> None:
        pass

