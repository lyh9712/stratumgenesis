"""ECDSA 区块签名单元测试。"""

import unittest
from dataclasses import replace

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import validate_block
from chain_store import ChainStore
from crypto_key import generate_miner_keypair, sign_block_payload, verify_block_signature
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens


class CryptoSignTests(unittest.TestCase):
    def make_signed_block(self, store: ChainStore, private_key=None, public_key=None) -> Block:
        if private_key is None or public_key is None:
            private_key, public_key = generate_miner_keypair()
        prompt = "design a signed deterministic extension with sandbox tests"
        output = "reasoning token " * 12
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal("signed-feature", "pure extension", "(+ 1 2)", (TestCase("(+ 1 2)", 3),))
        poi = PoiRecord("manual", prompt, output, MOCK_TOKENIZER_ID,
                        counts.standard_input_tokens, counts.standard_output_tokens,
                        counts.standard_total_tokens)
        unsigned = Block(1, store.tip.block_hash, "signed-miner", proposal, poi, miner_pubkey=public_key)
        signature = sign_block_payload(private_key, unsigned.canonical_bytes())
        return replace(unsigned, signature_bytes=signature)

    def test_normal_signature_verifies_and_block_is_accepted(self):
        store = ChainStore()
        block = self.make_signed_block(store)
        self.assertTrue(verify_block_signature(block.miner_pubkey, block.canonical_bytes(), block.signature_bytes))
        result = validate_block(block, store)
        self.assertTrue(result.accepted, result)
        self.assertEqual(result.checked_stages[0], "signature")

    def test_tampered_block_content_fails_signature(self):
        store = ChainStore()
        block = self.make_signed_block(store)
        tampered_proposal = replace(block.proposal, specification="tampered specification")
        tampered = replace(block, proposal=tampered_proposal)
        result = validate_block(tampered, store)
        self.assertFalse(result.accepted)
        self.assertEqual(result.error_code, "SIGNATURE_INVALID")
        self.assertEqual(result.stage, "signature")

    def test_mismatched_private_public_key_fails(self):
        store = ChainStore()
        private_a, public_a = generate_miner_keypair()
        private_b, _ = generate_miner_keypair()
        block = self.make_signed_block(store, private_a, public_a)
        wrong_signature = sign_block_payload(private_b, block.canonical_bytes())
        wrong = replace(block, signature_bytes=wrong_signature)
        self.assertFalse(validate_block(wrong, store).accepted)
        self.assertFalse(verify_block_signature(public_a, block.canonical_bytes(), wrong_signature))

    def test_empty_or_corrupt_signature_fails(self):
        store = ChainStore()
        block = self.make_signed_block(store)
        for signature in (b"", b"not-an-ecdsa-signature", b"\x00" * 8):
            invalid = replace(block, signature_bytes=signature)
            result = validate_block(invalid, store)
            self.assertFalse(result.accepted)
            self.assertEqual(result.error_code, "SIGNATURE_INVALID")


if __name__ == "__main__":
    unittest.main()
