"""Общий лимитер Gemini: fixed window на счётчике Redis (здесь — стаб)."""

import pytest

from bot.ratelimit import acquire_gemini_slot


class FakeRedis:
    def __init__(self):
        self.counters = {}

    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def decr(self, key):
        self.counters[key] -= 1

    def expire(self, key, ttl):
        pass


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def test_slots_within_limit_are_immediate():
    conn, clock = FakeRedis(), FakeClock()
    for _ in range(3):
        acquire_gemini_slot(conn, rpm=3, clock=clock, sleep=clock.sleep)
    assert clock.now == 0.0  # ни одного ожидания


def test_over_limit_waits_for_next_window():
    conn, clock = FakeRedis(), FakeClock()
    for _ in range(2):
        acquire_gemini_slot(conn, rpm=2, clock=clock, sleep=clock.sleep)
    acquire_gemini_slot(conn, rpm=2, wait=5, clock=clock, sleep=clock.sleep)
    assert clock.now >= 60  # третий слот достался в следующем окне


def test_timeout():
    conn, clock = FakeRedis(), FakeClock()
    acquire_gemini_slot(conn, rpm=1, clock=clock, sleep=clock.sleep)
    conn.counters = {k: v for k, v in conn.counters.items()}  # окно то же
    with pytest.raises(TimeoutError):
        # окно не сменится: timeout истечёт раньше следующей минуты
        acquire_gemini_slot(conn, rpm=1, wait=5, timeout=30,
                            clock=clock, sleep=clock.sleep)
