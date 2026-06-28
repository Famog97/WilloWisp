"""
M5.1 — TkEventDispatcher (the Tk R-HEX-2 adapter).

Driven with a fake root (anything exposing .after) so it's testable with no display.
"""
from adapters.driving.ui_tkinter.dispatcher import TkEventDispatcher
from core.ports.event_dispatcher import EventDispatcher


class _FakeRoot:
    def __init__(self):
        self.scheduled = []
    def after(self, ms, fn):
        self.scheduled.append(ms)
        fn()                      # run synchronously to mimic the loop firing


def test_is_an_event_dispatcher():
    assert isinstance(TkEventDispatcher(_FakeRoot()), EventDispatcher)


def test_marshals_callable_via_after_zero():
    root = _FakeRoot()
    d = TkEventDispatcher(root)
    out = []
    d.dispatch(lambda x, y=0: out.append((x, y)), 7, y=9)
    assert root.scheduled == [0]
    assert out == [(7, 9)]


def test_inline_fallback_when_loop_is_gone():
    class DeadRoot:
        def after(self, ms, fn):
            raise RuntimeError("application has been destroyed")
    out = []
    TkEventDispatcher(DeadRoot()).dispatch(lambda: out.append(1))
    assert out == [1]   # ran inline instead of raising
