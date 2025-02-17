import unittest
import os
import requests
import json
import inspect

proxy_url = os.environ.get('PROXY_URL', 'http://localhost:9090/solana')
headers = {'Content-type': 'application/json'}
EXTRA_GAS = int(os.environ.get("EXTRA_GAS", "0"))

def get_line_number():
    cf = inspect.currentframe()
    return cf.f_back.f_lineno


class TestUserStories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_blockNumber",
                             "params": []
                             })).text)
        print('response:', response)
        block_number = response['result']
        print('blockNumber:', int(block_number, 16))

    def test_01_check_eth_estimateGas_on_deploying_a_contract(self):
        print("https://github.com/neonlabsorg/proxy-model.py/issues/122")
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_estimateGas",
                             "params": [{"from": "0x55864414d401c9ff160043c50f6daca3bd22ccfc",
                                         "data": "0x60806040526040518060400160405280600c81526020017f48656c6c6f20576f726c642100000000000000000000000000000000000000008152506000908051906020019061004f929190610062565b5034801561005c57600080fd5b50610107565b828054600181600116156101000203166002900490600052602060002090601f016020900481019282601f106100a357805160ff19168380011785556100d1565b828001600101855582156100d1579182015b828111156100d05782518255916020019190600101906100b5565b5b5090506100de91906100e2565b5090565b61010491905b808211156101005760008160009055506001016100e8565b5090565b90565b6102b6806101166000396000f3fe608060405234801561001057600080fd5b50600436106100365760003560e01c80631f1bd6921461003b5780633917b3df146100be575b600080fd5b610043610141565b6040518080602001828103825283818151815260200191508051906020019080838360005b83811015610083578082015181840152602081019050610068565b50505050905090810190601f1680156100b05780820380516001836020036101000a031916815260200191505b509250505060405180910390f35b6100c66101df565b6040518080602001828103825283818151815260200191508051906020019080838360005b838110156101065780820151818401526020810190506100eb565b50505050905090810190601f1680156101335780820380516001836020036101000a031916815260200191505b509250505060405180910390f35b60008054600181600116156101000203166002900480601f0160208091040260200160405190810160405280929190818152602001828054600181600116156101000203166002900480156101d75780601f106101ac576101008083540402835291602001916101d7565b820191906000526020600020905b8154815290600101906020018083116101ba57829003601f168201915b505050505081565b606060008054600181600116156101000203166002900480601f0160208091040260200160405190810160405280929190818152602001828054600181600116156101000203166002900480156102775780601f1061024c57610100808354040283529160200191610277565b820191906000526020600020905b81548152906001019060200180831161025a57829003601f168201915b505050505090509056fea265627a7a7231582024368df40ce2133f972294ddde9f574e801391af7268266abe1646f640b2294c64736f6c63430005110032",
                                         "value": "0x0",
                                         }]
                             })).text)
        print('response:', response)
        used_gas = response['result']
        print('used_gas:', used_gas)
        self.assertEqual(used_gas, 89078 + EXTRA_GAS)

    def test_02_check_eth_estimateGas_on_deploying_a_contract_with_the_empty_value(self):
        print("https://github.com/neonlabsorg/proxy-model.py/issues/122")
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_estimateGas",
                             "params": [{"from": "0x55864414d401c9ff160043c50f6daca3bd22ccfc",
                                         "data": "0x60806040526040518060400160405280600c81526020017f48656c6c6f20576f726c642100000000000000000000000000000000000000008152506000908051906020019061004f929190610062565b5034801561005c57600080fd5b50610107565b828054600181600116156101000203166002900490600052602060002090601f016020900481019282601f106100a357805160ff19168380011785556100d1565b828001600101855582156100d1579182015b828111156100d05782518255916020019190600101906100b5565b5b5090506100de91906100e2565b5090565b61010491905b808211156101005760008160009055506001016100e8565b5090565b90565b6102b6806101166000396000f3fe608060405234801561001057600080fd5b50600436106100365760003560e01c80631f1bd6921461003b5780633917b3df146100be575b600080fd5b610043610141565b6040518080602001828103825283818151815260200191508051906020019080838360005b83811015610083578082015181840152602081019050610068565b50505050905090810190601f1680156100b05780820380516001836020036101000a031916815260200191505b509250505060405180910390f35b6100c66101df565b6040518080602001828103825283818151815260200191508051906020019080838360005b838110156101065780820151818401526020810190506100eb565b50505050905090810190601f1680156101335780820380516001836020036101000a031916815260200191505b509250505060405180910390f35b60008054600181600116156101000203166002900480601f0160208091040260200160405190810160405280929190818152602001828054600181600116156101000203166002900480156101d75780601f106101ac576101008083540402835291602001916101d7565b820191906000526020600020905b8154815290600101906020018083116101ba57829003601f168201915b505050505081565b606060008054600181600116156101000203166002900480601f0160208091040260200160405190810160405280929190818152602001828054600181600116156101000203166002900480156102775780601f1061024c57610100808354040283529160200191610277565b820191906000526020600020905b81548152906001019060200180831161025a57829003601f168201915b505050505090509056fea265627a7a7231582024368df40ce2133f972294ddde9f574e801391af7268266abe1646f640b2294c64736f6c63430005110032",
                                         }]
                             })).text)
        print('response:', response)
        used_gas = response['result']
        print('used_gas:', used_gas)
        self.assertEqual(used_gas, 89078 + EXTRA_GAS)

    def test_03_check_eth_estimateGas_on_deploying_a_contract_with_the_empty_data(self):
        print("https://github.com/neonlabsorg/proxy-model.py/issues/122")
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_estimateGas",
                             "params": [{"from": "0x55864414d401c9ff160043c50f6daca3bd22ccfc",
                                         "value": "0x0",
                                         }]
                             })).text)
        print('response:', response)
        used_gas = response['result']
        print('used_gas:', used_gas)
        self.assertEqual(used_gas, 53001 + EXTRA_GAS)

    def test_04_check_eth_estimateGas_on_deploying_a_contract_with_the_empty_data_and_value(self):
        print("https://github.com/neonlabsorg/proxy-model.py/issues/122")
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_estimateGas",
                             "params": [{"from": "0x55864414d401c9ff160043c50f6daca3bd22ccfc",
                                         }]
                             })).text)
        print('response:', response)
        used_gas = response['result']
        print('used_gas:', used_gas)
        self.assertEqual(used_gas, 53001 + EXTRA_GAS)

    def test_05_check_params_omitted(self):
        print("https://github.com/neonlabsorg/proxy-model.py/issues/318")
        response = json.loads(requests.post(
            proxy_url, headers=headers,
            data=json.dumps({"jsonrpc": "2.0",
                             "id": get_line_number(),
                             "method": "eth_chainId"
                             })).text)
        print('response:', response)
        chain_id = int(response['result'], 0)
        print('chain_id:', chain_id)
        self.assertEqual(chain_id, 111)

if __name__ == '__main__':
    unittest.main()
