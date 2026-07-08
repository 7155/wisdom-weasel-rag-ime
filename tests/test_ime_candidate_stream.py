from __future__ import annotations

import unittest

from rag_ime.ime_candidate_stream import ImeCandidateStreamParser


class ImeCandidateStreamParserTests(unittest.TestCase):
    def test_stream_parser_returns_first_candidate_before_end_marker(self) -> None:
        parser = ImeCandidateStreamParser(max_candidates=3)

        self.assertEqual(parser.feed("<CAND>\n候选稳定性"), ["候选稳定性"])
        self.assertFalse(parser.done())

    def test_stream_parser_stops_after_three_candidates(self) -> None:
        parser = ImeCandidateStreamParser(max_candidates=3)
        parser.feed("<CAND>\n候选稳定性\t显示状态机\t刷新显示解耦\t不应继续")

        self.assertEqual(parser.candidates, ["候选稳定性", "显示状态机", "刷新显示解耦"])
        self.assertTrue(parser.done())

    def test_stream_parser_filters_generic_filler_and_context_echo(self) -> None:
        parser = ImeCandidateStreamParser(max_candidates=3, recent_context="这个输入法目前最影响体验的是候选稳定性")
        parser.feed("<CAND>\n下一步\t候选稳定性\t显示状态机")

        self.assertEqual(parser.candidates, ["显示状态机"])

    def test_stream_parser_filters_repeated_tail_echo(self) -> None:
        parser = ImeCandidateStreamParser(
            max_candidates=3,
            current_input="继续继续下一步继续完善一下继续完善一下",
        )
        parser.feed("<CAND>\n继续完善一下\t继续完善一下继续完善一下\t换一个方向")

        self.assertEqual(parser.candidates, ["换一个方向"])

    def test_stream_parser_stops_on_prompt_echo(self) -> None:
        parser = ImeCandidateStreamParser(max_candidates=3)
        parser.feed("<IMEV1>\n<CAND>\n候选稳定性")

        self.assertTrue(parser.done())


if __name__ == "__main__":
    unittest.main()
