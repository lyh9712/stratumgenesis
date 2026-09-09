"""纪元基础框架测试。"""

import unittest
from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload
from epoch_manager import EpochManager
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


class EpochTests(unittest.TestCase):
    def setUp(self):
        self.store = ChainStore()
        self.private, self.public = generate_miner_keypair()

    def make_block(self, height=None, epoch=-1):
        target = self.store.height + 1 if height is None else height
        prompt = "design a deterministic epoch extension with sandbox tests"
        output = "reasoning token " * (MIN_POI_TOKENS + 2)
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal(f"epoch-{target}", "pure extension", "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
        poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                        counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
        unsigned = Block(target, self.store.tip.block_hash, "epoch-miner", proposal, poi,
                          miner_pubkey=self.public, epoch=epoch)
        return replace(unsigned, signature_bytes=sign_block_payload(self.private, unsigned.canonical_bytes()))

    def append(self, block):
        self.assertTrue(validate_block(block, self.store).accepted)
        self.store.append_main(block)

    def test_height_automatically_calculates_epoch(self):
        self.assertEqual(EpochManager.get_epoch_of_block(0), 0)
        self.assertEqual(EpochManager.get_epoch_of_block(99), 0)
        self.assertEqual(EpochManager.get_epoch_of_block(100), 1)
        block = self.make_block(height=100)
        self.assertEqual(block.epoch, 1)

    def test_explicit_inconsistent_epoch_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            self.make_block(height=100, epoch=0)

    def test_tampered_epoch_is_rejected_by_structure(self):
        block = self.make_block(height=1)
        object.__setattr__(block, "epoch", 9)
        # 为了测试第1步而不是第0步，重新用同一公钥对应私钥签名篡改后的 canonical bytes。
        object.__setattr__(block, "signature_bytes", sign_block_payload(self.private, block.canonical_bytes()))
        result = validate_block(block, self.store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.stage, "structure")
        self.assertEqual(result.error_code, "EPOCH_MISMATCH")

    def test_height_99_and_100_boundary(self):
        for height in range(1, 101):
            block = self.make_block(height=height)
            self.append(block)
        self.assertEqual(self.store.get_block(self.store.main_chain()[99].block_hash).epoch, 0)
        self.assertEqual(self.store.tip.height, 100)
        self.assertEqual(self.store.tip.epoch, 1)
        self.assertEqual(EpochManager.get_epoch_of_block(99), 0)
        self.assertEqual(EpochManager.get_epoch_of_block(100), 1)

    def test_main_chain_boundary_creates_archived_epoch_zero_snapshot(self):
        for _ in range(100):
            self.append(self.make_block())
        snapshot = self.store.epoch_manager.get_epoch_snapshot(0)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.start_height, 0)
        self.assertEqual(snapshot.end_height, 99)
        self.assertEqual(len(snapshot.block_hashes), 100)
        self.assertTrue(snapshot.archived)
        current = self.store.epoch_manager.get_epoch_snapshot(1)
        self.assertIsNotNone(current)
        self.assertFalse(current.archived)

    def test_sleeping_branch_epoch_does_not_create_snapshot(self):
        for _ in range(100):
            self.append(self.make_block())
        before = self.store.epoch_manager.snapshots()
        branch = self.make_block(height=101)
        self.assertEqual(branch.epoch, 1)
        self.store.add_sleeping_branch(branch)
        self.assertEqual(self.store.epoch_manager.snapshots(), before)
        self.assertEqual(self.store.height, 100)


if __name__ == "__main__":
    unittest.main()
