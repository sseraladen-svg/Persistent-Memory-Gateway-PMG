import json
import unittest

from pmg import waste


def chunk(text, tokens, why="match"):
    return {"text": text, "tokens": tokens, "why": why}


class ReplyTextTests(unittest.TestCase):
    def test_json_response(self):
        body = json.dumps({"choices": [{"message": {"content": "Biscuit eats twice a day"}}]}).encode()
        self.assertEqual(waste.reply_text(body), "Biscuit eats twice a day")

    def test_event_stream(self):
        lines = [json.dumps({"choices": [{"delta": {"content": p}}]}) for p in ("Bis", "cuit", " eats")]
        raw = ("".join(f"data: {l}\n\n" for l in lines) + "data: [DONE]\n\n").encode()
        self.assertEqual(waste.reply_text(raw), "Biscuit eats")

    def test_garbage_gives_empty(self):
        for raw in (b"", b"not json", b"data: {oops}\n\n", b"[]"):
            self.assertEqual(waste.reply_text(raw), "")


class EchoTests(unittest.TestCase):
    def test_counts_only_matched_chunks_that_were_echoed(self):
        chunks = [chunk("my dog is named Biscuit", 8), chunk("the audit deadline is March 3", 10),
                  chunk("answer in short sentences", 7, why="always")]
        echoed, total = waste.echoed_tokens(chunks, "Biscuit would like a walk.")
        self.assertEqual((echoed, total), (8, 18))  # the always-loaded instruction is not measured

    def test_word_forms_meet(self):
        self.assertEqual(waste.echoed_tokens([chunk("I enjoy running every morning", 9)], "You run each morning")[0], 9)

    def test_nothing_matched_means_nothing_measured(self):
        self.assertEqual(waste.echoed_tokens([chunk("always be brief", 5, why="always")], "ok"), (0, 0))


if __name__ == "__main__":
    unittest.main()
