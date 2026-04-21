import unittest
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

from core.models import ChannelInfo
from core.session import AppSession
from interface import prompter_channel


class ChannelPrompterTests(unittest.TestCase):
    def test_filter_channels_matches_name_and_count_keywords(self) -> None:
        channels = [
            ChannelInfo(name="/camera/front", count=10),
            ChannelInfo(name="/radar", count=5),
        ]

        filtered_channels = prompter_channel._filter_channels(channels, "camera 10")

        self.assertEqual([channel.name for channel in filtered_channels], ["/camera/front"])

    def test_select_channels_wizard_filters_then_returns_selected_channel(self) -> None:
        channels = [
            ChannelInfo(name="/camera/front", count=10),
            ChannelInfo(name="/radar", count=5),
        ]

        with patch(
            "interface.prompter_channel.prompter.prompt_text",
            side_effect=["/camera", "1"],
        ):
            selected_channels = prompter_channel.select_channels_wizard(
                channels,
                prompt="选择频道",
            )

        self.assertEqual(selected_channels, ["/camera/front"])

    def test_get_paths_channels_returns_empty_when_confirm_declined(self) -> None:
        session = cast(AppSession, SimpleNamespace())

        result = prompter_channel.get_paths_channels(
            session,
            ["/tmp/soc1/demo.record"],
            lambda prompt, default: False,
        )

        self.assertEqual(result, [])

    def test_get_paths_channels_merges_channels_from_distinct_socs(self) -> None:
        recorder = SimpleNamespace(
            get_info=Mock(
                side_effect=[
                    SimpleNamespace(
                        channels=[
                            ChannelInfo(name="/camera/front", count=10),
                            ChannelInfo(name="/radar", count=5),
                        ]
                    ),
                    SimpleNamespace(
                        channels=[
                            ChannelInfo(name="/camera/front", count=20),
                        ]
                    ),
                ]
            )
        )
        session = cast(AppSession, SimpleNamespace(recorder=recorder))

        with patch(
            "interface.prompter_channel.select_channels_wizard",
            side_effect=lambda channels, prompt: [channel.name for channel in channels],
        ):
            selected_channels = prompter_channel.get_paths_channels(
                session,
                [
                    "/tmp/root/soc1/demo.record",
                    "/tmp/root/soc2/demo.record",
                ],
                lambda prompt, default: True,
            )

        self.assertEqual(selected_channels, ["/camera/front", "/radar"])
        self.assertEqual(recorder.get_info.call_count, 2)


if __name__ == "__main__":
    unittest.main()
