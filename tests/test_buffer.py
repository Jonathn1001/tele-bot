from datetime import datetime, timedelta

from buffer import Message, MessageBuffer


def _msg(text: str, channel: str = "@ch", offset_secs: float = 0.0) -> Message:
    return Message(channel=channel, text=text, date=datetime.now() + timedelta(seconds=offset_secs))


def test_add_stores_messages():
    buf = MessageBuffer()
    buf.add("@ch", _msg("hello"))
    assert buf.total_size() == 1


def test_get_all_returns_all_messages():
    buf = MessageBuffer()
    buf.add("@ch", _msg("a"))
    buf.add("@ch", _msg("b"))
    assert len(buf.get_all()) == 2


def test_get_all_sorted_by_date():
    buf = MessageBuffer()
    m1 = _msg("first", offset_secs=0)
    m2 = _msg("second", offset_secs=1)
    buf.add("@ch", m2)
    buf.add("@ch", m1)
    result = buf.get_all()
    assert result[0].text == "first"
    assert result[1].text == "second"


def test_get_all_limit_returns_newest():
    buf = MessageBuffer()
    for i in range(10):
        buf.add("@ch", _msg(f"msg{i}", offset_secs=float(i)))
    result = buf.get_all(limit=3)
    assert len(result) == 3
    assert result[-1].text == "msg9"


def test_is_empty_true_when_no_messages():
    buf = MessageBuffer()
    assert buf.is_empty()


def test_is_empty_false_after_add():
    buf = MessageBuffer()
    buf.add("@ch", _msg("hello"))
    assert not buf.is_empty()


def test_total_size_sums_across_channels():
    buf = MessageBuffer()
    buf.add("@ch1", _msg("a", "@ch1"))
    buf.add("@ch1", _msg("b", "@ch1"))
    buf.add("@ch2", _msg("c", "@ch2"))
    assert buf.total_size() == 3


def test_channel_sizes_returns_per_channel_counts():
    buf = MessageBuffer()
    buf.add("@ch1", _msg("a", "@ch1"))
    buf.add("@ch1", _msg("b", "@ch1"))
    buf.add("@ch2", _msg("c", "@ch2"))
    sizes = buf.channel_sizes()
    assert sizes["@ch1"] == 2
    assert sizes["@ch2"] == 1


def test_deque_evicts_oldest_when_maxsize_exceeded():
    buf = MessageBuffer(maxsize=3)
    for i in range(5):
        buf.add("@ch", _msg(f"msg{i}"))
    assert buf.total_size() == 3
    texts = [m.text for m in buf.get_all()]
    assert "msg0" not in texts
    assert "msg1" not in texts
    assert "msg4" in texts


def test_get_all_across_multiple_channels():
    buf = MessageBuffer()
    buf.add("@a", _msg("from_a", "@a", offset_secs=0))
    buf.add("@b", _msg("from_b", "@b", offset_secs=1))
    result = buf.get_all()
    assert len(result) == 2
    assert result[0].text == "from_a"
    assert result[1].text == "from_b"
