## File: test_query_account_contract.py
## Integration test for the QueryAccount smart contract.
##
## QueryAccount precompiled contract supports three methods:
##
## owner(uint256) returns (uint256)
##     Takes a Solana address, treats it as an address of an account.
##     Returns the account's owner (32 bytes).
##
## length(uint256) returns (uint64)
##     Takes a Solana address, treats it as an address of an account.
##     Returns the length of the account's data (8 bytes).
##
## data(uint256, uint64, uint64) returns (bytes memory)
##     Takes a Solana address, treats it as an address of an account,
##     also takes an offset and length of the account's data.
##     Returns a chunk of the data (length bytes).

import unittest
import os
from web3 import Web3
from solcx import install_solc
install_solc(version='0.7.6')
from solcx import compile_source

issue = 'https://github.com/neonlabsorg/neon-evm/issues/360'
proxy_url = os.environ.get('PROXY_URL', 'http://localhost:9090/solana')
proxy = Web3(Web3.HTTPProvider(proxy_url))
admin = proxy.eth.account.create(issue + '/admin')
user = proxy.eth.account.create(issue + '/user')
proxy.eth.default_account = admin.address

# Address: HPsV9Deocecw3GeZv1FkAPNCBRfuVyfw9MMwjwRe1xaU (a token mint account)
# uint256: 110178555362476360822489549210862241441608066866019832842197691544474470948129

# Address: TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA (owner of the account)
# uint256: 3106054211088883198575105191760876350940303353676611666299516346430146937001

CONTRACT_SOURCE = '''
// SPDX-License-Identifier: MIT
pragma solidity >=0.7.0;

contract QueryAccount {
    address constant precompiled = 0xff00000000000000000000000000000000000002;

    function owner(uint256 solana_address) public returns (uint256) {
        (bool success, bytes memory result) = precompiled.delegatecall(abi.encodeWithSignature("owner(uint256)", solana_address));
        require(success, "QueryAccount.owner failed");
        return to_uint256(result);
    }

    function length(uint256 solana_address) public returns (uint64) {
        (bool success, bytes memory result) = precompiled.delegatecall(abi.encodeWithSignature("length(uint256)", solana_address));
        require(success, "QueryAccount.length failed");
        return to_uint64(result);
    }

    function data(uint256 solana_address, uint64 offset, uint64 len) public returns (bytes memory) {
        (bool success, bytes memory result) = precompiled.delegatecall(abi.encodeWithSignature("data(uint256,uint64,uint64)", solana_address, offset, len));
        require(success, "QueryAccount.data failed");
        return result;
    }

    function to_uint64(bytes memory bb) private pure returns (uint64 result) {
        assembly {
            result := mload(add(bb, 8))
        }
    }

    function to_uint256(bytes memory bb) private pure returns (uint256 result) {
        assembly {
            result := mload(add(bb, 32))
        }
    }
}

contract TestQueryAccount {
    QueryAccount query;

    constructor() {
        query = new QueryAccount();
    }

    function test_metadata_ok() public returns (bool) {
        uint256 solana_address = 110178555362476360822489549210862241441608066866019832842197691544474470948129;

        uint256 golden_ownr = 3106054211088883198575105191760876350940303353676611666299516346430146937001;
        uint64 golden_len = 82;

        uint256 ownr = query.owner(solana_address);
        if (ownr != golden_ownr) {
            return false;
        }

        uint64 len = query.length(solana_address);
        if (len != golden_len) {
            return false;
        }

        // Should return cached result
        ownr = query.owner(solana_address);
        if (ownr != golden_ownr) {
            return false;
        }

        // Should return cached result
        len = query.length(solana_address);
        if (len != golden_len) {
            return false;
        }

        return true;
    }

    function test_metadata_nonexistent_account() public returns (bool) {
        uint256 solana_address = 90000; // hopefully does not exist
        try query.owner(solana_address) {
            //
        } catch {
            return true; // expected exception
        }
        try query.length(solana_address) {
            //
        } catch {
            return true; // expected exception
        }
        return false;
    }

    function test_data_ok() public returns (bool) {
        uint256 solana_address = 110178555362476360822489549210862241441608066866019832842197691544474470948129;
        byte b0 = 0x71;
        byte b1 = 0x33;
        byte b2 = 0xc6;
        byte b3 = 0x12;

        // Test getting subset of data
        uint64 offset = 20;
        uint64 len = 4;
        bytes memory result = query.data(solana_address, offset, len);
        if (result.length != 4) {
            return false;
        }
        if (result[0] != b0) {
            return false;
        }
        if (result[1] != b1) {
            return false;
        }
        if (result[2] != b2) {
            return false;
        }
        if (result[3] != b3) {
            return false;
        }
        // Test getting full data
        offset = 0;
        len = 82;
        result = query.data(solana_address, offset, len);
        if (result.length != 82) {
            return false;
        }

        // Test getting subset of data (cached)
        offset = 20;
        len = 4;
        result = query.data(solana_address, offset, len);
        if (result.length != 4) {
            return false;
        }
        if (result[0] != b0) {
            return false;
        }
        if (result[1] != b1) {
            return false;
        }
        if (result[2] != b2) {
            return false;
        }
        if (result[3] != b3) {
            return false;
        }
        // Test getting full data (cached)
        offset = 0;
        len = 82;
        result = query.data(solana_address, offset, len);
        if (result.length != 82) {
            return false;
        }

        return true;
    }

    function test_data_nonexistent_account() public returns (bool) {
        uint256 solana_address = 90000; // hopefully does not exist
        uint64 offset = 0;
        uint64 len = 1;
        try query.data(solana_address, offset, len) {
            //
        } catch {
            return true; // expected exception
        }
        return false;
    }

    function test_data_too_big_offset() public returns (bool) {
        uint256 solana_address = 110178555362476360822489549210862241441608066866019832842197691544474470948129;
        uint64 offset = 200; // data len is 82
        uint64 len = 1;
        try query.data(solana_address, offset, len) {
            //
        } catch {
            return true; // expected exception
        }
        return false;
    }

    function test_data_too_big_length() public returns (bool) {
        uint256 solana_address = 110178555362476360822489549210862241441608066866019832842197691544474470948129;
        uint64 offset = 0;
        uint64 len = 200; // data len is 82
        try query.data(solana_address, offset, len) {
            //
        } catch {
            return true; // expected exception
        }
        return false;
    }
}
'''

