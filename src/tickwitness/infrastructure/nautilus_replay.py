"""Lazy, bounded Nautilus v1 qualification adapter, without strategy source execution."""

from decimal import ROUND_HALF_EVEN, Context, localcontext
from importlib import metadata

from tickwitness.domain.replay.capabilities import EngineCapabilities, ReplayCapability
from tickwitness.domain.replay.contracts import ReplayInput, ReplayResult, build_replay_result
from tickwitness.domain.replay.preflight import preflight_replay

ENGINE_ID = "nautilus-trader"
ENGINE_VERSION = "1.231.0"
SEMANTIC_ID = "nautilus_v1_receive_order_single_limit_buy_v1"
CAPABILITIES = EngineCapabilities(
    ENGINE_ID,
    ENGINE_VERSION,
    frozenset(
        {
            ReplayCapability.INPUT_EVENT_TRACE,
            ReplayCapability.DECISION_TRACE,
            ReplayCapability.ORDER_LIFECYCLE,
            ReplayCapability.FILL_TRACE,
            ReplayCapability.ACCOUNT_LEDGER,
        }
    ),
)


class ReplayDependencyError(RuntimeError):
    """The optional pinned native dependency cannot be used in this environment."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReplayEngineError(RuntimeError):
    """Native execution or its evidence collection failed; there is no success result."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NautilusReplayAdapter:
    """Replay only the validated built-in single-limit-buy qualification protocol.

    This adapter neither evaluates a research claim nor certifies the source clock.
    Native code is an optional dependency and is imported only after preflight.
    """

    @property
    def capabilities(self) -> EngineCapabilities:
        """Declare this tested profile; availability is checked separately at run time."""
        return CAPABILITIES

    def run(self, replay_input: ReplayInput) -> ReplayResult:
        prepared = preflight_replay(replay_input)
        try:
            installed = metadata.version("nautilus_trader")
        except metadata.PackageNotFoundError as error:
            raise ReplayDependencyError(
                "missing_dependency", "Install the optional nautilus extra for native replay"
            ) from error
        if installed != ENGINE_VERSION:
            raise ReplayDependencyError(
                "version_mismatch",
                f"Replay requires NautilusTrader {ENGINE_VERSION}, got {installed}",
            )
        try:
            # The private bridge is the only boundary permitted to construct native objects.
            from tickwitness.infrastructure._nautilus_native import run_native
        except ImportError as error:
            raise ReplayDependencyError(
                "native_import_failed", "The pinned Nautilus native runtime cannot be imported"
            ) from error
        try:
            # Do not inherit a caller's Decimal precision for units, fees, or native callbacks.
            with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
                return build_replay_result(run_native(prepared))
        except ReplayDependencyError:
            raise
        except ImportError as error:
            raise ReplayDependencyError(
                "native_import_failed", "The pinned Nautilus native runtime cannot be imported"
            ) from error
        except Exception as error:
            raise ReplayEngineError(
                "native_execution_failed", f"Native replay failed: {type(error).__name__}: {error}"
            ) from error
