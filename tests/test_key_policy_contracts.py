from __future__ import annotations

import unittest

from rag_ime.contracts.key_policy import (
    NUMBER_KEYS_PASS_THROUGH,
    NUMBER_KEYS_SELECT_RIME_CANDIDATE,
    OPTION_NUMBER_DISABLED,
    OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL,
    PASSTHROUGH_KEY_POLICY,
    ROUTE_NUMBER_KEY,
    ROUTE_OPTION_NUMBER,
    ROUTE_TAB_KEY,
    SELECTION_ACTION_COMMIT_SIDE_CANDIDATE,
    SELECTION_ACTION_SELECT_RIME_CANDIDATE,
    SIDE_SELECTION_ROUTE_EVENTS,
    TAB_ACCEPT_TOP_PREDICTION,
    key_policy_for_prediction_session,
)


class KeyPolicyContractTests(unittest.TestCase):
    def test_post_commit_policy_keeps_digits_pass_through_and_predictors_on_tab_option_number(self) -> None:
        policy = key_policy_for_prediction_session(
            {"phase": "post_commit", "inputMode": "post_commit_predicting", "selectionScope": "prediction"}
        )

        self.assertEqual(policy["numberKeys"], NUMBER_KEYS_PASS_THROUGH)
        self.assertEqual(policy["tab"], TAB_ACCEPT_TOP_PREDICTION)
        self.assertEqual(policy["optionNumber"], OPTION_NUMBER_SELECT_PREDICTION_BY_ORDINAL)

    def test_composition_policy_keeps_digits_owned_by_rime(self) -> None:
        policy = key_policy_for_prediction_session(
            {"phase": "anchor_composing", "inputMode": "anchor_composing", "selectionScope": "rime"}
        )

        self.assertEqual(policy["numberKeys"], NUMBER_KEYS_SELECT_RIME_CANDIDATE)
        self.assertEqual(policy["optionNumber"], OPTION_NUMBER_DISABLED)

    def test_unknown_or_raw_mode_uses_passthrough_policy(self) -> None:
        self.assertEqual(key_policy_for_prediction_session({"phase": "raw_passthrough"}), PASSTHROUGH_KEY_POLICY)

    def test_selection_actions_and_route_events_are_stable_contract_names(self) -> None:
        self.assertEqual(SELECTION_ACTION_COMMIT_SIDE_CANDIDATE, "commit_side_candidate")
        self.assertEqual(SELECTION_ACTION_SELECT_RIME_CANDIDATE, "select_rime_candidate")
        self.assertEqual(SIDE_SELECTION_ROUTE_EVENTS, {ROUTE_NUMBER_KEY, ROUTE_TAB_KEY, ROUTE_OPTION_NUMBER})


if __name__ == "__main__":
    unittest.main()