class Test_Query_Account_Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print('\n\n' + issue)
        print('user address:', user.address)
        cls.deploy_contract(cls)

    def deploy_contract(self):
        compiled = compile_source(CONTRACT_SOURCE)
        id, interface = compiled.popitem()
        self.contract = interface
        contract = proxy.eth.contract(abi=self.contract['abi'], bytecode=self.contract['bin'])
        nonce = proxy.eth.get_transaction_count(proxy.eth.default_account)
        tx = {'nonce': nonce}
        tx_constructor = contract.constructor().buildTransaction(tx)
        tx_deploy = proxy.eth.account.sign_transaction(tx_constructor, admin.key)
        tx_deploy_hash = proxy.eth.send_raw_transaction(tx_deploy.rawTransaction)
        tx_deploy_receipt = proxy.eth.wait_for_transaction_receipt(tx_deploy_hash)
        self.contract_address = tx_deploy_receipt.contractAddress

    # @unittest.skip("a.i.")
    def test_metadata_ok(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_metadata_ok = query.functions.test_metadata_ok().call()
        assert(get_metadata_ok)

    # @unittest.skip("a.i.")
    def test_metadata_nonexistent_account(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_metadata_nonexistent_account = query.functions.test_metadata_nonexistent_account().call()
        assert(get_metadata_nonexistent_account)

    # @unittest.skip("a.i.")
    def test_data_ok(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_data_ok = query.functions.test_data_ok().call()
        assert(get_data_ok)

    # @unittest.skip("a.i.")
    def test_data_nonexistent_account(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_data_nonexistent_account = query.functions.test_data_nonexistent_account().call()
        assert(get_data_nonexistent_account)

    # @unittest.skip("a.i.")
    def test_data_too_big_offset(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_data_too_big_offset = query.functions.test_data_too_big_offset().call()
        assert(get_data_too_big_offset)

    # @unittest.skip("a.i.")
    def test_data_too_big_length(self):
        print
        query = proxy.eth.contract(address=self.contract_address, abi=self.contract['abi'])
        get_data_too_big_length = query.functions.test_data_too_big_length().call()
        assert(get_data_too_big_length)

if __name__ == '__main__':
    unittest.main()