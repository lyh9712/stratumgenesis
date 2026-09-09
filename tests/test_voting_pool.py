"""候选区块池、历史贡献权重和冲突投票单元测试（ECDSA 版本）。"""

import unittest

from block_model import Block, PoiRecord, Proposal, TestCase
from block_validator import MIN_POI_TOKENS, validate_block
from candidate_pool import CandidatePool
from chain_store import ChainStore
from conflict_voter import resolve_conflict
from crypto_key import generate_miner_keypair, sign_block_payload
from mock_tokenizer import MOCK_TOKENIZER_ID, count_poi_tokens
from weight_calculator import calculate_historical_weights


class VotingPoolTests(unittest.TestCase):
    def setUp(self):
        self.keys = {}

    def make_block(self, store: ChainStore, miner: str, feature: str, expression: str, expected: int) -> Block:
        prompt = "design a deterministic extension proposal with enough reasoning"
        output = "reasoning token " * (MIN_POI_TOKENS + 3)
        counts = count_poi_tokens(prompt, output)
        proposal = Proposal(feature, "pure extension preserving immutable bind", expression, (TestCase(expression, expected),))
        poi = PoiRecord("manual-mock", prompt, output, MOCK_TOKENIZER_ID,
                        counts.standard_input_tokens, counts.standard_output_tokens, counts.standard_total_tokens)
        private_key, public_key = self.keys.setdefault(miner, generate_miner_keypair())
        unsigned = Block(store.tip.height + 1, store.tip.block_hash, miner, proposal, poi, miner_pubkey=public_key)
        signature = sign_block_payload(private_key, unsigned.canonical_bytes())
        return Block(unsigned.height, unsigned.parent_hash, unsigned.proposer, unsigned.proposal, unsigned.poi,
                     unsigned.prototype_version, public_key, signature)

    def add_valid(self, store: ChainStore, block: Block) -> None:
        result = validate_block(block, store)
        self.assertTrue(result.accepted, result)
        store.append_main(block)

    def test_single_candidate_no_conflict_goes_to_main_chain(self):
        store = ChainStore(); pool = CandidatePool()
        candidate = self.make_block(store, "miner-A", "A", "(+ 1 2)", 3)
        validation = validate_block(candidate, store); self.assertTrue(validation.accepted)
        key = pool.submit_validated(candidate, validation)
        vote = resolve_conflict(pool.remove_group(key), calculate_historical_weights(store.main_chain()))
        self.assertEqual(vote.status, "no_conflict")
        store.apply_vote_result(vote)
        self.assertEqual(store.height, 1)
        self.assertEqual(store.tip.miner_pubkey, self.keys["miner-A"][1])

    def test_two_legal_candidates_use_historical_weighted_vote(self):
        store = ChainStore()
        history = self.make_block(store, "miner-A", "history", "(+ 1 2)", 3); self.add_valid(store, history)
        b = self.make_block(store, "miner-A", "B", "(+ 3 4)", 7)
        c = self.make_block(store, "miner-B", "C", "(+ 5 6)", 11)
        pool = CandidatePool()
        for candidate in (b, c):
            validation = validate_block(candidate, store); self.assertTrue(validation.accepted, validation)
            pool.submit_validated(candidate, validation)
        key = next(iter(pool.groups()))
        vote = resolve_conflict(pool.remove_group(key), calculate_historical_weights(store.main_chain()))
        self.assertEqual(vote.status, "won"); self.assertIs(vote.winner, b); self.assertEqual(vote.losers, (c,))
        store.apply_vote_result(vote)
        self.assertEqual(store.tip.block_hash, b.block_hash)
        self.assertIn(c.block_hash, [block.block_hash for block in store.all_blocks()])

    def test_equal_weights_produce_tie_and_all_go_to_sleeping_branch(self):
        store = ChainStore(); pool = CandidatePool()
        b = self.make_block(store, "miner-B", "B", "(+ 3 4)", 7)
        c = self.make_block(store, "miner-C", "C", "(+ 5 6)", 11)
        for candidate in (b, c):
            validation = validate_block(candidate, store); self.assertTrue(validation.accepted, validation)
            pool.submit_validated(candidate, validation)
        key = next(iter(pool.groups()) )
        vote = resolve_conflict(pool.remove_group(key), calculate_historical_weights(store.main_chain()))
        self.assertEqual(vote.status, "vote_tie"); self.assertIsNone(vote.winner); self.assertEqual(set(vote.losers), {b, c})
        store.apply_vote_result(vote)
        self.assertEqual(store.height, 0)
        sleeping = [block for branch in store.sleeping_branches().values() for block in branch]
        self.assertEqual({block.block_hash for block in sleeping}, {b.block_hash, c.block_hash})

    def test_sleeping_branch_does_not_contribute_weight(self):
        store = ChainStore()
        main = self.make_block(store, "main-miner", "main", "(+ 1 2)", 3); self.add_valid(store, main)
        branch = self.make_block(store, "branch-miner", "branch", "(+ 4 5)", 9)
        self.assertTrue(validate_block(branch, store).accepted); store.add_sleeping_branch(branch)
        weights = calculate_historical_weights(store.main_chain())
        self.assertEqual(weights[self.keys["main-miner"][1]], main.poi.standard_total_tokens)
        self.assertNotIn(self.keys["branch-miner"][1], weights)

    def test_candidate_pool_groups_by_parent_and_height(self):
        store = ChainStore(); pool = CandidatePool()
        b = self.make_block(store, "B", "B", "(+ 1 2)", 3); c = self.make_block(store, "C", "C", "(+ 2 3)", 5)
        for candidate in (b, c):
            validation = validate_block(candidate, store); self.assertTrue(validation.accepted)
            pool.submit_validated(candidate, validation)
        self.assertEqual(len(pool.groups()), 1)
        key = next(iter(pool.groups()))
        self.assertEqual((key.parent_block_hash, key.target_height), (store.tip.block_hash, 1))
        self.assertEqual(len(pool.get_group(key.parent_block_hash, key.target_height)), 2)


if __name__ == "__main__":
    unittest.main()
