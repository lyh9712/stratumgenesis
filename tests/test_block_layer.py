"""StratumGenesis 最小区块层原型测试。"""

import unittest

from block_model import Block, PoiRecord, Proposal, TestCase
from crypto_key import generate_miner_keypair, sign_block_payload
from block_validator import MIN_POI_TOKENS, validate_block
from chain_store import ChainStore
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


class BlockLayerTests(unittest.TestCase):
    """覆盖区块结构、PoI、解析和沙箱校验的核心场景。"""

    def setUp(self) -> None:
        self.store = ChainStore()

    def make_block(
        self,
        *,
        parent_hash: str | None = None,
        height: int | None = None,
        specification: str = "add a pure language extension",
        demo: str = "(+ 1 2)",
        test: str = "(+ 1 2)",
        expected: object = 3,
        prompt: str | None = None,
        output: str | None = None,
        declared_counts=None,
    ) -> Block:
        parent_hash = self.store.tip.block_hash if parent_hash is None else parent_hash
        height = self.store.tip.height + 1 if height is None else height
        prompt = prompt or "design a deterministic proposal with tests"
        output = output or ("reasoning token " * (MIN_POI_TOKENS + 2))
        counts = count_poi_tokens(prompt, output)
        if declared_counts is None:
            declared_counts = counts
        proposal = Proposal(
            feature_id=f"feature-{height}-{len(self.store.all_blocks())}",
            specification=specification,
            demo_code=demo,
            test_cases=(TestCase(test, expected),),
        )
        poi = PoiRecord(
            "human-written-mock",
            prompt,
            output,
            MOCK_TOKENIZER_ID,
            declared_counts.standard_input_tokens,
            declared_counts.standard_output_tokens,
            declared_counts.standard_total_tokens,
        )
        private_key, public_key = generate_miner_keypair()
        unsigned = Block(height, parent_hash, "test-author", proposal, poi, miner_pubkey=public_key)
        signature = sign_block_payload(private_key, unsigned.canonical_bytes())
        return Block(height, parent_hash, "test-author", proposal, poi, miner_pubkey=public_key, signature_bytes=signature)

    def assert_rejected(self, block: Block, code: str, stage: str):
        result = validate_block(block, self.store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.error_code, code)
        self.assertEqual(result.stage, stage)
        return result

    def test_valid_block_can_be_added_to_main_chain(self):
        block = self.make_block()
        result = validate_block(block, self.store)
        self.assertTrue(result.accepted, result)
        self.assertEqual(result.checked_stages, ("signature", "structure", "kernel_compatibility", "poi", "parse", "activation", "sandbox", "language_evolution", "utxo"))
        self.store.append_main(block)
        self.assertEqual(self.store.height, 1)
        self.assertEqual(self.store.tip.block_hash, block.block_hash)

    def test_wrong_height(self):
        block = self.make_block(height=7)
        self.assert_rejected(block, "HEIGHT_MISMATCH", "structure")

    def test_parent_not_found(self):
        block = self.make_block(parent_hash="0" * 64, height=1)
        self.assert_rejected(block, "PARENT_NOT_FOUND", "structure")

    def test_genesis_kernel_conflict(self):
        block = self.make_block(specification="修改创世内核并启用严格求值")
        self.assert_rejected(block, "GENESIS_KERNEL_CONFLICT", "kernel_compatibility")

    def test_poi_below_threshold(self):
        prompt, output = "tiny", "tiny"
        counts = count_poi_tokens(prompt, output)
        block = self.make_block(prompt=prompt, output=output, declared_counts=counts)
        self.assert_rejected(block, "POI_BELOW_THRESHOLD", "poi")

    def test_poi_declared_count_mismatch(self):
        prompt, output = "design enough tokens", "reasoning " * 20
        counts = count_poi_tokens(prompt, output)
        fake = type(counts)(counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens + 1)
        block = self.make_block(prompt=prompt, output=output, declared_counts=fake)
        self.assert_rejected(block, "TOKEN_COUNT_MISMATCH", "poi")

    def test_demo_syntax_error(self):
        block = self.make_block(demo="(+ 1 2", test="(+ 1 2)")
        self.assert_rejected(block, "DEMO_PARSE_FAILED", "parse")

    def test_test_syntax_error(self):
        block = self.make_block(demo="(+ 1 2)", test="(+ 1 2")
        self.assert_rejected(block, "TEST_PARSE_FAILED", "parse")

    def test_sandbox_expectation_mismatch(self):
        block = self.make_block(test="(+ 1 2)", expected=999)
        self.assert_rejected(block, "TEST_EXPECTATION_MISMATCH", "sandbox")

    def test_sandbox_runtime_failure(self):
        block = self.make_block(test="missing-name", expected=3)
        self.assert_rejected(block, "TEST_RUNTIME_FAILED", "sandbox")

    def test_sleeping_branch_is_stored_without_changing_main_chain(self):
        block = self.make_block()
        result = validate_block(block, self.store)
        self.assertTrue(result.accepted)
        branch_id = self.store.add_sleeping_branch(block)
        self.assertEqual(branch_id, self.store.tip.block_hash)
        self.assertEqual(self.store.height, 0)
        self.assertIn(block.block_hash, [item.block_hash for item in self.store.all_blocks()])

    def test_block_is_frozen(self):
        block = self.make_block()
        with self.assertRaises(Exception):
            block.height = 9

    def test_genesis_and_hash_parent_link(self):
        genesis = self.store.tip
        self.assertEqual(genesis.height, 0)
        block = self.make_block()
        self.assertEqual(block.parent_hash, genesis.block_hash)
        self.assertEqual(len(block.block_hash), 64)


if __name__ == "__main__":
    unittest.main()
