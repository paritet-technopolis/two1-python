import math
from unittest.mock import MagicMock

from two1.bitcoin.crypto import HDKey, HDPrivateKey, HDPublicKey
from two1.bitcoin.txn import Transaction
from two1.wallet.account_types import AccountType, account_types
from two1.wallet.hd_account import HDAccount
from two1.wallet.txn_data_provider import TransactionDataProvider

class MockTxnDict(dict):
    def __init__(self, num_used, addr_range, addr_list, used_value, unused_value):
        self.num_used = num_used
        self.addr_range = addr_range
        self.addr_list = addr_list
        self.used_value = used_value
        self.unused_value = unused_value

        self.start = max([0, self.addr_range.start])
        self.end = min([self.num_used, self.addr_range.stop])

    def __getitem__(self, item):
        if item in self:
            return self.used_value
        else:
            return self.unused_value

    def __contains__(self, item):
        if self.num_used == 0 or self.start > self.end:
            return False

        return item in self.addr_list[self.start:self.end]


class MockTransactionDataProvider(TransactionDataProvider):
    methods = ['get_balance', 'get_transactions', 'get_utxo',
               'get_balance_hd', 'get_transactions_hd', 'get_utxo_hd',
               'send_transaction']
    address_increment = HDAccount.DISCOVERY_INCREMENT
    max_address = 8 * address_increment
    max_accounts = 10
    
    def __init__(self, hd_account_type, hd_master_key, non_hd_addr_list=[]):
        super().__init__()

        if isinstance(hd_account_type, str):
            if hd_account_type not in account_types:
                raise ValueError("hd_account_type must be one of %r." % account_types.keys())
            else:
                self.account_type = account_types[hd_account_type]
        elif isinstance(hd_account_type, AccountType):
            self.account_type = hd_account_type
        else:
            raise TypeError("hd_account_type should be a str or AccountType object")

        self._num_used_addresses = {}
        self._num_used_accounts = 0

        for i in range(self.max_accounts):
            self._num_used_addresses[i] = {0: 0, 1: 0}

        self.addr_list = non_hd_addr_list
        self.hd_master_key = hd_master_key

        for m in self.methods:
            setattr(self, m, MagicMock())

        self._setup_balances_hd()
        
    def reset_mocks(self, methods=[]):
        if not methods:
            methods = self.methods

        for m in methods:
            if hasattr(self, m):
                g = getattr(self, m)
                g.reset_mock()

    @property
    def hd_master_key(self):
        return self._hd_master_key

    @hd_master_key.setter
    def hd_master_key(self, k):
        self._hd_master_key = k
        self._acct_keys = {}

        keys = HDKey.from_path(self._hd_master_key, self.account_type.account_derivation_prefix)
        for i in range(self.max_accounts):
            acct_key = HDPrivateKey.from_parent(keys[-1], 0x80000000 | i)
            payout_key = HDPrivateKey.from_parent(acct_key, 0)
            change_key = HDPrivateKey.from_parent(acct_key, 1)
                
            payout_addresses = [HDPublicKey.from_parent(payout_key.public_key, i).address()
                                     for i in range(self.max_address)]
            change_addresses = [HDPublicKey.from_parent(change_key.public_key, i).address()
                                     for i in range(self.max_address)]

            self._acct_keys[i] = {'acct_key': acct_key,
                                  'payout_key': payout_key,
                                  'change_key': change_key,
                                  'payout_addresses': payout_addresses,
                                  'change_addresses': change_addresses}

            self._num_used_addresses[i][0] = 0
            self._num_used_addresses[i][1] = 0

        self._setup_balances_hd()

    def set_num_used_addresses(self, account_index, n, change):
        self._num_used_addresses[account_index][change] = n
        self._setup_balances_hd()

    def set_num_used_accounts(self, n):
        self._num_used_accounts = n
        self._setup_balances_hd()
        
    def _setup_balances_hd(self):
        d = {}
        for i in range(self._num_used_accounts):
            payout_addresses = self._acct_keys[i]['payout_addresses'][:self._num_used_addresses[i][0]]
            change_addresses = self._acct_keys[i]['change_addresses'][:self._num_used_addresses[i][1]]

            d.update({a: (0, 10000) for a in change_addresses})
            d.update({a: (100000, 0) for a in payout_addresses})
            
        self.get_balance_hd = MagicMock(return_value=d)

    def set_txn_side_effect_for_index(self, account_index, address_index, change):
        dummy_txn = Transaction(1, [], [], 0)

        addr_list = self._acct_keys[account_index]['change_addresses' if change else 'payout_addresses']
        self.get_transactions.side_effect = [MockTxnDict(num_used=address_index + 1,
                                                         addr_range=range(address_index, address_index + 1),
                                                         addr_list=addr_list,
                                                         used_value=[dummy_txn],
                                                         unused_value=[])]
        
    def set_txn_side_effect_for_hd_discovery(self):
        dummy_txn = Transaction(1, [], [], 0)

        # For each used account, there are at least 2 calls required:
        # 1 for the first DISCOVERY_INCREMENT payout addresses and 1 for the first
        # DISCOVERY_INCREMENT change addresses. Depending on the number of used
        # addresses for the account, this will change.
        
        effects = []

        n = self._num_used_accounts
        if n == 0:
            n = 1
        
        for acct_num in range(n):
            for change in [0, 1]:
                num_used = self._num_used_addresses[acct_num][change]
                r = math.ceil((num_used + HDAccount.GAP_LIMIT) / self.address_increment)
                addr_list = self._acct_keys[acct_num]['change_addresses' if change else 'payout_addresses']

                if r == 0:
                    r = 1
                for i in range(r):
                    effects.append(MockTxnDict(num_used=num_used,
                                               addr_range=range(i * self.address_increment, (i + 1) * self.address_increment),
                                               addr_list=addr_list,
                                               used_value=[dummy_txn],
                                               unused_value=[]))

        self.get_transactions.side_effect = effects
        
        return len(effects)

    
