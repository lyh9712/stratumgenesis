"""UTXO 账本与区块交易校验测试。"""

import unittest
from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from utxo_ledger import UTXOValidationError
from utxo_model import make_signed_transaction


class UTXOTests(unittest.TestCase):
    def setUp(self):
        self.store = ChainStore()
        self.a_private, self.a_public = generate_miner_keypair()
        self.b_private, self.b_public = generate_miner_keypair()

    def make_block(self, public_key, feature, transactions=()):
        prompt = "design a deterministic extension with enough sandbox tests"
        output = "reasoning token " * 12
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal(feature, "pure extension", "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
        poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                        counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
        unsigned = Block(self.store.height + 1, self.store.tip.block_hash, "miner", proposal, poi,
                         miner_pubkey=public_key, transactions=transactions)
        return replace(unsigned, signature_bytes=sign_block_payload(self.a_private if public_key == self.a_public else self.b_private, unsigned.canonical_bytes()))

    def mine_a_reward(self):
        block = self.make_block(self.a_public, "reward")
        self.assertTrue(validate_block(block, self.store).accepted)
        self.store.append_main(block)
        return next(utxo for utxo in self.store.utxo_ledger.snapshot() if utxo.pubkey == self.a_public)

    def test_mining_reward_creates_utxo(self):
        reward = self.mine_a_reward()
        self.assertEqual(reward.amount, 100)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.a_public), 100)

    def test_normal_transfer_changes_balances(self):
        reward = self.mine_a_reward()
        tx = make_signed_transaction(self.a_private, [reward], [(self.b_public, 30), (self.a_public, 70)])
        block = self.make_block(self.a_public, "transfer", (tx,))
        self.assertTrue(validate_block(block, self.store).accepted)
        self.store.append_main(block)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.a_public), 170)  # 新区块奖励100 + 找零70
        self.assertEqual(self.store.utxo_ledger.get_balance(self.b_public), 30)

    def test_double_spend_is_rejected(self):
        reward = self.mine_a_reward()
        tx = make_signed_transaction(self.a_private, [reward], [(self.b_public, 100)])
        first = self.make_block(self.a_public, "first", (tx,))
        self.assertTrue(validate_block(first, self.store).accepted)
        self.store.append_main(first)
        second_tx = make_signed_transaction(self.a_private, [reward], [(self.b_public, 100)])
        second = self.make_block(self.a_public, "double-spend", (second_tx,))
        result = validate_block(second, self.store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "utxo")

    def test_bad_transaction_signature_rejected(self):
        reward = self.mine_a_reward()
        tx = make_signed_transaction(self.a_private, [reward], [(self.b_public, 20), (self.a_public, 80)])
        bad_tx = replace(tx, tx_signature=sign_block_payload(self.b_private, tx.canonical_bytes()))
        block = self.make_block(self.a_public, "bad-signature", (bad_tx,))
        result = validate_block(block, self.store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "utxo")

    def test_input_less_than_output_rejected(self):
        reward = self.mine_a_reward()
        tx = make_signed_transaction(self.a_private, [reward], [(self.b_public, 101)])
        block = self.make_block(self.a_public, "overspend", (tx,))
        result = validate_block(block, self.store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "utxo")

    def test_sleeping_branch_does_not_change_ledger(self):
        reward_block = self.make_block(self.a_public, "main-reward")
        self.assertTrue(validate_block(reward_block, self.store).accepted)
        self.store.append_main(reward_block)
        before = self.store.utxo_ledger.snapshot()
        branch_tx = make_signed_transaction(self.a_private, [next(iter(before))], [(self.b_public, 100)])
        branch = self.make_block(self.a_public, "sleeping", (branch_tx,))
        self.assertTrue(validate_block(branch, self.store).accepted)
        self.store.add_sleeping_branch(branch)
        self.assertEqual(self.store.utxo_ledger.snapshot(), before)
        self.assertEqual(self.store.utxo_ledger.get_balance(self.b_public), 0)


if __name__ == "__main__":
    unittest.main()
